"""Load the OKF bundle into resolvable concept objects.

This module is the *reading* half of the semantic layer: it walks
``bundle/``, parses each concept's YAML frontmatter and markdown body, and
exposes them as `Concept` records a resolver can match user terms against.
It deliberately contains **no intelligence** - no fuzzy matching, no
synonym expansion, no LLM calls. Term resolution is exact (normalized)
matching against titles, declared ``aliases``, and concept-id tails,
because anything cleverer would smuggle knowledge into the layer that the
eval could not attribute to the bundle's *content*. If a term should
resolve, the bundle must say so with an alias.

Also parsed here:

  * the single ```sql fence of computation concepts (what the executor
    runs and the attester compares against),
  * bundle-absolute links (how a metric finds its computation),
  * markdown tables (the handoff treats spec tables as the "primary
    structured control plane" - the ambiguity and security rules are
    tables, and the facade reads them as data, not prose),
  * trust tier, derived from ``verified`` frontmatter exactly as
    ``bundle/index.md`` documents: no verifier = unverified; only
    ``process:*`` actors = machine-confirmed; any ``human:*`` actor =
    human-reviewed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml

# Reserved filenames are structural (directory description, change log),
# not resolvable concepts - same convention the conformance tests enforce.
_RESERVED = ("index.md", "log.md")

_FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n?", re.DOTALL)
_SQL_FENCE = re.compile(r"```sql\n(.*?)```", re.DOTALL)
# Bundle-absolute markdown links only: relative links are a conformance
# violation, so the loader does not even try to interpret them.
_LINK = re.compile(r"\[[^\]]*\]\((/[^)\s#]+\.(?:md|py))\)")


def normalize_term(term: str) -> str:
    """One canonical spelling for matching: lowercase, single spaces.
    Dashes count as spaces so a concept-id tail ('net-bookings-usd') and
    its natural-language form ('net bookings usd') meet in the middle."""
    return " ".join(term.lower().replace("-", " ").split())


def _as_date(value) -> date | None:
    """Frontmatter dates arrive as datetime.date or string depending on
    how YAML felt that day; normalize so staleness math is reliable."""
    if value is None or isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _trust_tier(verified) -> tuple[str, list[str]]:
    """Map ``verified`` frontmatter to the tier the resolver reports.

    The tier is part of every answer's provenance (the handoff's
    confidence model rides on it), so the mapping lives in exactly one
    place - here - and the bundle's index.md documents the same table.
    """
    if not verified:
        return "unverified", []
    entries = verified if isinstance(verified, list) else [verified]
    actors = [str(e.get("by", "")) for e in entries]
    tier = ("human-reviewed" if any(a.startswith("human:") for a in actors)
            else "machine-confirmed")
    return tier, actors


def parse_tables(body: str) -> list[list[dict]]:
    """Parse GitHub-style markdown tables into lists of row dicts.

    The governance spec ships its executable rules *as tables* (ambiguity
    defaults, security classes, column governance), so the facade needs
    them as data. Each contiguous block of ``|``-prefixed lines becomes one
    table; the first row is the header, the ``---`` separator row is
    skipped, and each remaining row maps header -> cell text.
    """
    tables: list[list[dict]] = []
    block: list[list[str]] = []
    for line in body.splitlines() + [""]:  # sentinel flushes the last block
        stripped = line.strip()
        if stripped.startswith("|"):
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            if not all(set(c) <= set("-: ") for c in cells):  # skip separator
                block.append(cells)
        elif block:
            header, *rows = block
            tables.append([dict(zip(header, r, strict=True))
                           for r in rows if len(r) == len(header)])
            block = []
    return tables


@dataclass
class Concept:
    """One resolvable bundle concept - a parsed .md file."""

    concept_id: str            # bundle path minus '.md', e.g. 'metrics/net-bookings-usd'
    type: str                  # frontmatter 'type' (Metric, Policy, ...)
    title: str
    description: str
    aliases: list[str]
    status: str                # stable / draft / deprecated ('' if unset)
    confidence: str | None     # the handoff confidence label, verbatim
    trust_tier: str            # unverified / machine-confirmed / human-reviewed
    verified_by: list[str]
    stale_after: date | None
    body: str                  # markdown body (frontmatter stripped)
    links: list[str]           # bundle-absolute link targets, e.g. '/policies/x.md'
    sql: str | None            # the single sql fence (computations only)
    parameters: list[dict]     # computation parameter declarations
    frontmatter: dict = field(repr=False, default_factory=dict)

    def is_stale(self, as_of: date | None) -> bool:
        """Staleness is relative to the session snapshot date - trap S1:
        a concept past its stale_after must be flagged, never silently
        served as current."""
        return bool(self.stale_after and as_of and self.stale_after < as_of)


class Bundle:
    """The loaded bundle: concepts by id plus an exact-match term index."""

    def __init__(self, root: str | Path = "bundle"):
        self.root = Path(root)
        if not (self.root / "index.md").exists():
            raise FileNotFoundError(f"no bundle at {self.root}")
        self.concepts: dict[str, Concept] = {}
        # term -> [concept_id, ...]; lists because two concepts MAY declare
        # the same alias - that is an authoring bug the resolver surfaces
        # as ambiguity rather than silently picking a winner.
        self._term_index: dict[str, list[str]] = {}
        for path in sorted(self.root.rglob("*.md")):
            if path.name in _RESERVED:
                continue
            self._load_concept(path)

    def _load_concept(self, path: Path) -> None:
        text = path.read_text(encoding="utf-8")
        match = _FRONTMATTER.match(text)
        if not match:  # conformance tests reject this; fail the same way
            raise ValueError(f"{path} lacks YAML frontmatter")
        fm = yaml.safe_load(match.group(1)) or {}
        body = text[match.end():]
        fences = _SQL_FENCE.findall(body)
        if fm.get("type") == "Computation" and len(fences) != 1:
            raise ValueError(f"{path}: computation needs exactly 1 sql fence")
        tier, actors = _trust_tier(fm.get("verified"))
        concept_id = path.relative_to(self.root).with_suffix("").as_posix()
        concept = Concept(
            concept_id=concept_id,
            type=str(fm.get("type", "")),
            title=str(fm.get("title", "")),
            description=str(fm.get("description", "")),
            aliases=[str(a) for a in fm.get("aliases", [])],
            status=str(fm.get("status", "")),
            confidence=fm.get("confidence"),
            trust_tier=tier,
            verified_by=actors,
            stale_after=_as_date(fm.get("stale_after")),
            body=body,
            links=_LINK.findall(body),
            sql=fences[0] if fences else None,
            parameters=list(fm.get("parameters", [])),
            frontmatter=fm,
        )
        self.concepts[concept_id] = concept
        # Index title, every alias, and the id tail. Exact-normalized
        # matching only - see the module docstring for why.
        terms = {concept.title, concept_id.rsplit("/", 1)[-1], *concept.aliases}
        for term in terms:
            if term:
                self._term_index.setdefault(normalize_term(term), []).append(concept_id)

    def get(self, concept_id: str) -> Concept | None:
        return self.concepts.get(concept_id)

    def resolve(self, term: str) -> list[Concept]:
        """All concepts matching a user term - [] means the layer does not
        govern this term (the abstention signal for trap A1); more than
        one means the term is genuinely ambiguous in the bundle."""
        ids = self._term_index.get(normalize_term(term), [])
        return [self.concepts[i] for i in ids]

    def by_type(self, type_name: str) -> list[Concept]:
        return [c for c in self.concepts.values() if c.type == type_name]

    def linked(self, concept: Concept, type_name: str) -> Concept | None:
        """First linked concept of a given type - how a Metric finds its
        Computation without a bespoke frontmatter field: links ARE the
        relationship model in OKF."""
        for target in concept.links:
            other = self.get(target.lstrip("/").removesuffix(".md"))
            if other and other.type == type_name:
                return other
        return None
