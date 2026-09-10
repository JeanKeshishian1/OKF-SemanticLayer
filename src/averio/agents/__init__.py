"""The two experiment agents - identical model, one difference.

``baseline`` and ``governed`` share everything in ``common``: the same
OpenRouter-served model, the same tool-loop runner, the same read-only
``run_sql`` access to the DuckDB snapshot, the same raw schema block in
their prompts. The ONLY difference is the semantic layer: the governed
agent additionally receives the layer mandate and the four
``SemanticLayer`` tools (resolve / ambiguity_rule / security_rules /
compute), while the baseline receives volume-comparable neutral filler
(raw column profiles) instead - so the experiment measures governed
semantics, not extra context.

Configuration comes from the environment, never from code or the repo:

    OPENROUTER_API_KEY    required to actually call the model
    OPENROUTER_MODEL      model slug (default in common.DEFAULT_MODEL)
    OPENROUTER_BASE_URL   default https://openrouter.ai/api/v1
"""
