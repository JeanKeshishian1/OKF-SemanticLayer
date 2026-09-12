"""Local jury-demo server: the experiment on one page, plus live questions.

Serves a single HTML page (``demo_page.html``) with two halves:

  * the RECORDED story - scorecard, per-trap comparison, and a browser over
    every question of the latest full eval run, read straight from
    ``eval/results.json`` (no numbers are hardcoded in the page, so a rerun
    updates the demo automatically); and
  * a LIVE section - one question runs through BOTH agents concurrently,
    with every tool call streamed to the page the moment it fires
    (server-sent events). Watching the governed agent walk
    resolve -> ambiguity_rule -> security_rules -> compute while the
    baseline fires raw SQL is the demo.

Nothing here touches the experiment: the server is a *consumer* of the
same ``build_baseline`` / ``build_governed`` factories the eval harness
uses, with the same environment-driven model. Run it with:

    .\\.venv\\Scripts\\python.exe -m averio.demo     # http://127.0.0.1:8000

The server binds localhost only - it is presentation equipment, not a
deployment - and needs OPENROUTER_API_KEY (via .env) for the live section;
everything recorded works offline.
"""

from __future__ import annotations

import json
import queue
import threading
from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

from averio.agents.baseline import build_baseline
from averio.agents.common import make_client, model_name
from averio.agents.governed import build_governed
from averio.evaluate import ScoringContext, score_answer

REPO = Path(__file__).resolve().parents[2]
PAGE = Path(__file__).with_name("demo_page.html")
RESULTS = REPO / "eval" / "results.json"
QUESTIONS = REPO / "eval" / "questions.json"
GROUND_TRUTH = REPO / "eval" / "ground_truth.json"
DB = REPO / "data" / "averio.duckdb"
BUNDLE = REPO / "bundle"


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
# this list just guarantees drama on demand.
CURATED_IDS = {
    "F1-01": "Watch which window each agent uses: fiscal 2026 starts Oct 2025.",
    "SEC1-01": "The name is restricted - watch who leaks it and who masks it.",
    "A1-01": "No approved margin formula exists - watch who invents one.",
    "S1-02": "The cancellation computation is stale - watch who says so.",
    "B4-02": "Summing Book Amt across currencies is meaningless - watch who refuses.",
    "C-01": "Four country roles exist - watch who asks which one you meant.",
}

app = FastAPI(title="Averio semantic-layer demo")


@app.get("/", response_class=HTMLResponse)
def page() -> str:
    return PAGE.read_text(encoding="utf-8")


@app.get("/api/results")
def results() -> JSONResponse:
    """The latest full eval run, verbatim - the page derives every recorded
    number from this, so demo and experiment can never disagree."""
    return JSONResponse(json.loads(RESULTS.read_text(encoding="utf-8")))


@app.get("/api/curated")
def curated() -> JSONResponse:
    by_id = {q["id"]: q for q in
             json.loads(QUESTIONS.read_text(encoding="utf-8"))["questions"]}
    return JSONResponse([
        {"id": qid, "question": by_id[qid]["question"], "watch_for": cue}
        for qid, cue in CURATED_IDS.items() if qid in by_id])


@app.get("/api/ask")
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
    question = q.strip()[:500]  # stage input, not an API; keep it sane

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
    return JSONResponse({"model": model_name(),
                         "live_ready": DB.exists(),
                         "results_ready": RESULTS.exists()})


def main() -> None:
    import uvicorn

    # localhost only: this is presentation equipment on the presenter's
    # laptop, never a service.
    uvicorn.run(app, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
