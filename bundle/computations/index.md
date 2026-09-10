# Attested computations

The only sanctioned way to produce a governed figure. The agent binds
semantic parameters (`fiscal_year`, optional `fiscal_period`, optional
`ytd`, plus per-metric extras) and hands execution to the
[executor](/references/executors/run-duckdb.md); the deterministic
attester then verifies the receipt. The agent never authors, edits, or
re-indents SQL.

- [net-bookings-usd-fp](/computations/net-bookings-usd-fp.md)
- [positive-booking-movements-usd-fp](/computations/positive-booking-movements-usd-fp.md)
- [debookings-usd-fp](/computations/debookings-usd-fp.md)
- [cancellation-debookings-usd-fp](/computations/cancellation-debookings-usd-fp.md)
  — note its freshness state before serving
- [transaction-booking-amount-fp](/computations/transaction-booking-amount-fp.md)
- [transaction-booking-amount-with-tax-fp](/computations/transaction-booking-amount-with-tax-fp.md)
- [distinct-sales-orders-fp](/computations/distinct-sales-orders-fp.md)
