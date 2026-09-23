"""Drift guards for the Heroku deployment files at the repo root.

The two hosted faces (jury demo, end-user assistant) deploy from the same
commit and differ only in config vars, so the root manifest is the whole
deployment contract: the Procfile must start the module whose main() reads
HOST/PORT/AVERIO_VARIANT, requirements.txt must install the extra that
carries fastapi/uvicorn (the core deps deliberately do not), the pinned
Python must satisfy the project floor, and the build hook must build the
database with the PINNED generator defaults - any other flag ships a slug
whose database disagrees with every recorded eval result the demo shows.
Nothing else in the suite reads these files; without this, a Heroku build
or boot after a push to master is where a mistake would surface.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PYPROJECT = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))


def _read(name: str) -> str:
    """The file's text, after checking what only the bytes can show: no BOM
    (a BOM before `web:` reads as "no web process type") and no CR (a CR
    after the shebang is "bad interpreter" on the Linux build). The
    .gitattributes rules pin these to LF in the index; this catches a
    working copy that drifted before it is ever pushed."""
    raw = (REPO / name).read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf"), f"{name} carries a UTF-8 BOM"
    assert b"\r" not in raw, f"{name} has CRLF line endings"
    return raw.decode("utf-8")


def test_procfile_runs_the_server_module_only():
    """One web process, started by the module whose main() validates the
    variant and refuses an open public bind. No release phase: release-phase
    filesystem changes never persist, so a `release:` generate_data would be
    a silent no-op."""
    procs = dict(re.findall(r"^(\w+):\s*(.+?)\s*$", _read("Procfile"), re.M))
    assert set(procs) == {"web"}, procs
    assert procs["web"].endswith("python -m averio.demo"), procs["web"]


def test_requirements_install_the_demo_extra():
    """The buildpack installs requirements.txt (a bare pyproject is not
    detected). The server's deps live in the `demo` extra, so that one line
    must pull it in - editable, so demo.REPO resolves to /app by itself."""
    lines = [line.strip() for line in _read("requirements.txt").splitlines()
             if line.strip() and not line.startswith("#")]
    assert lines == ["-e .[demo]"], lines
    demo_extra = PYPROJECT["project"]["optional-dependencies"]["demo"]
    names = {re.split(r"[<>=!~\[ ]", dep, maxsplit=1)[0] for dep in demo_extra}
    assert names >= {"fastapi", "uvicorn"}, names


def test_pinned_python_satisfies_the_project_floor():
    """`.python-version` is what Heroku runs: major.minor only, so patch
    releases arrive without a commit, and never below requires-python."""
    pinned = _read(".python-version").strip()
    assert re.fullmatch(r"\d+\.\d+", pinned), pinned
    floor = re.fullmatch(r">=\s*(\d+)\.(\d+)", PYPROJECT["project"]["requires-python"])
    assert floor, "requires-python is expected as a single >= floor"
    assert tuple(map(int, pinned.split("."))) >= tuple(map(int, floor.groups()))


def test_build_hook_generates_data_with_pinned_defaults():
    """bin/post_compile ships data/averio.duckdb in the slug. It must fail
    fast, cd to the app root (the generator writes relative to CWD), and
    call the generator exactly once with NO flags."""
    text = _read("bin/post_compile")
    assert text.startswith("#!/usr/bin/env bash\n")
    assert "set -euo pipefail" in text
    assert re.search(r"^cd ", text, re.M), "the hook must cd to the app root first"
    calls = re.findall(r"^[^#\n]*averio\.generate_data.*$", text, re.M)
    assert len(calls) == 1, calls
    call = calls[0].strip()
    assert re.fullmatch(r"(?:\S+=\S+\s+)*python -m averio\.generate_data", call), call
