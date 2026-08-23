// Decimal strings are formatted for display only — never parsed back into
// `number` and used in arithmetic, since JS floats can't represent the
// same values the backend's Decimal math guarantees. `Number()` here is a
// one-way trip strictly for `toLocaleString` formatting.

export function formatMoney(value: string, currency = "USD"): string {
  const n = Number(value);
  if (Number.isNaN(n)) return value;
  return n.toLocaleString("en-US", {
    style: "currency",
    currency,
    maximumFractionDigits: 2,
  });
}

export function formatQuantity(value: string): string {
  const n = Number(value);
  if (Number.isNaN(n)) return value;
  return n.toLocaleString("en-US", { maximumFractionDigits: 8 });
}

export function formatPercent(value: string): string {
  const n = Number(value);
  if (Number.isNaN(n)) return value;
  return `${(n * 100).toFixed(2)}%`;
}

export function formatDateTime(value: string): string {
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleString("en-US", {
    dateStyle: "medium",
    timeStyle: "medium",
  });
}
