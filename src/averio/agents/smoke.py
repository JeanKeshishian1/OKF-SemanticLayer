"""Side-by-side smoke run: one question through both agents.

Not the eval - just the fastest way to see the experiment working end to
end (and to sanity-check the OpenRouter wiring and model slug). Requires
OPENROUTER_API_KEY in the environment; see agents/__init__.py.

    .\\.venv\\Scripts\\python.exe -m averio.agents.smoke "What were bookings in FY2026?"
"""

from __future__ import annotations

import argparse
import json

from averio.agents.baseline import build_baseline
from averio.agents.common import make_client, model_name
from averio.agents.governed import build_governed


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run one question through both agents.")
    parser.add_argument("question", nargs="?",
                        default="What were net bookings in FY2025?")
    parser.add_argument("--db", default="data/averio.duckdb")
    parser.add_argument("--bundle", default="bundle")
    parser.add_argument("--transcript", metavar="PATH",
                        help="optionally dump both transcripts as JSON")
    args = parser.parse_args(argv)

    client = make_client()
    agents = [build_baseline(args.db, client=client),
              build_governed(args.db, bundle_dir=args.bundle, client=client)]

    # Context parity is a design requirement - print it so drift is visible
    # on every run, not discovered at eval time.
    print(f"model: {model_name()}")
    for agent in agents:
        print(f"{agent.name} system prompt: {len(agent.system_prompt)} chars, "
              f"{len(agent.tools)} tools")

    results = []
    for agent in agents:
        print(f"\n=== {agent.name} ===\nQ: {args.question}")
        result = agent.ask(args.question)
        results.append(result)
        for entry in result["transcript"]:
            if entry["type"] == "tool_call":
                print(f"  [{entry['tool']}] {entry['arguments']}")
        print(f"A: {result['answer']}")

    if args.transcript:
        with open(args.transcript, "w", encoding="utf-8") as fh:
            json.dump(results, fh, indent=2, default=str)
        print(f"\ntranscripts written to {args.transcript}")


if __name__ == "__main__":
    main()
