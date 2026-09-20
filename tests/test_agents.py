"""Offline tests for the agent machinery - no API key, no network.

The tool loop is driven with a scripted fake client (the OpenAI SDK's
response shape, faked with SimpleNamespace), and the agents' tool
implementations run against the session dataset from conftest. What is
deliberately NOT tested here is model behavior - that is the eval's job;
these tests pin the harness so that eval results measure the model and
the layer, never loop bugs.

The most load-bearing test is the baseline-prompt guard: the baseline
must stay semantics-free, because every governance concept that leaks
into its prompt deletes a trap from the experiment.
"""

from __future__ import annotations

import copy
from pathlib import Path
from types import SimpleNamespace

import pytest

from averio.agents.baseline import build_baseline
from averio.agents.common import (
    CONFIDENCE_INSTRUCTION,
    MAX_STEPS,
    ROW_CAP,
    AgentRunner,
    Tool,
    extract_confidence,
    make_run_sql,
)
from averio.agents.governed import build_governed

REPO = Path(__file__).resolve().parents[1]


# --- Scripted fake of the OpenAI-compatible client ---------------------------

def _tool_call(name: str, arguments: str, call_id: str = "call-1"):
    return SimpleNamespace(id=call_id,
                           function=SimpleNamespace(name=name, arguments=arguments))


def _assistant(content=None, tool_calls=None):
    return SimpleNamespace(content=content, tool_calls=tool_calls)


class FakeClient:
    """Plays back a script of assistant messages and records every request,
    so tests can assert what the runner actually sent upstream."""

    def __init__(self, script):
        self._script = list(script)
        self.requests: list[dict] = []
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        # Snapshot: the runner keeps appending to the same messages list
        # after the call, so recording the live object would show later
        # turns as if they had been sent with this request.
        self.requests.append(copy.deepcopy(kwargs))
        return SimpleNamespace(choices=[SimpleNamespace(message=self._script.pop(0))])


def _echo_runner(script) -> tuple[AgentRunner, FakeClient]:
    echo = Tool(name="echo", description="echo back",
                parameters={"type": "object",
                            "properties": {"text": {"type": "string"}},
                            "required": ["text"]},
                fn=lambda text: {"echoed": text})
    client = FakeClient(script)
    runner = AgentRunner(name="test", system_prompt="be terse",
                         tools=[echo], client=client, model="fake-model")
    return runner, client


# --- Tool loop ----------------------------------------------------------------

def test_runner_executes_tool_then_answers():
    runner, client = _echo_runner([
        _assistant(tool_calls=[_tool_call("echo", '{"text": "hi"}')]),
        _assistant(content="final: hi"),
    ])
    result = runner.ask("say hi")
    assert result["answer"] == "final: hi"
    assert result["steps"] == 2
    calls = [e for e in result["transcript"] if e["type"] == "tool_call"]
    assert calls == [{"step": 1, "type": "tool_call", "tool": "echo",
                      "arguments": '{"text": "hi"}', "result": {"echoed": "hi"}}]
    # The tool result must have gone back upstream as a role=tool message.
    second_request = client.requests[1]["messages"]
    tool_msgs = [m for m in second_request if m.get("role") == "tool"]
    assert tool_msgs and '"echoed": "hi"' in tool_msgs[0]["content"]


def test_history_none_leaves_the_request_unchanged():
    """The eval path: no history means exactly [system, question] - the
    shape every recorded result was produced from."""
    runner, client = _echo_runner([_assistant(content="ok")])
    runner.ask("q")
    assert [m["role"] for m in client.requests[0]["messages"]] == ["system", "user"]
    assert client.requests[0]["messages"][1] == {"role": "user", "content": "q"}


def test_history_turns_sit_between_system_and_question():
    """Multi-turn chat: earlier text turns are replayed verbatim between the
    system prompt and the new question, and nothing else changes - the
    result dict keeps its keys and the transcript covers only this turn."""
    runner, client = _echo_runner([_assistant(content="FY2025 too")])
    result = runner.ask("and for FY2025?", history=[
        {"role": "user", "content": "net bookings FY2026?"},
        {"role": "assistant", "content": "It was X."}])
    sent = client.requests[0]["messages"]
    assert sent == [
        {"role": "system", "content": runner.system_prompt},
        {"role": "user", "content": "net bookings FY2026?"},
        {"role": "assistant", "content": "It was X."},
        {"role": "user", "content": "and for FY2025?"}]
    assert result["question"] == "and for FY2025?"
    assert [e["type"] for e in result["transcript"]] == ["answer"]


def test_history_rejects_foreign_roles_before_any_request():
    """A stray tool/system turn in history is a caller bug; refusing loudly
    beats silently replaying a corrupted conversation."""
    runner, client = _echo_runner([_assistant(content="never")])
    with pytest.raises(ValueError, match="user/assistant"):
        runner.ask("q", history=[{"role": "tool", "content": "{}"}])
    assert client.requests == []


def test_runner_survives_unknown_tool_and_bad_arguments():
    """Failures become data the model can react to - never harness crashes."""
    runner, _ = _echo_runner([
        _assistant(tool_calls=[_tool_call("nope", "{}", "c1"),
                               _tool_call("echo", "{not json", "c2")]),
        _assistant(content="recovered"),
    ])
    result = runner.ask("q")
    assert result["answer"] == "recovered"
    results = [e["result"] for e in result["transcript"] if e["type"] == "tool_call"]
    assert "unknown tool" in results[0]["error"]
    assert "malformed" in results[1]["error"]


def test_runner_reports_exhausted_budget_honestly():
    looping = [_assistant(tool_calls=[_tool_call("echo", '{"text": "again"}')])
               ] * MAX_STEPS
    runner, _ = _echo_runner(looping)
    result = runner.ask("q")
    assert result["answer"] == "[no final answer within the step budget]"
    assert result["transcript"][-1]["type"] == "budget_exhausted"


def test_runner_accumulates_usage_and_cost():
    """Spend accounting: token counts and OpenRouter's per-request cost
    fold into the result, so the eval attributes real USD per question and
    the demo shows it live. Responses without usage (the other fakes here)
    must simply accumulate nothing rather than crash."""
    responses = [
        SimpleNamespace(
            choices=[SimpleNamespace(message=_assistant(
                tool_calls=[_tool_call("echo", '{"text": "hi"}')]))],
            usage=SimpleNamespace(prompt_tokens=100, completion_tokens=20,
                                  cost=0.0012)),
        SimpleNamespace(
            choices=[SimpleNamespace(message=_assistant(content="done"))],
            usage=SimpleNamespace(prompt_tokens=150, completion_tokens=30,
                                  cost=0.0018)),
    ]
    echo = Tool(name="echo", description="echo",
                parameters={"type": "object",
                            "properties": {"text": {"type": "string"}},
                            "required": ["text"]},
                fn=lambda text: {"echoed": text})
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
        create=lambda **kw: responses.pop(0))))
    runner = AgentRunner(name="t", system_prompt="s", tools=[echo],
                         client=client, model="fake")
    result = runner.ask("q")
    assert result["usage"] == {"requests": 2, "prompt_tokens": 250,
                               "completion_tokens": 50,
                               "cost_usd": pytest.approx(0.003)}


# --- Self-reported confidence -------------------------------------------------

def test_confidence_is_extracted_and_stripped_from_the_answer():
    """The runner pulls the trailing 'Confidence: NN%' line into its own
    field and removes it from the answer - the deterministic scorer must
    never see the stray percentage (it would trip the abstention checks).
    The verbatim final message stays in the transcript."""
    runner, _ = _echo_runner([
        _assistant(content="Net bookings were $135.3M.\n\n**Confidence: 85%**"),
    ])
    result = runner.ask("q")
    assert result["confidence"] == 85
    assert result["answer"] == "Net bookings were $135.3M."
    assert "Confidence" in result["transcript"][-1]["content"]


def test_confidence_absent_is_none_not_zero():
    runner, _ = _echo_runner([_assistant(content="No idea, sorry.")])
    result = runner.ask("q")
    assert result["confidence"] is None


def test_extract_confidence_never_mangles_mid_answer_mentions():
    """A confidence line quoted mid-answer yields the value but leaves the
    text intact; values clamp to 0-100."""
    text = "Confidence: 90%\nBut the real answer is below.\nDone."
    stripped, value = extract_confidence(text)
    assert stripped == text and value == 90
    assert extract_confidence("x\nConfidence: 250%")[1] == 100


def test_confidence_instruction_is_identical_in_both_prompts(workspace):
    """Symmetry guard: the instruction is appended by the runner itself,
    so neither agent can carry a different version of it."""
    db, _ = workspace
    baseline = build_baseline(str(db))
    governed = build_governed(str(db), bundle_dir=REPO / "bundle")
    for agent in (baseline, governed):
        assert agent.system_prompt.endswith(CONFIDENCE_INSTRUCTION)


# --- run_sql: the shared data-access tool -------------------------------------

def test_run_sql_caps_rows_and_reports_errors(workspace):
    db, _ = workspace
    run_sql = make_run_sql(str(db)).fn
    flooded = run_sql('SELECT * FROM bookings')
    assert flooded["truncated"] and len(flooded["rows"]) == ROW_CAP
    # Read-only connection: mutation attempts come back as error data.
    assert "error" in run_sql("CREATE TABLE x AS SELECT 1")
    assert "error" in run_sql("SELECT nonsense FROM nowhere")


# --- Prompt discipline --------------------------------------------------------

def test_baseline_prompt_stays_ungoverned(workspace):
    """THE guard: any governance vocabulary reaching the baseline prompt
    hands it the knowledge whose absence the experiment measures."""
    db, _ = workspace
    agent = build_baseline(str(db))
    prompt = agent.system_prompt.lower()
    for forbidden in ("sanction", "attest", "governed", "semantic layer",
                      "stale", "abstain", "sold-to", "signed movement",
                      "pd1", "fiscal year ends", "interco means"):
        assert forbidden not in prompt, f"governance leak in baseline prompt: {forbidden!r}"
    # But identical raw data access: full schema present, plus parity filler.
    assert '"USD Fixed Amount" DOUBLE' in agent.system_prompt
    assert "Column profile" in agent.system_prompt
    assert [t.name for t in agent.tools] == ["run_sql"]


def test_agents_share_schema_and_differ_only_in_layer(workspace):
    db, _ = workspace
    baseline = build_baseline(str(db))
    governed = build_governed(str(db), bundle_dir=REPO / "bundle")
    # Identical raw schema block in both prompts.
    from averio.agents.common import schema_block
    schema = schema_block(str(db))
    assert schema in baseline.system_prompt and schema in governed.system_prompt
    # Toolsets: governed = baseline + exactly the four layer tools.
    assert [t.name for t in governed.tools] == [
        "run_sql", "resolve", "ambiguity_rule", "security_rules", "compute"]
    # Discoverability: the governed prompt carries the bundle-derived
    # metric catalog (run 1 failed a tax-inclusive EUR question because the
    # agent never guessed a resolvable term); the baseline must never see
    # governed vocabulary.
    assert "metrics/transaction-booking-amount-with-tax" in governed.system_prompt
    assert "metrics/" not in baseline.system_prompt
    # Rough context parity: neither prompt more than ~2x the other.
    ratio = len(governed.system_prompt) / len(baseline.system_prompt)
    assert 0.5 < ratio < 2.0, f"context volumes diverged: ratio {ratio:.2f}"


# --- Governed tools end to end (no model involved) ----------------------------

def test_governed_tools_reach_the_layer(workspace):
    db, truth = workspace
    governed = build_governed(str(db), bundle_dir=REPO / "bundle")
    tools = {t.name: t.fn for t in governed.tools}

    resolved = tools["resolve"](term="bookings")
    assert resolved["concept_id"] == "metrics/net-bookings-usd"
    assert tools["resolve"](term="gross margin")["resolved"] is None

    answer = tools["compute"](metric="metrics/net-bookings-usd", fiscal_year=2025)
    assert answer["attested"]
    assert answer["value"] == pytest.approx(
        truth["periods"]["FY2025"]["net_bookings_usd"])
    # Refusals surface as error data - the policy speaking to the model.
    refused = tools["compute"](metric="metrics/transaction-booking-amount",
                               fiscal_year=2025)
    assert "currency" in refused["error"]

    security = tools["security_rules"]()
    assert "Customer Name" in security["blocked_columns"]
