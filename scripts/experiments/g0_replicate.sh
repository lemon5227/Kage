#!/bin/zsh
# Replicate the G0 desktop findings with a second 4B student (paper §5): same tasks, tools, server settings and
# arms as evidence/reports/g0; lessons are written by the teacher from this student's own training failures.
#   KAGE_MODEL_PATH=<gguf> scripts/experiments/g0_replicate.sh <name>
set -e
cd "$(dirname "$0")/../.."
PY=${PY:-/Users/wenbo/.codex/worktrees/c2-learning-loop/Kage/.venv-computer-use/bin/python}
NAME=${1:?name}
OUT=$HOME/.kage/g0/$NAME
TRAIN=calc_add,calc_mul,calc_div,calc_chain,te_fix,te_append,te_write,set_icon_size,set_scrollbars,set_nav_tint
TEST=calc_chain2,calc_chain3,te_fix2,te_append2,te_write2
TE=te_fix,te_append,te_write,te_fix2,te_append2,te_write2
run() { echo "== $(date +%H:%M:%S) $1"; $PY scripts/experiments/desktop_run.py --arm a0 --runs 3 --out $OUT/$1 "${@:2}" | tail -1; }
mkdir -p $OUT
# keep the display (and so the session) awake for the whole replication; runs also wait while it is locked
caffeinate -dimsu -w $$ &
[ -f $OUT/a0-train-v2/results.jsonl ] || run a0-train-v2 --tasks $TRAIN --interface v2
[ -f $OUT/a0-train-v2/lessons.json ] || { echo "== teach"; $PY scripts/experiments/desktop_run.py --arm teach --from $OUT/a0-train-v2 | tail -1; }
L=$OUT/a0-train-v2/lessons.json
[ -f $OUT/a0-test-v2/results.jsonl ] || run a0-test-v2 --tasks $TEST --interface v2
[ -f $OUT/a0-test-v2-lessons/results.jsonl ] || run a0-test-v2-lessons --tasks $TEST --interface v2 --lessons $L
[ -f $OUT/a0-test-v2-planonly/results.jsonl ] || run a0-test-v2-planonly --tasks $TEST --interface v2 --lesson-mode plan-only
[ -f $OUT/a0-test-v2-plan/results.jsonl ] || run a0-test-v2-plan --tasks $TEST --interface v2 --lessons $L --lesson-mode plan
[ -f $OUT/a0-te-v4/results.jsonl ] || run a0-te-v4 --tasks $TE --interface v4
[ -f $OUT/a0-final-v4-plan/results.jsonl ] || run a0-final-v4-plan --tasks $TRAIN,$TEST --interface v4 --lessons $L --lesson-mode plan
echo "== done $(date +%H:%M:%S)"
