#!/usr/bin/env bash
# Quality gate ("back pressure") for ctx.
#
# Single entry point run by humans, the pre-commit hook, CI, and the Ralph loop.
# A change may only be committed when this passes. Order is cheapest-first so
# failures surface fast.
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> ruff"
uv run ruff check .

echo "==> mypy"
uv run mypy .

echo "==> pytest"
# pytest exit code 5 means "no tests collected". The deterministic pytest layer
# (Pilot smoke tests driving HarnessApp via TestProvider) is the required next
# step — until it lands, treat "no tests" as a pass so the slot exists now and
# the gate tightens automatically once tests are added.
#
# `-n auto` (pytest-xdist) runs the suite across one worker per logical CPU. The
# tests are isolated (per-test temp DB + temp workspace, see tests/conftest.py),
# so this is safe; it cuts the mostly startup/IO-bound Pilot suite ~4x (~97s->~25s).
set +e
uv run pytest -q -n auto
code=$?
set -e
if [ "$code" -eq 5 ]; then
  echo "    (no tests collected yet — see tests/README.md)"
elif [ "$code" -ne 0 ]; then
  exit "$code"
fi

echo "==> all checks passed"
