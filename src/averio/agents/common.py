
"""Shared agent machinery - everything BOTH agents get, and nothing else.

This module is where the experiment's control variables live: the client
and model (one model for both agents), the tool-loop runner (identical
loop, temperature, budgets), the read-only ``run_sql`` tool (identical
data access), and the schema/profile introspection both prompts draw on.
If a capability lands here, both agents have it; the semantic layer's
tools deliberately live in ``governed.py`` instead, because their absence
from the baseline IS the experiment.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import duckdb

# One model serves both agents - vendor/slug comes from the environment so
# the harness never hardcodes a deployment. OpenRouter is an aggregator
# with an OpenAI-compatible API, hence the openai client pointed at it.
DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "qwen/qwen3.8-27b"

# Both agents answer deterministically-as-possible: the eval compares two
# agents, and sampling noise would blur the attribution the experiment
# exists to make.
TEMPERATURE = 0.0
# Generous because reasoning models spend "thinking" tokens from the same
# budget before emitting content; 1200 proved tight enough to produce
# empty final answers on hard questions.
MAX_TOKENS = 3000
MAX_STEPS = 15  # tool-loop budget; enough for clarify->resolve->compute chains

# run_sql returns at most this many rows. Enough for any legitimate
# aggregate; small enough that a "SELECT *" cannot flood the context.
ROW_CAP = 40


def make_client():
    """The OpenAI-compatible client, pointed at OpenRouter.

    Imported lazily so that offline work (tests, prompt construction)
    never needs the SDK's network stack or a key. The key comes from the
    environment ONLY - never a parameter, never a file in the repo. A
    gitignored .env at the repo root (copy .env.example) is folded into
    the environment here; already-set variables win over .env values.
    """
    from dotenv import load_dotenv
    from openai import OpenAI

    load_dotenv()  # no-op when no .env file exists
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise RuntimeError(
            "OPENROUTER_API_KEY is not set. Set it in the environment "
            "(never in code or the repo) to run the agents.")
    return OpenAI(api_key=key,
                  base_url=os.environ.get("OPENROUTER_BASE_URL", DEFAULT_BASE_URL))


def model_name() -> str:
    return os.environ.get("OPENROUTER_MODEL", DEFAULT_MODEL)


@dataclass
class Tool:
    """One callable tool: OpenAI function-calling spec + implementation."""

    name: str
    description: str
    parameters: dict  # JSON Schema for the arguments object
    fn: Callable[..., Any]

    def spec(self) -> dict:
        return {"type": "function",
                "function": {"name": self.name,
                             "description": self.description,
                             "parameters": self.parameters}}


def make_run_sql(db_path: str) -> Tool:
    """The shared data-access tool: arbitrary read-only SQL.

    Both agents get this - identical data access is a design requirement.
    The connection is read-only (the snapshot can never be mutated) and
    errors come back as data rather than exceptions, because a wrong query
    the agent can see and correct is part of realistic analyst behavior.
    Note what is deliberately absent: no masking, no column blocklist.
    Security is a POLICY the governed agent must apply, not a physical
    impossibility - otherwise trap SEC1 would measure the harness, not
    the agent.
    """

    def run_sql(sql: str) -> dict:
        try:
            con = duckdb.connect(db_path, read_only=True)
            try:
                cursor = con.execute(sql)
                columns = [d[0] for d in cursor.description]
                rows = cursor.fetchmany(ROW_CAP + 1)  # +1 detects truncation
            finally:
                con.close()
        except Exception as exc:  # surface the engine's message verbatim
            return {"error": str(exc)}
        return {"columns": columns,
                "rows": [list(r) for r in rows[:ROW_CAP]],
                "truncated": len(rows) > ROW_CAP}

    return Tool(
        name="run_sql",
        description=("Run a read-only SQL query against the DuckDB bookings "
                     "database. Column names contain spaces - always "
                     f"double-quote them. Returns at most {ROW_CAP} rows."),
        parameters={"type": "object",
                    "properties": {"sql": {"type": "string",
                                           "description": "DuckDB SQL to execute"}},
                    "required": ["sql"]},
        fn=run_sql,
    )


def schema_block(db_path: str) -> str:
    """The raw physical schema, rendered identically for both prompts.

    Deliberately semantics-free: names and types exactly as the database
    reports them, in table order. What the columns MEAN is precisely the
    knowledge under test, so it must never leak in here.
    """
    con = duckdb.connect(db_path, read_only=True)
    try:
        described = con.execute("DESCRIBE bookings").fetchall()
    finally:
        con.close()
    lines = [f'  "{name}" {ctype}' for name, ctype, *_ in described]
    return "Table \"bookings\" (one row per record in the extract):\n" + "\n".join(lines)


def column_profiles(db_path: str) -> str:
    """Neutral per-column statistics - the baseline's context-parity filler.

    Mirrors what a raw extract profile would show (non-null and distinct
    counts, like the real workbook's Field Governance sheet) WITHOUT any
    governance labels. This exists so the baseline prompt has comparable
    volume to the governed mandate: otherwise the eval would confound
    "the layer helps" with "more tokens help". Facts here are derivable
    from the data itself, so nothing semantic is being given away.
    """
    con = duckdb.connect(db_path, read_only=True)
    try:
        described = con.execute("DESCRIBE bookings").fetchall()
        names = [row[0] for row in described]
        aggregates = ", ".join(
            f'COUNT("{n}") AS "nn_{i}", COUNT(DISTINCT "{n}") AS "d_{i}"'
            for i, n in enumerate(names))
        total, *counts = con.execute(
            f"SELECT COUNT(*), {aggregates} FROM bookings").fetchone()
    finally:
        con.close()
    lines = [f"Row count: {total}", "column | non-null | distinct"]
    for i, name in enumerate(names):
        lines.append(f'"{name}" | {counts[2 * i]} | {counts[2 * i + 1]}')
    return "Column profile of the extract:\n" + "\n".join(lines)


# Both agents must self-report how sure they are of each answer. The
# instruction is appended by the RUNNER (not the agent builders) so it is
# impossible for the two prompts to drift apart - a symmetric addition is
# presentation machinery, not governance knowledge. The runner extracts and
# STRIPS the line from the returned answer, so the deterministic scorer
# never sees a stray percentage (which would trip the abstention checks);
# the verbatim final message stays in the transcript.
CONFIDENCE_INSTRUCTION = (
    "\n\nEnd every final answer with its own last line in exactly this "
    "form:\nConfidence: NN%\nwhere NN is 0-100 and states how confident "
    "you are that the answer above is correct and complete. Required on "
    "every answer, including refusals and clarifications.")

# Accepts "Confidence: 85%", "confidence = 85", "**Confidence: 85/100**".
_CONFIDENCE_LINE = re.compile(
    r"(?im)^\s*\**\s*confidence\s*[:=]\s*(\d{1,3})\s*(?:%|/\s*100)?\s*\**\s*$")


def extract_confidence(text: str) -> tuple[str, int | None]:
    """Split a final answer into (answer-without-the-line, confidence).

    Only a TRAILING confidence line is stripped - a mid-answer mention
    (e.g. the agent quoting the instruction) still yields the value but
    never mangles the answer body. Values clamp to 0-100; absence returns
    None, which the UI shows honestly as "not stated".
    """
    matches = list(_CONFIDENCE_LINE.finditer(text))
    if not matches:
        return text, None
    last = matches[-1]
    value = max(0, min(100, int(last.group(1))))
    if not text[last.end():].strip():  # it is the trailing line - remove it
        return text[:last.start()].rstrip(), value
    return text, value


class AgentRunner:
    """The tool loop both agents run - identical by construction.

    One instance = one agent (a system prompt plus a toolset). ``ask()``
    drives the standard function-calling loop: send messages, execute any
    requested tools, feed results back, stop at the first tool-free reply
    or when the step budget runs out. Every step lands in the transcript,
    because the eval scores PROCESS (which tools were consulted, what
    leaked) as much as the final answer.
    """

    def __init__(self, *, name: str, system_prompt: str, tools: list[Tool],
                 client=None, model: str | None = None):
        self.name = name
        self.system_prompt = system_prompt + CONFIDENCE_INSTRUCTION
        self.tools = tools
        self._by_name = {t.name: t for t in tools}
        self.client = client
        self.model = model or model_name()

    def ask(self, question: str, on_event=None) -> dict:
        """Run one question to completion.

        ``on_event``, when given, receives each transcript entry the moment
        it happens - presentation instrumentation (the live demo streams
        tool calls as they fire). It is observation only: both agents get
        the identical hook, it never alters the loop, and the returned
        transcript is byte-identical with or without it.
        """
        if self.client is None:  # constructed offline (tests, prompt checks)
            raise RuntimeError(f"agent {self.name!r} has no client attached")
        messages: list[dict] = [{"role": "system", "content": self.system_prompt},
                                {"role": "user", "content": question}]
        transcript: list[dict] = []

        def record(entry: dict) -> None:
            transcript.append(entry)
            if on_event is not None:
                on_event(entry)

        # Spend accounting. OpenRouter reports token counts on every
        # response and - with usage accounting enabled via the extra_body
        # below - the request's cost in USD credits. Totals ride along in
        # the result so the eval can attribute real cost per question and
        # the demo can show it live. Observation only: it never alters the
        # loop, and fakes without a usage field simply accumulate zeros.
        usage = {"requests": 0, "prompt_tokens": 0,
                 "completion_tokens": 0, "cost_usd": 0.0}

        def account(response) -> None:
            u = getattr(response, "usage", None)
            if u is None:
                return
            usage["requests"] += 1
            usage["prompt_tokens"] += getattr(u, "prompt_tokens", 0) or 0
            usage["completion_tokens"] += getattr(u, "completion_tokens", 0) or 0
            # The SDK's usage model carries OpenRouter's `cost` as an
            # extra field; older SDKs expose extras only via model_extra.
            cost = getattr(u, "cost", None)
            if cost is None:
                cost = (getattr(u, "model_extra", None) or {}).get("cost")
            if cost:
                usage["cost_usd"] += float(cost)

        for step in range(1, MAX_STEPS + 1):
            response = self.client.chat.completions.create(
                model=self.model, messages=messages,
                tools=[t.spec() for t in self.tools],
                temperature=TEMPERATURE, max_tokens=MAX_TOKENS,
                # OpenRouter usage accounting: ask for the cost of each
                # request in the response. Ignored by test fakes.
                extra_body={"usage": {"include": True}})
            account(response)
            message = response.choices[0].message
            tool_calls = getattr(message, "tool_calls", None) or []
            # Rebuild the assistant turn as a plain dict: the SDK returns
            # pydantic objects, tests return SimpleNamespace fakes, and the
            # next request needs neither - just the wire shape.
            assistant: dict = {"role": "assistant", "content": message.content or ""}
            if tool_calls:
                assistant["tool_calls"] = [
                    {"id": tc.id, "type": "function",
                     "function": {"name": tc.function.name,
                                  "arguments": tc.function.arguments}}
                    for tc in tool_calls]
            messages.append(assistant)

            if not tool_calls:  # a tool-free reply is the final answer
                content = (message.content or "").strip()
                if not content and step < MAX_STEPS:
                    # Reasoning models occasionally burn the whole token
                    # budget thinking and emit no content. One neutral
                    # nudge (identical for both agents) recovers the
                    # answer without coaching either of them.
                    record({"step": step, "type": "empty_reply_nudge"})
                    messages.append({"role": "user", "content":
                                     "Your previous reply was empty. "
                                     "State your final answer now."})
                    continue
                record({"step": step, "type": "answer", "content": content})
                answer, confidence = extract_confidence(content)
                return {"agent": self.name, "question": question,
                        "answer": answer, "confidence": confidence,
                        "steps": step, "transcript": transcript,
                        "usage": usage}

            for tc in tool_calls:
                result = self._execute(tc.function.name, tc.function.arguments)
                record({"step": step, "type": "tool_call",
                        "tool": tc.function.name,
                        "arguments": tc.function.arguments,
                        "result": result})
                messages.append({"role": "tool", "tool_call_id": tc.id,
                                 "content": json.dumps(result, default=str)})
        # Budget exhausted without a final reply - report it honestly; the
        # eval scores this as a failure, never retries silently.
        record({"step": MAX_STEPS, "type": "budget_exhausted"})
        return {"agent": self.name, "question": question,
                "answer": "[no final answer within the step budget]",
                "confidence": None, "steps": MAX_STEPS,
                "transcript": transcript, "usage": usage}

    def _execute(self, name: str, raw_arguments: str) -> Any:
        """Run one tool call; failures become data the model can react to
        (adapt, retry, or abstain), never crashes of the harness."""
        tool = self._by_name.get(name)
        if tool is None:
            return {"error": f"unknown tool {name!r}"}
        try:
            arguments = json.loads(raw_arguments or "{}")
        except json.JSONDecodeError as exc:
            return {"error": f"malformed tool arguments: {exc}"}
        try:
            return tool.fn(**arguments)
        except TypeError as exc:  # wrong/missing argument names
            return {"error": str(exc)}
