"""Averio's two faces on one server: the jury demo and the end-user assistant.

One FastAPI module, one HTML page (``demo_page.html``), one flag. The
``AVERIO_VARIANT`` environment variable decides which face a process serves:

  * ``demo`` (default) - the experiment on one page: the RECORDED story
    (scorecard, per-trap comparison, and a browser over every question of
    the latest full eval run, read straight from ``eval/results.json`` so
    no number is hardcoded and a rerun updates the demo automatically) plus
    a LIVE section where one question runs through BOTH agents
    concurrently, every tool call streamed to the page the moment it fires
    (server-sent events). Watching the governed agent walk
    resolve -> ambiguity_rule -> security_rules -> compute while the
    baseline fires raw SQL is the demo.
  * ``enduser`` - a plain chat with the governed agent (baseline switchable
    per chat) and a sidebar of the visitor's past chats, kept in their
    browser. Nothing of the demo - no scorecard, no duel, no recorded
    answers - reaches that browser.

Same checkout or image, two deployments, differing only in the flag (and
the port): ``/`` is rendered through ``render_page``, which keeps the
regions of ``demo_page.html`` wrapped in the active variant's marker
comments and strips the other variant's, and the variant-specific routes
answer 404 on the other face (``/api/results`` and ``/api/ask`` exist only
on the demo, ``/api/chat`` only on the end-user face). Both live routes
speak the same server-sent-event wire through one streaming helper.

Nothing here touches the experiment: the server is a *consumer* of the
same ``build_baseline`` / ``build_governed`` factories the eval harness
uses, with the same environment-driven model. Run it with:

    .\\.venv\\Scripts\\python.exe -m averio.demo     # http://127.0.0.1:8000

Serving environment, all optional (the agents still need OPENROUTER_API_KEY
for anything live; everything recorded works offline):

  AVERIO_VARIANT      demo | enduser (default demo)
  HOST, PORT          bind address and port (default 127.0.0.1:8000 -
                      presentation equipment on a laptop unless told
                      otherwise; hosting platforms inject PORT)
  AVERIO_ACCESS_CODE  when set, the credit-spending endpoints require it
                      as the X-Averio-Access header - a soft spend gate
                      for a public URL, not authentication. A non-loopback
                      HOST refuses to start without it unless
                      AVERIO_ALLOW_OPEN=1 says an open endpoint is intended
  AVERIO_REPO         root holding eval/, data/, bundle/ for a
                      non-editable install; read at import, so it must be
                      a real process variable, not just a .env line
"""

from __future__ import annotations

import hmac
import json
import os
import queue
import re
import sys
import threading
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from averio.agents.baseline import build_baseline
from averio.agents.common import make_client, model_name
from averio.agents.governed import build_governed
from averio.evaluate import ScoringContext, score_answer
from averio.semantic_layer import layer_confidence

# Repo root: two levels above src/averio/ in an editable checkout. A
# non-editable install (a container image) has no such tree around the
# package, so AVERIO_REPO names the directory holding eval/, data/ and
# bundle/ instead. Resolved once at import, which is why it has to be a
# process environment variable: main() loads .env only after this module
# is already imported.
REPO = (Path(os.environ["AVERIO_REPO"]).resolve() if os.environ.get("AVERIO_REPO")
        else Path(__file__).resolve().parents[2])
PAGE = Path(__file__).with_name("demo_page.html")
RESULTS = REPO / "eval" / "results.json"
QUESTIONS = REPO / "eval" / "questions.json"
GROUND_TRUTH = REPO / "eval" / "ground_truth.json"
DB = REPO / "data" / "averio.duckdb"
BUNDLE = REPO / "bundle"

# Questions are stage or chat input, not an API: capped so one paste cannot
# blow up a prompt. /api/config publishes the figure so the page's own
# counter can never drift from the server's cut.
MAX_QUESTION_CHARS = 500

# A chat replays its earlier turns to the model (text only - see
# AgentRunner.ask). These caps bound what one request can cost: the newest
# HISTORY_MAX_TURNS turns, each assistant turn cut to
# MAX_ASSISTANT_TURN_CHARS (a long answer's tables add little to a
# follow-up), and the oldest dropped until the whole history fits
# HISTORY_MAX_CHARS. The page sends only completed pairs, so these are
# backstops, not the normal path.
HISTORY_MAX_TURNS = 20
MAX_ASSISTANT_TURN_CHARS = 4000
HISTORY_MAX_CHARS = 24_000

# Proxies and platform load balancers drop idle streams (60-100 s is
# common); a comment frame every KEEPALIVE_SECONDS keeps a slow question's
# connection alive without the page ever seeing an event.
KEEPALIVE_SECONDS = 15

# Chat titles: one tiny, tool-free completion by the same model, capped
# hard because it is pure convenience - the fallback is the question's own
# first words, never an error.
TITLE_MAX_TOKENS = 24
TITLE_MAX_CHARS = 60
TITLE_FALLBACK_CHARS = 40


# --- Which face this process serves -------------------------------------------

VARIANTS = ("demo", "enduser")
DEFAULT_VARIANT = "demo"


def variant() -> str:
    """The active variant, from AVERIO_VARIANT.

    Read on every call rather than frozen at import: the offline tests
    build one TestClient over this module and flip the variable between
    requests, and a per-call read is also what lets a value loaded from
    .env in main() take effect. An unrecognised value falls back to the
    demo HERE (a request must never 500 over a typo) - but main() refuses
    to START on one, so a misspelt flag cannot quietly deploy the wrong
    face to a URL.
    """
    value = os.environ.get("AVERIO_VARIANT", DEFAULT_VARIANT).strip().lower()
    return value if value in VARIANTS else DEFAULT_VARIANT


# The single page carries both faces. Regions that belong to one only are
# wrapped in marker comments and the server keeps exactly the active
# variant's regions:
#
#     <!-- variant:demo -->    ... demo-only markup / <style> / <script> ...
#     <!-- /variant -->
#
# Convention (a test pins it once the page is split): markers sit BETWEEN
# elements - never inside <style>/<script> text or inside a tag - regions
# never nest, and variant-specific CSS/JS live in their own <style>/<script>
# elements wrapped whole. Stripping server-side is what makes "nothing of
# the demo reaches the end-user browser" literally true: it is not hidden
# by CSS, it is never sent.
VARIANT_REGION = re.compile(
    r"<!--\s*variant:(demo|enduser)\s*-->(.*?)<!--\s*/variant\s*-->", re.DOTALL)
_MARKER_RESIDUE = re.compile(r"<!--\s*/?variant")


def render_page(html: str, active: str) -> str:
    """Keep ``active``'s marked regions, drop the other variant's.

    Non-greedy matching stops at the first closer, so with no nesting every
    region is matched exactly once. A missing closer would make a region
    swallow everything up to the NEXT closer, and a nested or stray marker
    survives the substitution - so any marker text left after the pass
    means the page is broken, and it is raised loudly: a 500 on the
    presenter's screen beats a silently mangled page in front of a jury,
    or demo markup leaking to end users.
    """
    out = VARIANT_REGION.sub(lambda m: m.group(2) if m.group(1) == active else "", html)
    if _MARKER_RESIDUE.search(out):
        raise RuntimeError("demo_page.html has unbalanced or nested variant markers")
    return out


def _only(name: str):
    """Route guard: 404 unless this process serves ``name``.

    A FastAPI dependency rather than a startup-time choice of routers, so
    the flag is read per request (testable in one process) and the check
    runs before any body parsing or agent construction. The plain
    'Not Found' keeps a gated route indistinguishable from an unknown one:
    the other face's API simply does not exist at this URL.
    """
    def guard() -> None:
        if variant() != name:
            raise HTTPException(status_code=404, detail="Not Found")
    return guard


demo_only = Depends(_only("demo"))
enduser_only = Depends(_only("enduser"))


# --- Access code ---------------------------------------------------------------

def access_code() -> str:
    """The shared code guarding the live endpoints; empty means open."""
    return os.environ.get("AVERIO_ACCESS_CODE", "")


def require_access(x_averio_access: Annotated[str | None, Header()] = None) -> None:
    """Soft spend gate for the endpoints that call the model.

    A public URL spends the owner's OpenRouter credits for anyone who finds
    it. When AVERIO_ACCESS_CODE is set, live requests must carry it in the
    X-Averio-Access header; the page asks the visitor once and remembers
    it. This is deliberately not authentication (one shared code, visible
    in the browser) - just enough that a stray crawler or a forwarded link
    cannot drain the budget. Unset means open, which is right for a laptop
    on localhost. The comparison is constant-time and on bytes:
    compare_digest rejects non-ASCII str, and timing must not leak the
    code's prefix.
    """
    expected = access_code()
    if not expected:
        return
    supplied = (x_averio_access or "").encode("utf-8")
    if not hmac.compare_digest(supplied, expected.encode("utf-8")):
        raise HTTPException(status_code=401, detail="Access code missing or incorrect")


needs_access = Depends(require_access)


# --- Streaming ------------------------------------------------------------------
#
# Both live routes speak the same wire: server-sent events, one JSON object
# per `data:` frame, produced by PRODUCERS running in daemon threads (the
# OpenAI client blocks) and drained by one generator in arrival order - so
# the page sees genuine interleaving, not a replay. A producer is a
# callable taking an `emit` function, and it MUST end with exactly one
# terminal event: the generator counts terminals to know when every
# producer is done, so a producer that could raise or hang without
# emitting one would hang the stream. Both producers below guard that.

TERMINAL_TYPES = frozenset({"final", "error", "title"})


def sse(body) -> StreamingResponse:
    """An event-stream response with the headers a proxied deploy needs:
    no caching, and nginx-style buffering off so frames leave as they are
    produced instead of arriving in one lump when the stream closes."""
    return StreamingResponse(body, media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


def run_streamed(producers):
    """Run the producers concurrently and yield SSE frames until each has
    emitted its terminal event, then a closing ``{"type": "done"}``.

    The queue wait times out every KEEPALIVE_SECONDS to yield a comment
    frame (``: ping``) - invisible to the page's parser, enough to keep an
    idle connection open through an intermediary while a slow question
    thinks.
    """
    events: queue.Queue = queue.Queue()
    for produce in producers:
        threading.Thread(target=produce, args=(events.put,), daemon=True).start()
    finished = 0
    while finished < len(producers):
        try:
            event = events.get(timeout=KEEPALIVE_SECONDS)
        except queue.Empty:
            yield ": ping\n\n"
            continue
        if event.get("type") in TERMINAL_TYPES:
            finished += 1
        yield f"data: {json.dumps(event, default=str)}\n\n"
    yield 'data: {"type": "done"}\n\n'


def agent_producer(agent, question: str, *, history=None, judge=None):
    """A producer that runs one agent and narrates it as it works.

    Emits ``{agent, type, step, tool, arguments}`` for every transcript
    entry the moment it happens (slimmed for the wire: tool RESULTS can be
    large - run_sql rows - and the page only narrates the calls), then
    exactly one terminal. ``final`` carries the answer, the step count, the
    real OpenRouter spend, the model's self-reported 0-100 confidence (None
    when it failed to state one) and, for the governed agent, the
    calculated counterpart: what the layer's own signals (attestation,
    trust tier, staleness) prove. ``error`` surfaces any exception on the
    page rather than crashing the stream. ``verdict`` rides along only when
    a ``judge`` is given - the demo scoring a curated question; the chat
    has no answer key and makes no such claim.
    """
    def produce(emit) -> None:
        def relay(entry: dict) -> None:
            emit({"agent": agent.name, "type": entry["type"],
                  "step": entry.get("step"),
                  "tool": entry.get("tool"),
                  "arguments": entry.get("arguments")})
        try:
            outcome = agent.ask(question, on_event=relay, history=history)
            final = {"agent": agent.name, "type": "final",
                     "answer": outcome["answer"],
                     "steps": outcome["steps"],
                     "usage": outcome.get("usage"),
                     "confidence": outcome.get("confidence"),
                     "layer_confidence": (
                         layer_confidence(outcome.get("transcript"))
                         if agent.name == "governed" else None)}
            if judge is not None:
                final["verdict"] = judge(outcome["answer"])
            emit(final)
        except Exception as exc:
            emit({"agent": agent.name, "type": "error", "message": str(exc)})
    return produce


def title_producer(client, question: str):
    """A producer that names a new chat. It always emits a ``title`` event
    (generate_title never raises), so the terminal count stays exact."""
    def produce(emit) -> None:
        emit({"type": "title", "title": generate_title(client, question)})
    return produce


def _client():
    """The OpenRouter client, or a readable 503 when there is no key.

    Built in the endpoint body, before the response starts: a RuntimeError
    raised inside the generator would reach the page as a truncated
    stream, whereas a 503 with the message is something it can display.
    """
    try:
        return make_client()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


# --- Chat titles ----------------------------------------------------------------

TITLE_INSTRUCTION = ("Reply with a 3-6 word title for this question. "
                     "No quotes, no trailing period.")


def _cut_at_word(text: str, limit: int) -> str:
    """``text`` cut to at most ``limit`` characters - at a word boundary
    where one exists - without a dangling separator."""
    if len(text) <= limit:
        return text
    cut = text[:limit]
    if " " in cut:
        cut = cut[:cut.rfind(" ")]
    return cut.rstrip(" ,;:.-")


def fallback_title(question: str) -> str:
    """The question's own first words - what a chat is called when the
    model cannot name it (no key, an error, an empty reply)."""
    text = " ".join(question.split())
    if len(text) <= TITLE_FALLBACK_CHARS:
        return text
    return _cut_at_word(text, TITLE_FALLBACK_CHARS) + "…"


def sanitize_title(raw: str | None) -> str:
    """One clean line out of whatever the model returned: the first
    non-empty line, a 'Title:' prefix and quote/markdown dressing removed,
    spaces collapsed, no trailing period, capped at a word boundary. Empty
    when nothing usable remains - the caller falls back, never shows it."""
    lines = [line.strip() for line in (raw or "").splitlines() if line.strip()]
    if not lines:
        return ""
    text = re.sub(r"(?i)^\s*title\s*:\s*", "", lines[0])
    text = " ".join(text.strip(" \"'`*.").split())
    return _cut_at_word(text, TITLE_MAX_CHARS)


def generate_title(client, question: str) -> str:
    """Name a chat from its first question with one tiny, tool-free call.

    Same model, temperature 0, a hard token cap. Reasoning is switched off
    for this call - an OpenRouter-level switch that providers without the
    feature ignore - because a thinking model would spend the whole cap
    thinking and return nothing. Any failure, or an empty or unusable
    reply, yields the fallback: a title is convenience and must never
    cost the visitor an error. Nothing here touches the agents' calls.
    """
    try:
        response = client.chat.completions.create(
            model=model_name(),
            messages=[{"role": "system", "content": TITLE_INSTRUCTION},
                      {"role": "user", "content": question}],
            temperature=0, max_tokens=TITLE_MAX_TOKENS,
            extra_body={"reasoning": {"enabled": False}})
        title = sanitize_title(response.choices[0].message.content)
    except Exception:
        title = ""
    return title or fallback_title(question)


# --- Chat requests --------------------------------------------------------------

class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    # The model's self-reported confidence for an assistant turn. The
    # runner strips the trailing "Confidence: NN%" line from every answer
    # before the page stores it; trim_history puts the line back when the
    # turn is replayed, so the model sees its earlier answers in exactly
    # the form the system prompt demands and keeps producing the line.
    confidence: int | None = None


class ChatRequest(BaseModel):
    agent: Literal["baseline", "governed"] = "governed"
    messages: list[ChatTurn] = Field(min_length=1)
    # True on a chat's first exchange: the server names the chat alongside
    # the answer (a `title` event) instead of the page making a second
    # request for it.
    want_title: bool = False


def trim_history(turns: list[ChatTurn]) -> list[dict]:
    """Earlier turns as the runner takes them, bounded and normalised.

    Per-turn caps first (user turns to the question cap, assistant turns
    to MAX_ASSISTANT_TURN_CHARS, then the confidence line re-appended so
    the cap can never eat it), then the newest HISTORY_MAX_TURNS, then the
    oldest dropped until the total fits HISTORY_MAX_CHARS. Whatever
    survives starts on a user turn: a history opening with an orphaned
    assistant reply reads as a conversation the model never had.
    """
    history: list[dict] = []
    for turn in turns:
        if turn.role == "assistant":
            content = turn.content.strip()[:MAX_ASSISTANT_TURN_CHARS]
            if turn.confidence is not None:
                content = f"{content}\n\nConfidence: {max(0, min(100, turn.confidence))}%"
        else:
            content = turn.content.strip()[:MAX_QUESTION_CHARS]
        history.append({"role": turn.role, "content": content})
    history = history[-HISTORY_MAX_TURNS:]
    while history and sum(len(t["content"]) for t in history) > HISTORY_MAX_CHARS:
        history.pop(0)
    while history and history[0]["role"] != "user":
        history.pop(0)
    return history


@lru_cache(maxsize=1)
def _scoring() -> tuple[ScoringContext, dict]:
    """The eval's own deterministic scorer, reused for live verdicts.

    A live answer to a CURATED question can be scored exactly like the
    recorded run (the question id keys its expectation); a free-text
    question has no answer key, so it stays honestly unscored - the demo
    never improvises a judgment the experiment could not defend.
    """
    truth = json.loads(GROUND_TRUTH.read_text(encoding="utf-8"))
    questions = {q["id"]: q for q in
                 json.loads(QUESTIONS.read_text(encoding="utf-8"))["questions"]}
    return ScoringContext(truth, str(DB)), questions

# Curated showcase questions for the live section: each is a question from
# the eval set whose failure mode is *visible* on stage, with a one-line
# "watch for" cue the presenter can narrate. Free-text questions work too -
# this list just guarantees drama on demand. The end-user face reuses the
# question texts as its suggested prompts (never the cues).
CURATED_IDS = {
    "F1-01": "Watch which window each agent uses: fiscal 2026 starts Oct 2025.",
    "SEC1-01": "The name is restricted - watch who leaks it and who masks it.",
    "A1-01": "No approved margin formula exists - watch who invents one.",
    "S1-02": "The cancellation computation is stale - watch who says so.",
    "B4-02": "Summing Book Amt across currencies is meaningless - watch who refuses.",
    "C-01": "Four country roles exist - watch who asks which one you meant.",
}

app = FastAPI(title="Averio semantic layer")


@app.get("/", response_class=HTMLResponse)
def page() -> str:
    # Read per request - the presenter can edit the page without a
    # restart - and rendered for whichever face this process serves.
    return render_page(PAGE.read_text(encoding="utf-8"), variant())


@app.get("/api/results", dependencies=[demo_only])
def results() -> JSONResponse:
    """The latest full eval run - the page derives every recorded number
    from this, so demo and experiment can never disagree.

    Governed rows are enriched on the fly with the layer-derived confidence
    (computed here, from the stored transcript, by the same function the
    live stream uses - one implementation, no chance of drift; it also
    means runs recorded before the feature existed get the chip)."""
    data = json.loads(RESULTS.read_text(encoding="utf-8"))
    for row in data.get("results", []):
        if isinstance(row, dict) and row.get("agent") == "governed":
            row["layer_confidence"] = layer_confidence(row.get("transcript"))
    return JSONResponse(data)


@app.get("/api/curated")
def curated() -> JSONResponse:
    by_id = {q["id"]: q for q in
             json.loads(QUESTIONS.read_text(encoding="utf-8"))["questions"]}
    return JSONResponse([
        {"id": qid, "question": by_id[qid]["question"], "watch_for": cue}
        for qid, cue in CURATED_IDS.items() if qid in by_id])


@app.get("/api/ask", dependencies=[demo_only, needs_access])
def ask(q: str, qid: str | None = None) -> StreamingResponse:
    """Run one question through both agents concurrently, streaming events.

    Server-sent events, one JSON object per event:
      {agent, type: "tool_call", step, tool, arguments}   as each tool fires
      {agent, type: "final", answer, steps,
       usage: {tokens, cost_usd, ...},                    real OpenRouter spend
       confidence, layer_confidence,
       verdict: {correct, leaks} | null}                  scored iff qid given
      {agent, type: "error", message}                     on failure
      {type: "done"}                                      when both finish

    ``qid`` is the eval question id when the presenter picked a curated
    question; it keys the deterministic scorer so the page can stamp each
    live answer correct/incorrect exactly as the recorded run would.
    """
    question = q.strip()[:MAX_QUESTION_CHARS]

    def judge(answer: str) -> dict | None:
        """Deterministic verdict for a curated question; None = unscored."""
        if not qid:
            return None
        try:
            ctx, questions = _scoring()
            spec = questions.get(qid)
            if spec is None:
                return None
            score = score_answer(spec, answer, ctx)
            return {"correct": score["correct"],
                    "leaks": len(score["leaked_names"])}
        except Exception:  # a scoring hiccup must never kill the stream
            return None

    client = _client()
    agents = [build_baseline(str(DB), client=client),
              build_governed(str(DB), bundle_dir=str(BUNDLE), client=client)]
    return sse(run_streamed([agent_producer(agent, question, judge=judge)
                             for agent in agents]))


@app.post("/api/chat", dependencies=[enduser_only, needs_access])
def chat(request: ChatRequest) -> StreamingResponse:
    """One turn of an end-user chat with ONE agent, streaming events.

    The body carries the whole conversation so far - the browser owns the
    history, the server stores nothing - with the new question last:
      {agent: "governed" | "baseline", want_title: bool,
       messages: [{role, content, confidence?}, ...]}
    Events are the demo's minus ``verdict`` (there is no answer key for a
    free conversation), plus:
      {type: "title", title}    when want_title, alongside the answer
      {type: "done"}
    Only the requested agent is built, so a turn costs one agent run. The
    agent never changes mid-conversation: the page fixes it at the first
    message and each request names it explicitly, so a chat's history is
    always one agent's own answers.
    """
    last = request.messages[-1]
    if last.role != "user":
        raise HTTPException(status_code=400,
                            detail="The last message must be the user's question.")
    question = last.content.strip()[:MAX_QUESTION_CHARS]
    if not question:
        raise HTTPException(status_code=400, detail="The question is empty.")
    history = trim_history(request.messages[:-1])
    client = _client()
    if request.agent == "governed":
        agent = build_governed(str(DB), bundle_dir=str(BUNDLE), client=client)
    else:
        agent = build_baseline(str(DB), client=client)
    producers = [agent_producer(agent, question, history=history)]
    if request.want_title:
        producers.append(title_producer(client, question))
    return sse(run_streamed(producers))


@app.get("/api/access", dependencies=[needs_access])
def access_check() -> JSONResponse:
    """Lets a page verify a code before anything is asked, so a wrong or
    stale code is refused at once rather than at the first refused
    question. Spends nothing: the dependency has already done the
    comparison, and with no code configured it simply answers ok."""
    return JSONResponse({"ok": True})


@app.get("/api/config")
def config() -> JSONResponse:
    """What a page needs before its first request: which face it is,
    whether the live path can run at all, and whether a code must be
    collected before anything spends credits."""
    return JSONResponse({"model": model_name(),
                         "variant": variant(),
                         "live_ready": DB.exists(),
                         "results_ready": RESULTS.exists(),
                         "access_required": bool(access_code()),
                         "max_question_chars": MAX_QUESTION_CHARS})


# Hosts on which an open (no access code) server only reaches the machine
# it runs on. Anything else is reachable by others and gets a warning.
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def main() -> None:
    import uvicorn
    from dotenv import load_dotenv

    # .env may carry the serving flags too (AVERIO_VARIANT, HOST, PORT,
    # AVERIO_ACCESS_CODE). Real environment variables win, as everywhere in
    # the project, so a hosting platform's per-service settings override
    # the file - that is what lets one image serve both faces. Loaded here
    # and not at import: importing this module (tests, tooling) must never
    # read anyone's .env.
    load_dotenv()
    requested = os.environ.get("AVERIO_VARIANT", DEFAULT_VARIANT).strip().lower()
    if requested not in VARIANTS:
        # variant() would fall back to the demo per request; at startup a
        # typo must fail, or the wrong face ends up behind the URL.
        sys.exit(f"AVERIO_VARIANT={requested!r} is not one of {VARIANTS}; "
                 "refusing to start.")
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8000"))
    if host not in LOOPBACK_HOSTS and not access_code():
        # A public bind with no code hands the owner's OpenRouter credits to
        # anyone who finds the URL - the one deployment mistake this server
        # must not allow by default. Forgetting the variable on the host
        # therefore fails loudly; an open endpoint has to be asked for.
        if os.environ.get("AVERIO_ALLOW_OPEN", "").strip().lower() not in ("1", "true", "yes"):
            sys.exit(f"HOST={host} is reachable by others and AVERIO_ACCESS_CODE is not set. "
                     "Set a code (the page asks visitors for it once), or set "
                     "AVERIO_ALLOW_OPEN=1 to serve an open endpoint on purpose.")
        print("WARNING: serving on a non-loopback host with no AVERIO_ACCESS_CODE - "
              "anyone who reaches this URL can spend your OpenRouter credits.",
              file=sys.stderr)
    # Flushed so it precedes uvicorn's own log lines when stdout is a pipe
    # (a platform log viewer), where it would otherwise surface at exit.
    print(f"Averio {requested} variant -> http://{host}:{port}", flush=True)
    # One process, stated explicitly. Left unset, uvicorn takes its worker
    # count from WEB_CONCURRENCY, which Heroku's Python buildpack exports on
    # every dyno (2 on 512 MB) - and uvicorn refuses to run an app *object*
    # with more than one worker, so the dyno exited at boot (H10) with a
    # message about import strings. This server is single-process by
    # design: each request runs its agents on its own threads and nothing
    # is shared, so a second process would only double the memory footprint.
    uvicorn.run(app, host=host, port=port, workers=1)


if __name__ == "__main__":
    main()
