"""Trader tracking + copy-trade decisioning (brief Sections 10-13).

Scope note: this package makes decisions from `trader_trades` rows that
already exist in the database. It does not itself scrape, poll, or
otherwise acquire real trader/wallet activity — Section 4 of the brief
requires any such feed to come from an authorized, public API, and none
has been chosen yet (the same boundary Phase 2 drew around exchange
adapters: a real integration is added once a specific, authorized data
source exists, never reverse-engineered).
"""
