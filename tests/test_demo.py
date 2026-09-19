"""Offline tests for the demo / end-user server and its streaming hook.

The live paths are exercised manually against the real model (they spend
API budget); what is pinned here is everything that can break silently
before a presentation or a deployment: the page serves, the variant flag
gates the routes and the page regions, the access code turns away every
credit-spending request BEFORE an agent is built, both live routes keep
their wire contract (the demo's exact event shapes, the chat's history
replay, titles and their fallback, keepalive frames), the recorded-results
and curated endpoints return coherent data, and the AgentRunner event hook
streams exactly the transcript it returns - because the live demo's
honesty depends on the stream being the transcript, not a reenactment.

The model is replaced by ``FakeChat`` - a scripted, thread-safe stand-in
behind echo-tool runners - so no DuckDB file and no key are needed.
"""

from __future__ import annotations

import copy
import json
import re
import shutil
import subprocess
import threading
import time
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
    threads the server starts per producer. Tool-bearing requests play the
    agent script; tool-free ones (the title request) return ``title``, or
    raise when it is None - the model failing to name a chat. Requests are
    deep-copied because the runner keeps appending to the live message
    list after each call."""

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
            elif self.title is None:
                raise RuntimeError("title model unavailable")
            else:
                message = SimpleNamespace(content=self.title, tool_calls=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def fake_agents(monkeypatch, tool=ECHO) -> dict[str, FakeChat]:
    """Swap the real factories - which open the gitignored DuckDB and need
    a key - for echo runners over scripted clients. Returns every fake by
    role ("client" is what make_client hands out, i.e. where the title
    request lands; "baseline"/"governed" are the agents actually built) so
    a test can inspect exactly what the server sent, and to whom."""
    fakes: dict[str, FakeChat] = {}

    def factory(name):
        def build(*_args, **_kwargs):
            fakes[name] = FakeChat()
            return AgentRunner(name=name, system_prompt="s", tools=[tool],
                               client=fakes[name], model="fake")
        return build

    def make_client():
        fakes["client"] = FakeChat()
        return fakes["client"]

    monkeypatch.setattr(demo, "make_client", make_client)
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


def read_stream(response) -> tuple[list[dict], list[str]]:
    """Drain an SSE response to its end: (JSON events, other non-empty
    lines such as keepalive comments). Always consumed fully, so the
    server's worker threads are never left blocked behind a half-read
    stream."""
    events, other = [], []
    for line in response.iter_lines():
        if line.startswith("data: "):
            events.append(json.loads(line[len("data: "):]))
        elif line.strip():
            other.append(line)
    return events, other


def read_events(response) -> list[dict]:
    return read_stream(response)[0]


def _chat(body: dict):
    return client.post("/api/chat", json=body)


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


def test_demo_page_is_the_default_and_carries_no_end_user_regions():
    page = client.get("/").text
    assert "Averio Governed Semantic Layer" in page and 'id="ask-form"' in page
    assert "OKF Explorer" in page and "Averio Assistant" not in page
    assert "<!-- variant" not in page and "<!-- /variant" not in page


def test_enduser_page_serves_only_its_regions(monkeypatch):
    """The end-user browser must never receive the demo: not hidden by CSS,
    simply absent from the bytes served."""
    monkeypatch.setenv("AVERIO_VARIANT", "enduser")
    page = client.get("/").text
    assert "Averio Assistant" in page
    for own in ('id="composer"', 'id="chat-sidebar"', 'id="sidebar-resizer"', "/api/chat"):
        assert own in page, own
    for demo_only in ('id="ask-form"', "OKF Explorer", "trapchart", "/api/results",
                      "/api/ask", "Averio Governed Semantic Layer"):
        assert demo_only not in page, demo_only
    monkeypatch.setenv("AVERIO_VARIANT", "demo")
    assert 'id="composer"' not in client.get("/").text  # and the demo has none of the chat
    assert page.count("<script") == page.count("</script>")
    assert page.count("<style") == page.count("</style>")
    assert "<!-- variant" not in page and "<!-- /variant" not in page


def test_variant_markers_sit_between_elements_and_never_nest():
    """The convention render_page relies on, checked against the real file:
    every opener has a closer, no region contains another, and no marker
    sits inside a <script> or <style> element (where the comment would be
    text, not markup, and a stripped region would leave broken code)."""
    raw = demo.PAGE.read_text(encoding="utf-8")
    openers = re.findall(r"<!--\s*variant:(\w+)\s*-->", raw)
    closers = re.findall(r"<!--\s*/variant\s*-->", raw)
    assert openers and len(openers) == len(closers)
    assert set(openers) <= set(demo.VARIANTS)
    for region in demo.VARIANT_REGION.finditer(raw):
        assert "<!-- variant" not in region.group(2)
    for marker in re.finditer(r"<!--\s*/?variant", raw):
        prefix = raw[:marker.start()]
        assert prefix.count("<script") == prefix.count("</script>")
        assert prefix.count("<style") == prefix.count("</style>")
    for face in demo.VARIANTS:
        demo.render_page(raw, face)  # must not raise


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_served_scripts_boot_on_each_face(monkeypatch, tmp_path):
    """Splitting one script into shared and per-face parts can leave a face
    with a script that no longer parses, or whose boot code touches an
    element only the other face has - either way a blank page. Boot every
    <script> each face actually serves against a stub DOM (tests/boot_check.js)."""
    def boot(name: str, html: str):
        path = tmp_path / f"{name}.html"
        path.write_text(html, encoding="utf-8")
        return subprocess.run(["node", str(REPO / "tests" / "boot_check.js"), str(path)],
                              capture_output=True, text=True)

    pages = {}
    for face in demo.VARIANTS:
        monkeypatch.setenv("AVERIO_VARIANT", face)
        pages[face] = client.get("/").text
        result = boot(face, pages[face])
        assert result.returncode == 0, f"{face}: {result.stderr or result.stdout}"
    # Negative control: the check must have teeth. A demo-only element
    # touched at boot on the end-user page is exactly the regression it
    # exists to catch.
    broken = pages["enduser"].replace(
        "</body>", "<script>$('search').addEventListener('input', () => {});</script></body>")
    result = boot("broken", broken)
    assert result.returncode != 0 and "script" in result.stderr


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
    # The chat route does not exist on the demo face: the gate answers
    # before the body is even validated (an empty body would be a 422).
    assert _chat({}).status_code == 404

    # The end-user face: no recorded story, no duel - those routes do not
    # exist here, and the gate fires before any agent could be built.
    monkeypatch.setenv("AVERIO_VARIANT", "enduser")
    assert client.get("/").status_code == 200
    assert client.get("/api/results").status_code == 404
    assert client.get("/api/ask", params={"q": "x"}).status_code == 404
    assert client.get("/api/curated").status_code == 200
    assert client.get("/api/config").json()["variant"] == "enduser"
    assert _chat({}).status_code == 422  # reachable; validation, not the gate

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


def test_access_code_guards_every_live_endpoint(monkeypatch):
    monkeypatch.setenv("AVERIO_ACCESS_CODE", "sesame")
    forbid_agents(monkeypatch)
    assert client.get("/api/ask", params={"q": "x"}).status_code == 401
    assert client.get("/api/ask", params={"q": "x"},
                      headers={"X-Averio-Access": "wrong"}).status_code == 401
    # Nothing that spends no credits is gated.
    assert client.get("/").status_code == 200
    assert client.get("/api/curated").status_code == 200
    assert client.get("/api/results").status_code == 200
    # The chat is guarded the same way on its own face.
    monkeypatch.setenv("AVERIO_VARIANT", "enduser")
    turn = {"messages": [{"role": "user", "content": "q"}]}
    assert _chat(turn).status_code == 401
    assert client.post("/api/chat", json=turn,
                       headers={"X-Averio-Access": "wrong"}).status_code == 401
    monkeypatch.delenv("AVERIO_VARIANT")
    # The right code lets the stream through, and it runs to completion.
    fake_agents(monkeypatch)
    with client.stream("GET", "/api/ask", params={"q": "x"},
                       headers={"X-Averio-Access": "sesame"}) as resp:
        assert resp.status_code == 200
        events = read_events(resp)
    assert events[-1] == {"type": "done"}
    assert sum(e["type"] == "final" for e in events) == 2


def test_missing_key_is_a_readable_503(monkeypatch):
    """No key must surface as a response the page can display, not as a
    stream that dies after the headers."""
    def no_key():
        raise RuntimeError("OPENROUTER_API_KEY is not set.")
    monkeypatch.setattr(demo, "make_client", no_key)
    resp = client.get("/api/ask", params={"q": "x"})
    assert resp.status_code == 503 and "OPENROUTER_API_KEY" in resp.json()["detail"]
    monkeypatch.setenv("AVERIO_VARIANT", "enduser")
    assert _chat({"messages": [{"role": "user", "content": "q"}]}).status_code == 503


def test_main_serves_from_the_environment(monkeypatch, capsys):
    """The deployment surface: face, host and port come from the
    environment, and a public bind without an access code does not start
    unless an open endpoint is asked for explicitly."""
    captured = {}
    monkeypatch.setattr("uvicorn.run",
                        lambda app, host, port: captured.update(host=host, port=port))
    # Keep the developer's real .env out of the test process.
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: False)
    monkeypatch.delenv("AVERIO_ALLOW_OPEN", raising=False)
    monkeypatch.setenv("AVERIO_VARIANT", "enduser")
    monkeypatch.setenv("HOST", "0.0.0.0")
    monkeypatch.setenv("PORT", "8123")
    # Forgetting the code on a host must fail, not quietly expose credits.
    with pytest.raises(SystemExit):
        demo.main()
    assert not captured
    # An open endpoint can be asked for; it still warns.
    monkeypatch.setenv("AVERIO_ALLOW_OPEN", "1")
    demo.main()
    assert captured == {"host": "0.0.0.0", "port": 8123}
    out, err = capsys.readouterr()
    assert "enduser" in out and "http://0.0.0.0:8123" in out
    assert "WARNING" in err and "AVERIO_ACCESS_CODE" in err
    # With a code set, a public bind is fine and quiet.
    monkeypatch.delenv("AVERIO_ALLOW_OPEN")
    monkeypatch.setenv("AVERIO_ACCESS_CODE", "sesame")
    demo.main()
    assert "WARNING" not in capsys.readouterr()[1]
    # Loopback never needs a code: a laptop, not a service.
    monkeypatch.delenv("AVERIO_ACCESS_CODE")
    monkeypatch.setenv("HOST", "127.0.0.1")
    demo.main()
    assert captured["host"] == "127.0.0.1"


def test_main_refuses_an_unknown_variant(monkeypatch):
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: False)
    monkeypatch.setattr("uvicorn.run", lambda *a, **k: pytest.fail("server started"))
    monkeypatch.setenv("AVERIO_VARIANT", "end-user")
    with pytest.raises(SystemExit):
        demo.main()


# --- The demo's live stream ---------------------------------------------------

def test_ask_stream_keeps_its_wire_contract(monkeypatch):
    """The demo page is written against these exact event shapes; pin them
    so server work shared with the chat cannot move them unnoticed."""
    fakes = fake_agents(monkeypatch)
    with client.stream("GET", "/api/ask", params={"q": "x" * 900}) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        # What a proxied deploy needs to pass frames through as they come.
        assert resp.headers["cache-control"] == "no-cache"
        assert resp.headers["x-accel-buffering"] == "no"
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
    # Both agents received the question cut to the published cap, with no
    # history: the demo's request is the eval's - exactly [system, question].
    for name in ("baseline", "governed"):
        sent = fakes[name].requests[0]["messages"]
        assert [m["role"] for m in sent] == ["system", "user"]
        assert len(sent[-1]["content"]) == demo.MAX_QUESTION_CHARS
    assert not fakes["client"].requests  # no title on the demo


def test_keepalive_frame_is_emitted_when_idle(monkeypatch):
    """A slow tool must not leave the connection silent: comment frames go
    out while nothing else happens, and the page ignores them."""
    monkeypatch.setattr(demo, "KEEPALIVE_SECONDS", 0.05)
    slow_echo = Tool(name="echo", description="echo", parameters=ECHO.parameters,
                     fn=lambda text: (time.sleep(0.3), {"echoed": text})[1])
    fake_agents(monkeypatch, tool=slow_echo)
    with client.stream("GET", "/api/ask", params={"q": "x"}) as resp:
        events, other = read_stream(resp)
    assert events[-1] == {"type": "done"}
    assert any(line.startswith(": ping") for line in other)


# --- The end-user chat ------------------------------------------------------------

def test_chat_streams_tool_calls_final_and_title(monkeypatch):
    monkeypatch.setenv("AVERIO_VARIANT", "enduser")
    fakes = fake_agents(monkeypatch)
    body = {"agent": "governed", "want_title": True,
            "messages": [{"role": "user", "content": "q1"},
                         {"role": "assistant", "content": "a1", "confidence": 70},
                         {"role": "user", "content": "q2"}]}
    with client.stream("POST", "/api/chat", json=body) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        assert resp.headers["cache-control"] == "no-cache"
        assert resp.headers["x-accel-buffering"] == "no"
        events = read_events(resp)
    types = [e["type"] for e in events]
    assert types[-1] == "done"
    assert types.count("final") == 1 and types.count("title") == 1
    call = next(e for e in events if e["type"] == "tool_call")
    assert (call["agent"], call["tool"]) == ("governed", "echo")
    final = next(e for e in events if e["type"] == "final")
    assert final["answer"] == "The answer" and final["confidence"] == 80
    assert final["layer_confidence"]["level"] == "policy"
    assert "verdict" not in final  # no answer key for a free conversation
    assert next(e for e in events if e["type"] == "title")["title"] == "Scripted title"
    # Only the requested agent was built, and it saw the conversation with
    # the confidence line restored on its earlier answer.
    assert set(fakes) == {"client", "governed"}
    sent = fakes["governed"].requests[0]["messages"]
    assert sent[0]["role"] == "system"
    assert [(m["role"], m["content"]) for m in sent[1:]] == [
        ("user", "q1"), ("assistant", "a1\n\nConfidence: 70%"), ("user", "q2")]
    # The title came from one tool-free, deterministic, hard-capped call.
    (title_call,) = fakes["client"].requests
    assert "tools" not in title_call
    assert title_call["temperature"] == 0
    assert title_call["max_tokens"] == demo.TITLE_MAX_TOKENS
    assert title_call["messages"][-1]["content"] == "q2"


def test_chat_title_falls_back_when_the_model_fails(monkeypatch):
    monkeypatch.setenv("AVERIO_VARIANT", "enduser")
    fakes = fake_agents(monkeypatch)
    # Arm the failure through the client the server will build.
    real_make_client = demo.make_client

    def failing_client():
        fake = real_make_client()
        fake.title = None
        return fake
    monkeypatch.setattr(demo, "make_client", failing_client)
    question = "What were net bookings in USD for fiscal year 2026 through period 10?"
    body = {"want_title": True, "messages": [{"role": "user", "content": question}]}
    with client.stream("POST", "/api/chat", json=body) as resp:
        events = read_events(resp)
    title = next(e for e in events if e["type"] == "title")["title"]
    assert title == demo.fallback_title(question)
    assert title.endswith("…") and len(title) <= demo.TITLE_FALLBACK_CHARS + 1
    assert any(e["type"] == "final" for e in events)  # the answer still arrived
    assert fakes["client"].requests  # the model was asked before falling back


def test_title_helpers_are_pure_and_bounded():
    assert demo.sanitize_title('"Net Bookings FY2026."') == "Net Bookings FY2026"
    assert demo.sanitize_title("Title: **Net bookings, FY2026**\nSecond line") == \
        "Net bookings, FY2026"
    assert demo.sanitize_title("") == "" and demo.sanitize_title(None) == ""
    assert demo.sanitize_title("   \n  ") == ""
    cut = demo.sanitize_title(" ".join(["word"] * 30))
    assert len(cut) <= demo.TITLE_MAX_CHARS and cut.endswith("word")
    assert demo.fallback_title("Short question?") == "Short question?"
    fb = demo.fallback_title("A " * 100)
    assert fb.endswith("…") and " …" not in fb  # word boundary, no dangling space
    assert len(fb) <= demo.TITLE_FALLBACK_CHARS + 1


def test_chat_validates_and_caps_input(monkeypatch):
    monkeypatch.setenv("AVERIO_VARIANT", "enduser")
    fakes = fake_agents(monkeypatch)
    assert _chat({"messages": []}).status_code == 422
    assert _chat({"messages": [{"role": "tool", "content": "x"}]}).status_code == 422
    assert _chat({"agent": "other",
                  "messages": [{"role": "user", "content": "q"}]}).status_code == 422
    assert _chat({"messages": [{"role": "user", "content": "q"},
                               {"role": "assistant", "content": "a"}]}).status_code == 400
    assert _chat({"messages": [{"role": "user", "content": "   "}]}).status_code == 400
    assert not fakes  # none of those built an agent or a client
    # A long question reaches the runner cut to the cap; thirty earlier
    # turns reach it as the newest twenty, opening on a user turn.
    turns = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"t{i}"}
             for i in range(30)]
    body = {"agent": "baseline",
            "messages": turns + [{"role": "user", "content": "x" * 900}]}
    with client.stream("POST", "/api/chat", json=body) as resp:
        assert resp.status_code == 200
        read_events(resp)
    sent = fakes["baseline"].requests[0]["messages"]
    assert len(sent) == 1 + demo.HISTORY_MAX_TURNS + 1
    assert sent[1] == {"role": "user", "content": "t10"}
    assert len(sent[-1]["content"]) == demo.MAX_QUESTION_CHARS
    assert set(fakes) == {"client", "baseline"}  # governed never built
    assert not fakes["client"].requests  # no title unless asked


def test_trim_history_bounds_and_normalises_turns():
    turn = demo.ChatTurn
    big = "x" * (demo.MAX_ASSISTANT_TURN_CHARS + 500)
    turns = []
    for i in range(8):
        turns += [turn(role="user", content=f"q{i}"),
                  turn(role="assistant", content=big, confidence=55)]
    history = demo.trim_history(turns)
    assert 0 < len(history) < len(turns)
    assert history[0]["role"] == "user"
    assert sum(len(t["content"]) for t in history) <= demo.HISTORY_MAX_CHARS
    line = "\n\nConfidence: 55%"
    for t in history:
        if t["role"] == "assistant":
            assert t["content"].endswith(line)  # restored, never eaten by the cap
            assert len(t["content"]) <= demo.MAX_ASSISTANT_TURN_CHARS + len(line)
    # Without a stored confidence nothing is invented; whitespace is trimmed.
    assert demo.trim_history([turn(role="user", content=" q "),
                              turn(role="assistant", content="a")]) == [
        {"role": "user", "content": "q"}, {"role": "assistant", "content": "a"}]
    # An orphaned opening reply is dropped.
    assert demo.trim_history([turn(role="assistant", content="a"),
                              turn(role="user", content="q")]) == [
        {"role": "user", "content": "q"}]


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
