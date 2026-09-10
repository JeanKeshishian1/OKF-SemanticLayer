"""Offline tests for the jury-demo server and its streaming hook.

The live /api/ask path is exercised manually (it spends real API budget);
what is pinned here is everything that can break silently before a
presentation: the page serves, the recorded-results and curated endpoints
return coherent data, and the AgentRunner event hook streams exactly the
transcript it returns - because the live demo's honesty depends on the
stream being the transcript, not a reenactment of it.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from averio.agents.common import AgentRunner, Tool
from averio.demo import app

REPO = Path(__file__).resolve().parents[1]
client = TestClient(app)


def test_page_and_recorded_results_serve():
    page = client.get("/")
    assert page.status_code == 200
    assert "Averio Governed Semantic Layer" in page.text
    results = client.get("/api/results").json()
    assert {"baseline", "governed"} <= set(results["scorecard"])
    assert results["results"], "results.json has no recorded runs"


def test_curated_questions_come_from_the_eval_set():
    """Curated stage questions must be real eval questions - the live demo
    shows the same traps the recorded experiment measured."""
    eval_ids = {q["id"] for q in json.loads(
        (REPO / "eval" / "questions.json").read_text(encoding="utf-8"))["questions"]}
    curated = client.get("/api/curated").json()
    assert len(curated) >= 4
    for entry in curated:
        assert entry["id"] in eval_ids
        assert entry["question"] and entry["watch_for"]


def test_config_reports_readiness():
    cfg = client.get("/api/config").json()
    assert {"model", "live_ready", "results_ready"} <= set(cfg)
    assert cfg["results_ready"] is True


def test_on_event_streams_the_exact_transcript():
    """The demo streams transcript entries as they happen; the hook must
    emit precisely what the returned transcript contains, in order."""
    echo = Tool(name="echo", description="echo",
                parameters={"type": "object",
                            "properties": {"text": {"type": "string"}},
                            "required": ["text"]},
                fn=lambda text: {"echoed": text})

    def _tc(name, args):
        return SimpleNamespace(id="c1",
                               function=SimpleNamespace(name=name, arguments=args))

    script = [SimpleNamespace(content=None, tool_calls=[_tc("echo", '{"text": "x"}')]),
              SimpleNamespace(content="done", tool_calls=None)]
    fake = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
        create=lambda **kw: SimpleNamespace(
            choices=[SimpleNamespace(message=script.pop(0))]))))
    seen: list[dict] = []
    runner = AgentRunner(name="t", system_prompt="s", tools=[echo],
                         client=fake, model="fake")
    outcome = runner.ask("q", on_event=seen.append)
    assert seen == outcome["transcript"]
    assert [e["type"] for e in seen] == ["tool_call", "answer"]
