"""Shared fixtures: one pinned-default dataset per test session.

The dataset is generated fresh into a session temp dir with the PINNED
defaults (seed 20260824, as-of 2026-08-24) - so every figure asserted in
any test file is the same figure in ``eval/ground_truth.json``, and tests
stay independent of whatever currently sits in ``data/``. Generation costs
~2 seconds once per session (bulk COPY load), which is why the fixtures
are session-scoped rather than per-test.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from averio import generate_data
from averio.semantic_layer import SemanticLayer

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def workspace(tmp_path_factory):
    """(db_path, ground_truth) built with the pinned experiment defaults."""
    tmp = tmp_path_factory.mktemp("averio-data")
    db = tmp / "averio.duckdb"
    gt_path = tmp / "ground_truth.json"
    generate_data.main(["--db", str(db), "--ground-truth", str(gt_path)])
    return db, json.loads(gt_path.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def layer(workspace):
    """A SemanticLayer over the session dataset and the repo bundle."""
    return SemanticLayer(REPO / "bundle", workspace[0])
