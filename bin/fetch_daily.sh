#!/bin/sh
# Fetch yesterday's finished jisseki file and load it.
#
# No `set -e`: it would abort on a non-zero fetch before the failure-logging
# lines below could run -- the error handler killed by the error.
set -u

REPO="$HOME/hokkaido-grid"
PY="$REPO/.venv/bin/python"
DAY=$(date -d yesterday +%Y-%m-%d)


cd "$REPO" || exit 78          # EX_CONFIG: broken environment, not bad data
mkdir -p logs state

# DAY is passed explicitly although main.py already defaults to yesterday,
# so the log records which day was attempted rather than leaving it to be
# reconstructed from the run timestamp.
"$PY" main.py daily "$DAY" >>logs/cron.log 2>&1
rc=$?

if [ "$rc" -eq 0 ]; then
    date -Iseconds >state/last_success
else
    printf '%s rc=%s day=%s\n' "$(date -Iseconds)" "$rc" "$DAY" >>logs/failures.log
fi

exit "$rc"
