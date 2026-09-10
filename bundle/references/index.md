# References

Executable trust infrastructure for the attested computations:

- [executors/run-duckdb.md](/references/executors/run-duckdb.md) — the
  contract for executing a sanctioned computation and producing a receipt.
- `attesters/sql_equality.py` — the deterministic (no-LLM) attester that
  verifies receipts: SQL equality, independent binding re-derivation, and
  hash integrity. It re-implements the fiscal calendar on purpose; see the
  module docstring before touching it.
