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
on the demo).

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
                      for a public URL, not authentication
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
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

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
       verdict: {correct, leaks} | null}                  scored iff qid given
      {agent, type: "error", message}                     on failure
      {type: "done"}                                      when both finish

    ``qid`` is the eval question id when the presenter picked a curated
    question; it keys the deterministic scorer so the page can stamp each
    live answer correct/incorrect exactly as the recorded run would.

    The agents run in threads (their OpenAI-client calls are blocking) and
    push into one queue; the generator drains it in arrival order, so the
    page shows genuine interleaving - not a replay.
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

    def stream():
        events: queue.Queue = queue.Queue()
        client = make_client()
        agents = [build_baseline(str(DB), client=client),
                  build_governed(str(DB), bundle_dir=str(BUNDLE), client=client)]

        def run(agent):
            def relay(entry: dict) -> None:
                # Slim the entry for the wire: tool results can be large
                # (run_sql rows) and the page only narrates the calls.
                events.put({"agent": agent.name, "type": entry["type"],
                            "step": entry.get("step"),
                            "tool": entry.get("tool"),
                            "arguments": entry.get("arguments")})
            try:
                outcome = agent.ask(question, on_event=relay)
                events.put({"agent": agent.name, "type": "final",
                            "answer": outcome["answer"],
                            "steps": outcome["steps"],
                            "usage": outcome.get("usage"),
                            # The model's self-reported 0-100 confidence
                            # (None when it failed to state one).
                            "confidence": outcome.get("confidence"),
                            # The governed side also carries the calculated
                            # counterpart: what the layer's own signals
                            # (attestation, trust tier, staleness) prove.
                            "layer_confidence": (
                                layer_confidence(outcome.get("transcript"))
                                if agent.name == "governed" else None),
                            "verdict": judge(outcome["answer"])})
            except Exception as exc:  # surfaced on the page, never a crash
                events.put({"agent": agent.name, "type": "error",
                            "message": str(exc)})

        for agent in agents:
            threading.Thread(target=run, args=(agent,), daemon=True).start()

        finished = 0
        while finished < len(agents):
            event = events.get()
            if event["type"] in ("final", "error"):
                finished += 1
            yield f"data: {json.dumps(event, default=str)}\n\n"
        yield 'data: {"type": "done"}\n\n'

    return StreamingResponse(stream(), media_type="text/event-stream")


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
        print("WARNING: serving on a non-loopback host with no AVERIO_ACCESS_CODE - "
              "anyone who reaches this URL can spend your OpenRouter credits.",
              file=sys.stderr)
    # Flushed so it precedes uvicorn's own log lines when stdout is a pipe
    # (a platform log viewer), where it would otherwise surface at exit.
    print(f"Averio {requested} variant -> http://{host}:{port}", flush=True)
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
