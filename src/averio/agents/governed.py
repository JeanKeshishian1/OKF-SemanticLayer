"""The governed agent: the baseline PLUS the semantic layer - nothing else.

Same model, same tool loop, same run_sql data access, same schema block.
The additions are exactly the layer: four tools wrapping ``SemanticLayer``
(resolve / ambiguity_rule / security_rules / compute) and a mandate that
requires consulting them. run_sql is deliberately KEPT: identical data
access is a design requirement, and a governed agent that bypasses
compute() for an ad-hoc figure commits a *scored policy violation* - the
eval wants to observe that temptation, not make it physically impossible.

Layer tool failures (unresolvable term, refused parameters, ambiguity)
return as ``{"error": ...}`` data: for this agent, an error is often the
ANSWER - the signal to clarify or abstain rather than improvise.
"""

from __future__ import annotations

from averio.agents.common import AgentRunner, Tool, make_run_sql, schema_block
from averio.semantic_layer import SemanticLayer

# The mandate encodes the handoff's execution playbook, not domain facts:
# the facts (definitions, calendars, rules) come from the layer at runtime,
# which is what makes the bundle - not this prompt - the knowledge source.
GOVERNED_MANDATE = """\
You are a data analyst for Averio's Middle East & Africa business,
operating under a governed semantic layer. The layer - not your general
knowledge - is the authority on what business terms mean here.

Mandatory working rules:
1. Resolve business terms with the resolve tool before using them. A term
   the layer does not resolve is NOT governed: do not improvise a
   definition from the raw schema - clarify with the user or abstain,
   saying the concept is not governed.
2. For an ambiguous term (customer, country, business, product, amount,
   period, bookings scope), consult ambiguity_rule and follow it: apply
   the default silently, ask the stated clarification, or abstain.
3. Headline figures MUST come from the compute tool (sanctioned, attested
   computation). For a breakdown or ranking of a governed metric by one of
   its allowed dimensions (BU, HFM PG Name, Booking Type, Interco & Trade,
   or masked party IDs), use run_sql applying that metric's sanctioned
   formula over the FY/PD window, and attest the corresponding total with
   compute. Never use run_sql to invent ungoverned metrics, produce
   figures on other bases, or bypass a refusal.
4. Apply security_rules BEFORE querying and again BEFORE answering. Never
   output person or organization names - identify parties by ID. Never
   present row-level restricted detail; aggregates only.
5. If compute flags a result as stale, you must say so in the answer,
   with the reason.
6. End with the answer plus its provenance: metric, window, confidence
   level, trust tier, and any caveats or staleness flags the layer
   returned.
"""


def _layer_tools(layer: SemanticLayer) -> list[Tool]:
    """Wrap the SemanticLayer facade as function-calling tools.

    Wrappers convert layer exceptions into error payloads because the
    model must SEE refusals to act on them - an ExecutionRefused about a
    missing currency is the currency-discipline policy talking.
    """

    def resolve(term: str) -> dict:
        try:
            record = layer.resolve(term)
        except Exception as exc:
            return {"error": str(exc)}
        if record is None:
            return {"resolved": None,
                    "note": ("term is not governed by the semantic layer - "
                             "clarify with the user or abstain")}
        return record

    def ambiguity_rule(term: str) -> dict:
        rule = layer.ambiguity_rule(term)
        return rule if rule is not None else {
            "rule": None, "note": "no ambiguity rule for this term"}

    def security_rules() -> dict:
        return layer.security_rules()

    def compute(metric: str, fiscal_year: int, fiscal_period: int | None = None,
                ytd: bool = False, currency: str | None = None,
                trade_scope: str | None = None) -> dict:
        try:
            return layer.compute(metric, fiscal_year=fiscal_year,
                                 fiscal_period=fiscal_period, ytd=ytd,
                                 currency=currency, trade_scope=trade_scope)
        except Exception as exc:
            return {"error": str(exc)}

    period_params = {
        "fiscal_year": {"type": "integer",
                        "description": "FY named for its ENDING calendar year"},
        "fiscal_period": {"type": "integer",
                          "description": "PD 1-12; omit for the full fiscal year"},
        "ytd": {"type": "boolean",
                "description": "with fiscal_period: widen to PD1..fiscal_period"},
    }
    return [
        Tool(name="resolve",
             description=("Resolve a business term to its governed concept: "
                          "definition, confidence, trust tier, staleness, and "
                          "its sanctioned computation if any."),
             parameters={"type": "object",
                         "properties": {"term": {"type": "string"}},
                         "required": ["term"]},
             fn=resolve),
        Tool(name="ambiguity_rule",
             description=("Default / clarify / abstain guidance for an "
                          "ambiguous user term, from the ambiguity policy."),
             parameters={"type": "object",
                         "properties": {"term": {"type": "string"}},
                         "required": ["term"]},
             fn=ambiguity_rule),
        Tool(name="security_rules",
             description=("The output restrictions: blocked columns, "
                          "aggregate-only columns, and the mandatory "
                          "no-names rule."),
             parameters={"type": "object", "properties": {}},
             fn=security_rules),
        Tool(name="compute",
             description=("Execute a governed metric through the sanctioned, "
                          "attested computation path. The ONLY policy-"
                          "compliant source of reported figures."),
             parameters={"type": "object",
                         "properties": {
                             "metric": {"type": "string",
                                        "description": ("concept id (e.g. "
                                                        "'metrics/net-bookings-usd') "
                                                        "or a resolvable term")},
                             **period_params,
                             "currency": {"type": "string",
                                          "description": ("ONLY for the two transaction-"
                                                          "booking-amount metrics, where it "
                                                          "is required (exactly one code); "
                                                          "every other metric takes NO "
                                                          "currency parameter")},
                             "trade_scope": {"type": "string",
                                             "enum": ["operational", "trade"],
                                             "description": ("net bookings only; "
                                                             "'trade' = external "
                                                             "market view")},
                         },
                         "required": ["metric", "fiscal_year"]},
             fn=compute),
    ]


def _metric_catalog(layer: SemanticLayer) -> str:
    """The governed vocabulary, listed - bundle-derived, like index.md.

    Exact-match resolution is a deliberate design choice, but it means a
    term only resolves if the agent *asks with* a declared name or alias.
    Run 1 showed the failure mode: a tax-inclusive EUR question never found
    the transaction-with-tax metric because the agent never guessed a
    resolvable term. Listing the catalog is not extra intelligence - it is
    the same table of contents the bundle's index gives a human reader.
    """
    lines = ["Governed metric catalog (resolve any of these ids or aliases):"]
    for metric in sorted(layer.bundle.by_type("Metric"), key=lambda c: c.concept_id):
        aliases = ", ".join(metric.aliases)
        lines.append(f"- {metric.concept_id}: {metric.title} (aliases: {aliases})")
    return "\n".join(lines)


def build_governed(db_path: str, bundle_dir: str = "bundle",
                   client=None, model: str | None = None) -> AgentRunner:
    """Assemble the governed agent: baseline surface + the semantic layer."""
    layer = SemanticLayer(bundle_dir, db_path)
    system_prompt = "\n".join([
        GOVERNED_MANDATE,
        _metric_catalog(layer),
        "",
        schema_block(db_path),  # identical raw schema; parity with baseline
    ])
    tools = [make_run_sql(db_path), *_layer_tools(layer)]
    return AgentRunner(name="governed", system_prompt=system_prompt,
                       tools=tools, client=client, model=model)
