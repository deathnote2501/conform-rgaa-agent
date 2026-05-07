#!/bin/bash
# send_5_daily.sh — envoie 5 emails de prospection (1 par appel send_email.py).
# Cron : Mon-Fri 7h30 Paris (cf. crontab CRON_TZ=Europe/Paris).
# PAUSE.flag / PAUSE.email.flag respectés par send_email.py lui-même.

cd "$(dirname "$0")/.."
mkdir -p logs
LOG="logs/cron-send-5.log"

ts() { date -u +%FT%TZ; }
echo "[$(ts)] === send_5_daily.sh start ===" >> "$LOG"

for i in 1 2 3 4 5; do
    echo "[$(ts)]   iter=$i: sending…" >> "$LOG"
    if doppler run --project conform-rgaa --config dev -- python3 scripts/send_email.py >> "$LOG" 2>&1; then
        echo "[$(ts)]   iter=$i: OK" >> "$LOG"
    else
        echo "[$(ts)]   iter=$i: FAILED (continuing)" >> "$LOG"
    fi
    [ "$i" -lt 5 ] && sleep 5
done

echo "[$(ts)] === send_5_daily.sh done ===" >> "$LOG"
