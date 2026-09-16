"""The semantic layer facade - the only interface the governed agent gets.

``SemanticLayer`` wires the pieces the bundle and harness provide into the
governed answer path:

    term -> resolve()          concept + confidence + trust tier (+ staleness)
         -> ambiguity_rule()   default / clarify / abstain guidance
         -> security_rules()   what may never appear in output
         -> compute()          sanctioned execution -> receipt -> attestation
                               -> value + full provenance

Design constraints, all load-bearing for the experiment:

  * **Resolution is exact.** ``resolve()`` returns None for anything the
    bundle does not name (trap A1: absence is the abstention signal) and
    raises on genuinely ambiguous matches instead of guessing.
  * **compute() refuses to serve unattested figures.** The attester - the
    deterministic script shipped *inside the bundle*, loaded from its
    bundle path - must return ok on the receipt, or the layer raises. An
    answer without a passing attestation is not a governed answer.
  * **Staleness is surfaced, never swallowed** (trap S1): a computation
    past its ``stale_after`` still runs, but the result is flagged with
    the reason, and serving it as current is the agent's scored mistake.
  * **The snapshot dates itself.** ``as_of`` comes from the data's
    REFRESH_DATE stamp, not from a caller argument - "as of when" is a
    property of the snapshot, not a knob.
"""

from __future__ import annotations

import importlib.util
from datetime import date
from pathlib import Path

import duckdb

from averio.bundle_loader import Bundle, Concept, normalize_term, parse_tables
from averio.executor import execute


def layer_confidence(transcript) -> dict:
    """Governance-backed confidence for a governed answer - calculated, not
    self-reported.

    A deterministic function over the run's transcript: it looks only at
    what the layer actually served (attested compute results, their trust
    tiers, staleness, and corroboration) and never at the answer's wording.
    It is the counterpart to the model's verbalized "Confidence: NN%": the
    model reports what it *feels*; this reports what the governance can
    *prove* - as a 0-100 score from a transparent points rubric, with the
    itemized breakdown returned so the UI can show WHY the number is what
    it is. Multiple served figures score conservatively (worst case per
    component).

        Attestation    40  every served figure carries a passing receipt
        Verification   25  all metric definitions human-verified
                       10  ...only machine-verified (strongly supported)
        Freshness      25  nothing past its stale_after; 0 when stale
        Corroboration  10  definitions also dataset-supported

    Answers that served NO computed figure (abstentions, clarifications,
    refusals) are "policy-based": there is no figure to score, so they get
    a label instead of a percentage - that describes the kind of evidence,
    not a defect. ``level`` (high/medium/stale/policy) rides along for
    styling and tests.
    """
    computes = [
        entry["result"] for entry in (transcript or [])
        if isinstance(entry, dict) and entry.get("type") == "tool_call"
        and entry.get("tool") == "compute"
        and isinstance(entry.get("result"), dict) and entry["result"].get("attested")
    ]
    if not computes:
        return {"level": "policy", "score": None, "label": "Layer: policy-based",
                "reason": ("No computed figure was served - the reply rests on "
                           "term resolution, policies, or refusal rules.")}

    provenances = [result.get("provenance") or {} for result in computes]
    human = all(p.get("trust_tier") == "human-reviewed" for p in provenances)
    fresh = not any(result.get("stale") for result in computes)
    corroborated = all(p.get("confidence") == "confirmed-plus-dataset-supported"
                       for p in provenances)

    breakdown = [
        "Attestation 40/40 - every served figure carries a passing receipt",
        ("Verification 25/25 - all metric definitions human-verified" if human
         else "Verification 10/25 - at least one metric is only "
              "machine-verified (strongly-supported tier)"),
        ("Freshness 25/25 - nothing past its stale_after date" if fresh
         else "Freshness 0/25 - a figure came from a computation past its "
              "stale_after date (served flagged)"),
        ("Corroboration 10/10 - definitions also dataset-supported by the "
         "extract profiler" if corroborated
         else "Corroboration 0/10 - no dataset corroboration on every "
              "definition used"),
    ]
    score = 40 + (25 if human else 10) + (25 if fresh else 0) + (10 if corroborated else 0)
    level = "stale" if not fresh else ("high" if human else "medium")
    return {"level": level, "score": score, "label": f"Layer: {score}%",
            "breakdown": breakdown,
            "reason": "Calculated from the layer's own signals - hover items "
                      "show how each point was earned."}


class AmbiguousTerm(LookupError):
    """A term matched more than one concept - clarify, don't guess."""

    def __init__(self, term: str, matches: list[Concept]):
        self.matches = matches
        super().__init__(
            f"{term!r} is ambiguous in the bundle: {[c.concept_id for c in matches]}")


class AttestationFailed(RuntimeError):
    """The receipt did not verify - the figure must not be served."""


class SemanticLayer:
    """Facade over one bundle + one DuckDB snapshot."""

    def __init__(self, bundle_dir: str | Path = "bundle",
                 db_path: str | Path = "data/averio.duckdb"):
        self.bundle = Bundle(bundle_dir)
        self.db_path = str(db_path)
        self._attester = self._load_attester()
        # The snapshot's own freshness stamp is the session as-of date.
        # A resolve-only session (no database generated yet) still works;
        # staleness checks then degrade to "unknown" rather than lying.
        self.refresh_date = self._read_refresh_date()
        self.as_of: date | None = self.refresh_date.date() if self.refresh_date else None

    # --- wiring -------------------------------------------------------------

    def _load_attester(self):
        """Import the attester from its path inside the bundle. It is part
        of the layer's shipped trust infrastructure - using any other
        verifier would break the 'the bundle carries its own checks'
        property the experiment measures."""
        path = Path(self.bundle.root) / "references" / "attesters" / "sql_equality.py"
        spec = importlib.util.spec_from_file_location("sql_equality", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def _read_refresh_date(self):
        if not Path(self.db_path).exists():
            return None
        con = duckdb.connect(self.db_path, read_only=True)
        try:
            return con.execute('SELECT MAX("REFRESH_DATE") FROM bookings').fetchone()[0]
        finally:
            con.close()

    # --- resolution ---------------------------------------------------------

    def resolve(self, term: str) -> dict | None:
        """Resolve a user term to its governed concept, or None.

        None is a *meaningful* answer: the layer does not govern this term,
        and the correct downstream behavior is to clarify or abstain -
        never to improvise from the raw schema (trap A1).
        """
        matches = self.bundle.resolve(term)
        if len(matches) > 1:
            # Physical artifacts legitimately share names with the business
            # concepts they implement (the 'bookings' TABLE vs the
            # 'bookings' metric alias). Business vocabulary outranks
            # physical naming: if exactly one business-facing concept
            # matches, it wins; a tie among business concepts is a real
            # ambiguity and still raises.
            business = [c for c in matches if c.type in ("Metric", "Entity", "Policy")]
            if len(business) == 1:
                matches = business
        if not matches:
            return None
        if len(matches) > 1:
            raise AmbiguousTerm(term, matches)
        return self._describe(matches[0])

    def _describe(self, concept: Concept) -> dict:
        """The resolution record: everything provenance needs, nothing an
        agent could mistake for data."""
        computation = self.bundle.linked(concept, "Computation")
        return {
            "concept_id": concept.concept_id,
            "type": concept.type,
            "title": concept.title,
            "description": concept.description,
            "status": concept.status,
            "confidence": concept.confidence,
            "trust_tier": concept.trust_tier,
            "verified_by": concept.verified_by,
            "stale": concept.is_stale(self.as_of),
            "stale_after": concept.stale_after.isoformat() if concept.stale_after else None,
            "aliases": concept.aliases,
            "links": concept.links,
            "computation": computation.concept_id if computation else None,
            # The body carries the load-bearing caveats ("What this is
            # not", controls, servability limits). Run 1 of the experiment
            # showed that serving only the metadata invites exactly the
            # misreads the bundle exists to prevent (a trade-only figure
            # labeled "consolidated", positives offered as "new business"),
            # so the resolver serves the knowledge itself, not a pointer.
            "guidance": concept.body.strip(),
        }

    def ambiguity_rule(self, term: str) -> dict | None:
        """Default / clarify / abstain guidance for an ambiguous user term,
        read from the ambiguity policy's table - the spec's own structured
        control plane, not prose reinterpreted."""
        policy = self.bundle.get("policies/ambiguity-and-abstention")
        wanted = normalize_term(term)
        for table in parse_tables(policy.body):
            for row in table:
                cell = row.get("Term", "")
                if wanted and wanted in normalize_term(cell):
                    return {"term": cell,
                            "default": row.get("Default", ""),
                            "clarify_when": row.get("Clarify when", ""),
                            "abstain_when": row.get("Abstain when", "")}
        return None

    def security_rules(self) -> dict:
        """The output restrictions, as data: which columns are blocked
        outright and which are aggregate-only - read from the bookings
        table concept's column inventory so policy and schema cannot
        drift apart silently."""
        table = self.bundle.get("tables/bookings")
        blocked, aggregate_only = [], []
        for md_table in parse_tables(table.body):
            for row in md_table:
                column = row.get("Column", "").strip("`")
                cls = row.get("Security class", "")
                if "Restricted" in cls:
                    blocked.append(column)
                elif "Commercially sensitive" in cls:
                    aggregate_only.append(column)
        return {
            "mandatory": ("No person or organization names in any output; "
                          "use IDs or authorized masked labels. Apply before "
                          "query generation and again before response generation."),
            "blocked_columns": blocked,
            "aggregate_only_columns": aggregate_only,
            "policy": "policies/security-and-disclosure",
        }

    # --- governed computation -----------------------------------------------

    def compute(self, metric: str, *, fiscal_year, fiscal_period=None,
                ytd: bool = False, currency: str | None = None,
                trade_scope: str | None = None) -> dict:
        """Execute a governed metric through the full attested path.

        ``metric`` may be a concept id ('metrics/net-bookings-usd'), a
        computation id, or a resolvable term ('bookings'). The semantic
        parameters given here are BOTH the executor's input and the claim
        the attester independently re-derives the binding from - the same
        ask flows down both sides and must meet in the middle.
        """
        concept = self.bundle.get(metric)
        if concept is None:
            record = self.resolve(metric)  # raises AmbiguousTerm if unclear
            if record is None:
                raise LookupError(
                    f"{metric!r} is not governed by this layer - clarify or abstain")
            concept = self.bundle.get(record["concept_id"])
        if concept.status == "deprecated":
            # No current concept is deprecated, but the rule predates its
            # first use: deprecated definitions are never served unlabeled.
            raise LookupError(f"{concept.concept_id} is deprecated and not servable")
        computation = (concept if concept.type == "Computation"
                       else self.bundle.linked(concept, "Computation"))
        if computation is None:
            raise LookupError(f"{concept.concept_id} has no sanctioned computation")

        receipt = execute(computation, self.db_path, fiscal_year=fiscal_year,
                          fiscal_period=fiscal_period, ytd=ytd,
                          currency=currency, trade_scope=trade_scope)

        # The claim mirrors the caller's semantic ask, nothing more - the
        # attester must reconstruct the binding from it alone.
        claim = {"fiscal_year": int(fiscal_year)}
        if fiscal_period is not None:
            claim["fiscal_period"] = int(fiscal_period)
        if ytd:
            claim["ytd"] = True
        if currency is not None:
            claim["currency"] = currency
        if trade_scope is not None:
            claim["trade_scope"] = trade_scope
        verdict = self._attester.attest(receipt, computation.sql, claim)
        if not verdict["ok"]:
            raise AttestationFailed(f"receipt failed attestation: {verdict['reasons']}")

        stale = computation.is_stale(self.as_of) or (
            concept is not computation and concept.is_stale(self.as_of))
        window = (f"FY{int(fiscal_year)}"
                  + (f"-PD{int(fiscal_period):02d}" if fiscal_period else "")
                  + ("-YTD" if ytd else ""))
        return {
            "value": receipt["result"],
            "attested": True,
            "stale": stale,
            "stale_reason": (
                f"computation stale_after {computation.stale_after} predates "
                f"snapshot {self.as_of} - flag before serving" if stale else None),
            "receipt": receipt,
            "attestation": verdict,
            # Provenance per handoff section 15: definition, basis, window,
            # scope, confidence, and standing limitations - everything an
            # answer must be able to state about itself.
            "provenance": {
                "metric": concept.concept_id,
                "definition": concept.description,
                "computation": computation.concept_id,
                "confidence": concept.confidence,
                "trust_tier": concept.trust_tier,
                "date_basis": "Averio Booking Date via FY/PD",
                "window": window,
                "currency_basis": currency or "USD (fixed rate)",
                "trade_scope": receipt["bound_params"].get("trade_scope", "n/a"),
                "grain": "signed booking movement",
                "snapshot_refresh": str(self.refresh_date),
                "policies": [t for t in concept.links if t.startswith("/policies/")],
                # The metric's own caveats ride along at serving time, so
                # the moment a figure exists is also the moment its limits
                # are in front of the agent (trap B3's mandatory caveat,
                # T1's "no consolidated view", coverage notes).
                "guidance": concept.body.strip(),
            },
        }
