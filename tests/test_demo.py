"""Offline tests for the demo / end-user server and its streaming hook.

The live paths are exercised manually against the real model (they spend
API budget); what is pinned here is everything that can break silently
before a presentation or a deployment: the page serves, the variant flag
gates the routes and the page regions, the access code turns away every
credit-spending request BEFORE an agent is built, the /api/ask wire
contract holds, the recorded-results and curated endpoints return coherent
data, and the AgentRunner event hook streams exactly the transcript it
returns - because the live demo's honesty depends on the stream being the
transcript, not a reenactment of it.

The model is replaced by ``FakeChat`` - a scripted, thread-safe stand-in
behind echo-tool runners - so no DuckDB file and no key are needed.
"""

from __future__ import annotations

import copy
import json
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import averio.demo as demo
from averio.agents.common import AgentRunner, Tool
from averio.semantic_layer import layer_confidence

REPO = Path(__file__).resolve().parents[1]
client = TestClient(demo.app)


@pytest.fixture(autouse=True)
def _default_face(monkeypatch):
    """Every test starts on the default face with no access code, whatever
    the shell says: the server reads both variables per request, which is
    what lets one import-time TestClient exercise both variants."""
    monkeypatch.delenv("AVERIO_VARIANT", raising=False)
    monkeypatch.delenv("AVERIO_ACCESS_CODE", raising=False)


# --- Fakes ----------------------------------------------------------------------

ECHO = Tool(name="echo", description="echo",
            parameters={"type": "object",
                        "properties": {"text": {"type": "string"}},
                        "required": ["text"]},
            fn=lambda text: {"echoed": text})


def _tc(name, args):
    return SimpleNamespace(id="c1", function=SimpleNamespace(name=name, arguments=args))


def _script(answer="The answer\n\nConfidence: 80%"):
    """One tool call, then a final reply - the smallest honest transcript."""
    return [SimpleNamespace(content=None, tool_calls=[_tc("echo", '{"text": "x"}')]),
            SimpleNamespace(content=answer, tool_calls=None)]


class FakeChat:
    """Scripted stand-in for the OpenAI client, safe to call from the
    threads the server starts per agent. Tool-bearing requests play the
    agent script; tool-free ones (a title request) return ``title``.
    Requests are deep-copied because the runner keeps appending to the
    live message list after each call."""

    def __init__(self, script=None, title="Scripted title"):
        self.script = list(_script() if script is None else script)
        self.title = title
        self.requests: list[dict] = []
        self._lock = threading.Lock()
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        with self._lock:
            self.requests.append(copy.deepcopy(kwargs))
            if "tools" in kwargs:
                message = self.script.pop(0)
            else:
                message = SimpleNamespace(content=self.title, tool_calls=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def fake_agents(monkeypatch) -> dict[str, FakeChat]:
    """Swap the real factories - which open the gitignored DuckDB and need
    a key - for echo runners over scripted clients. Returns each agent's
    fake so a test can inspect exactly what the server sent it."""
    fakes: dict[str, FakeChat] = {}

    def factory(name):
        def build(*_args, **_kwargs):
            fakes[name] = FakeChat()
            return AgentRunner(name=name, system_prompt="s", tools=[ECHO],
                               client=fakes[name], model="fake")
        return build

    monkeypatch.setattr(demo, "make_client", lambda: SimpleNamespace())
    monkeypatch.setattr(demo, "build_baseline", factory("baseline"))
    monkeypatch.setattr(demo, "build_governed", factory("governed"))
    return fakes


def forbid_agents(monkeypatch) -> None:
    """Make any agent construction a loud failure - for asserting that a
    gate turned the request away BEFORE anything could spend credits."""
    def boom(*_args, **_kwargs):
        raise AssertionError("an agent was built past a gate")
    monkeypatch.setattr(demo, "make_client", boom)
    monkeypatch.setattr(demo, "build_baseline", boom)
    monkeypatch.setattr(demo, "build_governed", boom)


def read_events(response) -> list[dict]:
    """Drain an SSE response to its end and return its JSON events. Always
    consumed fully, so the server's worker threads are never left blocked
    behind a half-read stream."""
    events = []
    for line in response.iter_lines():
        if line.startswith("data: "):
            events.append(json.loads(line[len("data: "):]))
    return events


# --- Variant flag -----------------------------------------------------------------

def test_render_page_keeps_only_the_active_variants_regions():
    html = ("<head><!-- variant:demo --><title>D</title><!-- /variant -->"
            "<!--variant:enduser--><title>E</title><!--/variant--></head>"
            "<body>shared<!-- variant:demo -->\n<script>demo()</script>\n<!-- /variant -->"
            '<!-- variant:enduser -->\n<div id="chat"></div>\n<!-- /variant --></body>')
    demo_page = demo.render_page(html, "demo")
    enduser_page = demo.render_page(html, "enduser")
    for page in (demo_page, enduser_page):
        assert "shared" in page and "<!--" not in page  # markers never ship
    assert "<title>D</title>" in demo_page and "demo()" in demo_page
    assert "<title>E</title>" not in demo_page and "chat" not in demo_page
    assert "<title>E</title>" in enduser_page and 'id="chat"' in enduser_page
    assert "<title>D</title>" not in enduser_page and "demo()" not in enduser_page
    # A missing closer or a nested region can only yield a mangled page -
    # both must fail loudly instead of being served, on either face.
    with pytest.raises(RuntimeError):
        demo.render_page("<!-- variant:demo -->x", "demo")
    nested = ("<!-- variant:demo -->a<!-- variant:enduser -->b"
              "<!-- /variant -->c<!-- /variant -->")
    for face in ("demo", "enduser"):
        with pytest.raises(RuntimeError):
            demo.render_page(nested, face)


def test_variant_defaults_to_demo_and_ignores_unknown_values(monkeypatch):
    assert demo.variant() == "demo"
    monkeypatch.setenv("AVERIO_VARIANT", " EndUser ")
    assert demo.variant() == "enduser"
    monkeypatch.setenv("AVERIO_VARIANT", "end-user")
    assert demo.variant() == "demo"


def test_routes_are_gated_by_variant(monkeypatch):
    forbid_agents(monkeypatch)
    assert client.get("/api/results").status_code == 200
    assert client.get("/api/config").json()["variant"] == "demo"

    # The end-user face: no recorded story, no duel - those routes do not
    # exist here, and the gate fires before any agent could be built.
    monkeypatch.setenv("AVERIO_VARIANT", "enduser")
    assert client.get("/").status_code == 200
    assert client.get("/api/results").status_code == 404
    assert client.get("/api/ask", params={"q": "x"}).status_code == 404
    assert client.get("/api/curated").status_code == 200
    assert client.get("/api/config").json()["variant"] == "enduser"

    # A typo is not a third face: per request it behaves as the demo
    # (and main() refuses to start on it - see below).
    monkeypatch.setenv("AVERIO_VARIANT", "bogus")
    assert client.get("/api/results").status_code == 200


def test_config_reports_variant_and_access(monkeypatch):
    cfg = client.get("/api/config").json()
    assert {"model", "variant", "live_ready", "results_ready",
            "access_required", "max_question_chars"} <= set(cfg)
    assert cfg["access_required"] is False
    assert cfg["max_question_chars"] == demo.MAX_QUESTION_CHARS
    monkeypatch.setenv("AVERIO_ACCESS_CODE", "sesame")
    assert client.get("/api/config").json()["access_required"] is True


def test_access_code_guards_the_live_endpoint(monkeypatch):
    monkeypatch.setenv("AVERIO_ACCESS_CODE", "sesame")
    forbid_agents(monkeypatch)
    assert client.get("/api/ask", params={"q": "x"}).status_code == 401
    assert client.get("/api/ask", params={"q": "x"},
                      headers={"X-Averio-Access": "wrong"}).status_code == 401
    # Nothing that spends no credits is gated.
    assert client.get("/").status_code == 200
    assert client.get("/api/curated").status_code == 200
    assert client.get("/api/results").status_code == 200
    # The right code lets the stream through, and it runs to completion.
    fake_agents(monkeypatch)
    with client.stream("GET", "/api/ask", params={"q": "x"},
                       headers={"X-Averio-Access": "sesame"}) as resp:
        assert resp.status_code == 200
        events = read_events(resp)
    assert events[-1] == {"type": "done"}
    assert sum(e["type"] == "final" for e in events) == 2


def test_ask_stream_keeps_its_wire_contract(monkeypatch):
    """The demo page is written against these exact event shapes; pin them
    so later server work (the end-user chat will share the streaming
    machinery) cannot move them unnoticed."""
    fakes = fake_agents(monkeypatch)
    with client.stream("GET", "/api/ask", params={"q": "x" * 900}) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        events = read_events(resp)
    assert events[-1] == {"type": "done"}
    calls = [e for e in events if e["type"] == "tool_call"]
    finals = {e["agent"]: e for e in events if e["type"] == "final"}
    assert {c["agent"] for c in calls} == {"baseline", "governed"}
    assert all(c["tool"] == "echo" and
               set(c) == {"agent", "type", "step", "tool", "arguments"} for c in calls)
    assert set(finals) == {"baseline", "governed"}
    for final in finals.values():
        assert set(final) == {"agent", "type", "answer", "steps", "usage",
                              "confidence", "layer_confidence", "verdict"}
        assert final["answer"] == "The answer"  # the confidence line is stripped
        assert final["confidence"] == 80
        assert final["verdict"] is None  # free text: honestly unscored
    assert finals["baseline"]["layer_confidence"] is None
    assert finals["governed"]["layer_confidence"]["level"] == "policy"
    # Both agents received the question cut to the published cap.
    for fake in fakes.values():
        sent = fake.requests[0]["messages"][-1]
        assert sent["role"] == "user"
        assert len(sent["content"]) == demo.MAX_QUESTION_CHARS


def test_main_serves_from_the_environment(monkeypatch, capsys):
    """The deployment surface: face, host and port come from the
    environment, and a public bind with no access code is warned about."""
    captured = {}
    monkeypatch.setattr("uvicorn.run",
                        lambda app, host, port: captured.update(host=host, port=port))
    # Keep the developer's real .env out of the test process.
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: False)
    monkeypatch.setenv("AVERIO_VARIANT", "enduser")
    monkeypatch.setenv("HOST", "0.0.0.0")
    monkeypatch.setenv("PORT", "8123")
    demo.main()
    assert captured == {"host": "0.0.0.0", "port": 8123}
    out, err = capsys.readouterr()
    assert "enduser" in out and "http://0.0.0.0:8123" in out
    assert "AVERIO_ACCESS_CODE" in err
    monkeypatch.setenv("AVERIO_ACCESS_CODE", "sesame")
    demo.main()
    assert "WARNING" not in capsys.readouterr()[1]


def test_main_refuses_an_unknown_variant(monkeypatch):
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: False)
    monkeypatch.setattr("uvicorn.run", lambda *a, **k: pytest.fail("server started"))
    monkeypatch.setenv("AVERIO_VARIANT", "end-user")
    with pytest.raises(SystemExit):
        demo.main()


# --- Recorded story and hooks -------------------------------------------------

def test_page_and_recorded_results_serve():
    page = client.get("/")
    assert page.status_code == 200
    assert "Averio Governed Semantic Layer" in page.text
    results = client.get("/api/results").json()
    assert {"baseline", "governed"} <= set(results["scorecard"])
    assert results["results"], "results.json has no recorded runs"
    # Governed rows are enriched with the layer-derived confidence on the
    # fly, from stored transcripts - runs recorded before the feature
    # existed still get the chip.
    governed = [r for r in results["results"] if r["agent"] == "governed"]
    assert governed and all(
        r["layer_confidence"]["level"] in ("high", "medium", "stale", "policy")
        for r in governed)
    assert not any("layer_confidence" in r for r in results["results"]
                   if r["agent"] == "baseline")


def test_layer_confidence_rubric_is_deterministic():
    """The calculated confidence looks only at what the layer served:
    attestation (40) + verification tier (25/10) + freshness (25/0) +
    dataset corroboration (10/0) - never the answer's wording. Multiple
    figures score conservatively, and the breakdown itemizes every point
    (the chip's hover renders it verbatim)."""
    def compute_entry(tier="human-reviewed", stale=False, attested=True,
                      confidence="confirmed-internally"):
        return {"type": "tool_call", "tool": "compute",
                "result": {"attested": attested, "stale": stale,
                           "provenance": {"trust_tier": tier,
                                          "confidence": confidence}}}

    full = layer_confidence([compute_entry(
        confidence="confirmed-plus-dataset-supported")])
    assert (full["level"], full["score"]) == ("high", 100)
    assert len(full["breakdown"]) == 4

    assert layer_confidence([compute_entry()])["score"] == 90  # no corroboration
    machine = layer_confidence([compute_entry(), compute_entry(
        tier="machine-confirmed")])
    assert (machine["level"], machine["score"]) == ("medium", 75)
    stale = layer_confidence([compute_entry(stale=True)])
    assert (stale["level"], stale["score"]) == ("stale", 65)
    assert layer_confidence([compute_entry(
        tier="machine-confirmed", stale=True)])["score"] == 50

    # A refused/unattested compute is not evidence of a served figure -
    # policy-based answers carry no score at all, honestly.
    for transcript in ([compute_entry(attested=False)],
                       [{"type": "tool_call", "tool": "resolve",
                         "result": {"resolved": None}}],
                       None):
        verdict = layer_confidence(transcript)
        assert (verdict["level"], verdict["score"]) == ("policy", None)


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
    seen: list[dict] = []
    runner = AgentRunner(name="t", system_prompt="s", tools=[ECHO],
                         client=FakeChat(), model="fake")
    outcome = runner.ask("q", on_event=seen.append)
    assert seen == outcome["transcript"]
    assert [e["type"] for e in seen] == ["tool_call", "answer"]
