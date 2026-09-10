"""The baseline agent: same model, same data, NO semantic layer.

This agent is the experiment's counterfactual: a competent analyst given
the raw schema and free SQL access, and nothing else. Its prompt must
stay scrupulously semantics-free - no booking-movement rules, no fiscal
calendar, no customer-role guidance, no security policy. Every one of
those absences is a trap the eval measures, so "improving" this prompt
with domain knowledge would quietly delete the experiment
(tests/test_agents.py guards the prompt against governance vocabulary).

What it DOES get, deliberately:
  * the identical schema block the governed agent sees (identical data
    access is a design requirement), and
  * neutral column profiles as context-parity filler, so the two prompts
    have comparable volume and the eval is not confounded by token count.
"""

from __future__ import annotations

from averio.agents.common import AgentRunner, column_profiles, make_run_sql, schema_block

# Plain analyst instructions: competent, diligent, and entirely ungoverned.
# Nothing here hints at signed movements, fiscal conventions, party roles,
# currency discipline, or disclosure rules.
BASELINE_MANDATE = """\
You are a data analyst for Averio's Middle East & Africa business. You
answer questions about the order/bookings data in a DuckDB database using
the run_sql tool.

Working rules:
- Column names contain spaces: always double-quote them in SQL.
- Investigate the data as needed (inspect values, check columns) before
  answering.
- Finish with a clear final answer: the figure(s) or finding, plus a short
  note on how you computed it.
- If a question cannot be answered from this database, say so.
"""


def build_baseline(db_path: str, client=None, model: str | None = None) -> AgentRunner:
    """Assemble the baseline agent over one database snapshot."""
    system_prompt = "\n".join([
        BASELINE_MANDATE,
        schema_block(db_path),
        "",
        # Parity filler: neutral, derivable-from-data statistics standing
        # in for the token volume the governed agent's mandate occupies.
        column_profiles(db_path),
    ])
    return AgentRunner(name="baseline", system_prompt=system_prompt,
                       tools=[make_run_sql(db_path)], client=client, model=model)
