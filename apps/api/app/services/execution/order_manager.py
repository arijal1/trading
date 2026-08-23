"""Order Manager (brief Sections 24-25).

Every order is keyed by a `client_order_id`. Before ever submitting to
the exchange, `submit_order` checks whether an order with that id
already exists:

- terminal status (FILLED/CANCELLED/REJECTED) -> return it as-is, never
  resubmit.
- in-flight (NEW/SUBMITTED/PARTIALLY_FILLED) with a known
  `exchange_order_id` -> query the exchange for its real status first
  and reconcile, rather than blindly submitting a duplicate. This is
  what Section 25 requires: "FIRST query order status. Only submit
  another order if the previous order is confirmed absent."
- in-flight with NO `exchange_order_id` -> we have no way to ask the
  exchange whether it actually received the previous attempt. Silently
  resubmitting here risks a real duplicate order, so this raises
  `OrderReconciliationRequiredError` instead of guessing — a stuck order
  in this state needs a human (or a real adapter's client-order-id
  lookup, not implemented by the mock) to resolve, never an automatic
  retry.

A unique constraint on `orders.client_order_id` backs this: if two
callers race to create the same client_order_id, the loser's insert
fails and it falls back to fetching (and reconciling) the winner's row —
the same class of fix already applied to the strategy registry and
system_state races found earlier in this project.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.trading import Fill, Order, OrderEvent
from app.schemas.exchange import OrderRequest, OrderSide, OrderStatus, OrderType
from app.services.exchanges.base import ExchangeAdapter, ExchangeAdapterError

_TERMINAL_STATUSES = {
    OrderStatus.FILLED.value,
    OrderStatus.CANCELLED.value,
    OrderStatus.REJECTED.value,
}


class OrderReconciliationRequiredError(RuntimeError):
    """An in-flight order has no exchange_order_id to check status with.

    We cannot safely tell whether the previous submission attempt reached
    the exchange, so we refuse to guess by resubmitting.
    """


class OrderManager:
    def __init__(self, adapter: ExchangeAdapter) -> None:
        self.adapter = adapter

    async def submit_order(
        self,
        db: AsyncSession,
        *,
        account_id: uuid.UUID,
        asset_id: uuid.UUID,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        quantity: Decimal,
        limit_price: Decimal | None = None,
        stop_price: Decimal | None = None,
        decision_id: uuid.UUID | None = None,
        client_order_id: str | None = None,
    ) -> Order:
        client_order_id = client_order_id or str(uuid.uuid4())

        order = await self._get_existing(db, client_order_id)
        if order is not None:
            return await self._reconcile(db, order, symbol)

        order, created_by_me = await self._create_order(
            db,
            account_id=account_id,
            asset_id=asset_id,
            decision_id=decision_id,
            client_order_id=client_order_id,
            side=side,
            order_type=order_type,
            quantity=quantity,
            limit_price=limit_price,
            stop_price=stop_price,
        )
        if not created_by_me:
            # Lost a create race: another concurrent call already inserted
            # this client_order_id (status could be anything, including
            # still NEW) and is the one responsible for submitting it.
            # Never submit a second time on their behalf.
            return await self._reconcile(db, order, symbol)

        request = OrderRequest(
            client_order_id=client_order_id,
            symbol=symbol,
            side=side,
            type=order_type,
            quantity=quantity,
            limit_price=limit_price,
            stop_price=stop_price,
        )
        try:
            result = await self._place(request)
        except ExchangeAdapterError as exc:
            order.status = OrderStatus.REJECTED.value
            order.error = str(exc)
            db.add(
                OrderEvent(
                    order_id=order.id, event_type="REJECTED", payload={"error": str(exc)}
                )
            )
            await db.commit()
            await db.refresh(order)
            return order

        await self._apply_result(db, order, result)
        return order

    async def _get_existing(self, db: AsyncSession, client_order_id: str) -> Order | None:
        result = await db.execute(select(Order).where(Order.client_order_id == client_order_id))
        return result.scalar_one_or_none()

    async def _create_order(
        self,
        db: AsyncSession,
        *,
        account_id: uuid.UUID,
        asset_id: uuid.UUID,
        decision_id: uuid.UUID | None,
        client_order_id: str,
        side: OrderSide,
        order_type: OrderType,
        quantity: Decimal,
        limit_price: Decimal | None,
        stop_price: Decimal | None,
    ) -> tuple[Order, bool]:
        order = Order(
            account_id=account_id,
            decision_id=decision_id,
            client_order_id=client_order_id,
            asset_id=asset_id,
            side=side.value,
            type=order_type.value,
            quantity=quantity,
            limit_price=limit_price,
            stop_price=stop_price,
            status="NEW",
        )
        db.add(order)
        try:
            await db.flush()
        except IntegrityError:
            await db.rollback()
            existing = await self._get_existing(db, client_order_id)
            assert existing is not None  # the unique constraint is what just fired
            return existing, False
        db.add(OrderEvent(order_id=order.id, event_type="CREATED", payload=None))
        await db.commit()
        await db.refresh(order)
        return order, True

    async def _place(self, request: OrderRequest):
        dispatch = {
            (OrderSide.BUY, OrderType.MARKET): self.adapter.place_market_buy,
            (OrderSide.SELL, OrderType.MARKET): self.adapter.place_market_sell,
            (OrderSide.BUY, OrderType.LIMIT): self.adapter.place_limit_buy,
            (OrderSide.SELL, OrderType.LIMIT): self.adapter.place_limit_sell,
        }
        place = dispatch[(request.side, request.type)]
        return await place(request)

    async def _apply_result(self, db: AsyncSession, order: Order, result) -> None:
        previous_status = order.status
        order.exchange_order_id = result.exchange_order_id
        order.status = result.status.value

        already_filled = await db.scalar(
            select(func.coalesce(func.sum(Fill.quantity), 0)).where(Fill.order_id == order.id)
        )
        new_fill_quantity = result.filled_quantity - already_filled

        if new_fill_quantity > 0 and result.avg_fill_price is not None:
            db.add(
                Fill(
                    order_id=order.id,
                    price=result.avg_fill_price,
                    quantity=new_fill_quantity,
                    fee=result.fee,
                )
            )
            event_type = "FILLED" if result.status == OrderStatus.FILLED else "PARTIALLY_FILLED"
            db.add(
                OrderEvent(
                    order_id=order.id,
                    event_type=event_type,
                    payload={
                        "filled_quantity": str(new_fill_quantity),
                        "price": str(result.avg_fill_price),
                    },
                )
            )
        elif previous_status != order.status:
            db.add(
                OrderEvent(
                    order_id=order.id,
                    event_type=order.status,
                    payload={"exchange_order_id": order.exchange_order_id},
                )
            )

        await db.commit()
        await db.refresh(order)

    async def _reconcile(self, db: AsyncSession, order: Order, symbol: str) -> Order:
        if order.status in _TERMINAL_STATUSES:
            return order
        if not order.exchange_order_id:
            raise OrderReconciliationRequiredError(
                f"order {order.id} (client_order_id={order.client_order_id}) is {order.status} "
                "with no exchange_order_id — cannot confirm whether the exchange received it, "
                "refusing to resubmit"
            )
        result = await self.adapter.get_order_status(symbol, order.exchange_order_id)
        await self._apply_result(db, order, result)
        return order

    async def cancel_order(self, db: AsyncSession, order: Order, *, symbol: str) -> Order:
        if order.status in _TERMINAL_STATUSES:
            return order
        if not order.exchange_order_id:
            raise OrderReconciliationRequiredError(
                f"order {order.id} has no exchange_order_id — cannot cancel"
            )
        result = await self.adapter.cancel_order(symbol, order.exchange_order_id)
        await self._apply_result(db, order, result)
        return order
