#!/bin/bash
# One pass of the benchmark, unattended: reviews for the full and frontier sets at once; while they run, a judging
# pass every 30 minutes over the configurations whose reviews are complete; then one more review pass to retry
# errored runs, the final judging, checks, reports, the dataset export and the independent re-scoring.
# Usage: scripts/pass.sh <repeats, e.g. 1 or 2-3>   (logs in results/pass_r<repeats>/)
# Survives a closed terminal when started with nohup; every step resumes where it stopped if run again.
set -u
REPS="${1:-1}"
cd "$(dirname "$0")/.."
C=.venv/bin/crbench
LOG="results/pass_r${REPS}"
mkdir -p "$LOG"
say() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG/pass.log"; }
judge_all() {
  say "judging (configurations with every review done)"
  $C judge --set full --repeats "$REPS" >> "$LOG/judge.log" 2>&1; say "  full: exit $?"
  $C judge --set frontier --repeats "$REPS" >> "$LOG/judge.log" 2>&1; say "  frontier: exit $?"
}
reviews() {  # $1 = label
  $C run --set full --repeats "$REPS" > "$LOG/run_full_$1.log" 2>&1 &
  local full=$!
  $C run --set frontier --repeats "$REPS" > "$LOG/run_frontier_$1.log" 2>&1 &
  local frontier=$!
  say "reviews ($1) started: full pid $full, frontier pid $frontier"
  while kill -0 "$full" 2>/dev/null || kill -0 "$frontier" 2>/dev/null; do
    for _ in $(seq 180); do  # 30 minutes, checking every 10 s whether both finished
      sleep 10
      kill -0 "$full" 2>/dev/null || kill -0 "$frontier" 2>/dev/null || break
    done
    if kill -0 "$full" 2>/dev/null || kill -0 "$frontier" 2>/dev/null; then judge_all; fi
  done
  wait "$full"; say "reviews ($1) full: exit $? $(grep -h '^{' "$LOG/run_full_$1.log")"
  wait "$frontier"; say "reviews ($1) frontier: exit $? $(grep -h '^{' "$LOG/run_frontier_$1.log")"
}

say "pass with repeats $REPS starts"
reviews first
reviews retry          # errored runs (timeouts, provider errors) are made again; finished ones are skipped
judge_all
judge_all              # a second sweep picks up anything a judge left unfinished
say "checks"
$C check --set full --repeats "$REPS" > "$LOG/check_full.log" 2>&1; say "  full: $(tail -1 "$LOG/check_full.log")"
$C check --set frontier --repeats "$REPS" > "$LOG/check_frontier.log" 2>&1; say "  frontier: $(tail -1 "$LOG/check_frontier.log")"
say "reports"
$C report --set full --repeats "$REPS" --frontier --name "full-r${REPS}" > "$LOG/report.log" 2>&1
$C report --set frontier --repeats "$REPS" --name "frontier-r${REPS}" >> "$LOG/report.log" 2>&1
$C export > "$LOG/export.log" 2>&1
for r in "full-r${REPS}" "frontier-r${REPS}"; do say "  verify $r: $(.venv/bin/python scripts/verify_report.py "$r" 2>&1 | tail -1)"; done
$C cost --set full --repeats "$REPS" > "$LOG/cost_full.log" 2>&1
$C cost --set frontier --repeats "$REPS" > "$LOG/cost_frontier.log" 2>&1
say "pass with repeats $REPS done"
