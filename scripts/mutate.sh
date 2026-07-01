#!/usr/bin/env bash
# Mutation testing for ctx (mutmut).
#
# This is a PERIODIC / triage tool — deliberately NOT part of scripts/check.sh,
# because it re-runs the test suite once per mutant and is slow by design.
#
# It answers the question line coverage cannot: "are the tests strong enough to
# catch a fault?" mutmut injects tiny bugs (mutants) into the source and reruns
# the tests. A mutant that no test catches "survives" — a hole in the suite.
# Triage every survivor as one of:
#   - weak test       -> strengthen the assertion (it should have caught this)
#   - equivalent      -> the mutation doesn't change behavior; document & ignore
#   - real bug        -> the code is wrong; quarantine + log it (xfail/FOUND-BUGS.md)
#
# SERIAL + REPO-GLOBAL: mutmut uses one mutants/ working dir and cache at the repo
# root and is CPU-heavy. Run only ONE mutmut process at a time — do NOT run this
# concurrently across parallel sessions. The set of mutated modules is the union in
# [tool.mutmut].only_mutate (pyproject.toml); don't narrow that list for a focused
# run — instead pass a mutant-name glob to scope EXECUTION (below).
#
# Usage:
#   scripts/mutate.sh                       # mutate+run the whole only_mutate union, then results
#   scripts/mutate.sh run 'ctx.core.config.*'   # focused: only run mutants matching the glob
#   scripts/mutate.sh run 'ctx.core.a.*' 'ctx.core.b.*'  # ONE sweep over several modules
#                                             # (one session owning >1 module — cheaper than N runs)
#   scripts/mutate.sh verify '<mutant-id>' ['<id>' ...]  # scoped re-check: run ONLY these mutant
#                                             # ids (seconds vs minutes) to confirm a strengthening
#                                             # killed them — copy ids verbatim from results
#   scripts/mutate.sh results               # re-show the last run's results
#   scripts/mutate.sh browse                # interactive TUI over results
#   scripts/mutate.sh show <id>             # show the diff for one mutant
#
# NOTE: every `run`/`verify` regenerates the whole mutants/ tree AND re-runs the full baseline
# suite once — that cost is per-invocation, not per-glob. Combine globs into ONE sweep; scope a
# re-check with `verify`. Piping `run` to `tail` drops the 🎉/🙁 summary (it prints before the
# results dump) — capture full output or read `results` separately.
set -euo pipefail
cd "$(dirname "$0")/.."

case "${1:-run}" in
  run|verify)
    shift || true
    # Optional trailing args are mutant-name globs (fnmatch) to scope which mutants
    # are executed this run, e.g. 'ctx.core.storage.*' or an exact mutant id like
    # 'ctx.core.storage.xǁConversationRepositoryǁsave__mutmut_3'. With no glob, the
    # whole only_mutate union runs. `verify` is an alias for `run` — a naming cue that
    # you are re-checking specific mutant ids after a strengthening, not doing a full sweep.
    #
    # Regenerate from scratch first: mutmut caches the mutants/ tree and does NOT
    # invalidate it when [tool.mutmut].only_mutate changes — so a module added to the
    # union after a prior run would have no mutants (glob matches nothing, "0 files
    # mutated"). Deleting the cache forces generation against the current config.
    # Safe because the gate is serial (one mutmut at a time) and triage
    # (results/show/browse) happens after this run, reading the freshly-written tree.
    rm -rf mutants
    uv run mutmut run "$@"
    echo
    echo "==> results"
    uv run mutmut results
    ;;
  *)
    uv run mutmut "$@"
    ;;
esac
