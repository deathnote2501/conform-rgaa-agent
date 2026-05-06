#!/bin/bash
# run.sh — boucle d'action conform-rgaa-agent (1 action par run)
# Cron : toutes les 30 min de 5h à 21h UTC.

set -euo pipefail
cd "$(dirname "$0")"

mkdir -p logs memory

# Pause kill switch
if [ -f PAUSE.flag ]; then
    echo "[$(date -u +%FT%TZ)] PAUSE.flag présent — exit." >> logs/run.log
    exit 0
fi

# Token "1 action par run" : créé ici, claim() par le 1er skill Python lancé
TOKEN="$(mktemp /tmp/conform-rgaa-token.XXXXXX)"
export CONFORM_RGAA_ACTION_TOKEN="$TOKEN"
trap 'rm -f "$TOKEN"' EXIT

# Décide l'action prioritaire :
#   P1. Si pool envoi non vide ET cap < 10 → send_email
#   P2. Sinon, scrape RGAA (batch 20)
#   P3. (ingest API → tâche cron hebdo dédiée, pas dans cette boucle)
#
# Tout passe par doppler run -- pour injecter les secrets.

ACTION="$(doppler run --project conform-rgaa --config dev -- python3 - <<'PY'
import os, psycopg, sys
sys.path.insert(0, 'scripts')
from _db import database_url
with psycopg.connect(database_url()) as conn, conn.cursor() as cur:
    cur.execute("""
        SELECT count(*) FROM mairies
        WHERE contacted_at >= date_trunc('day', now() at time zone 'UTC')
    """)
    sent_today = cur.fetchone()[0]
    cur.execute("""
        SELECT count(*) FROM mairies
        WHERE email IS NOT NULL
          AND rgaa_status IN ('non_conforme','partiellement')
          AND contacted_at IS NULL AND unsubscribed_at IS NULL
    """)
    pool = cur.fetchone()[0]
    cur.execute("""
        SELECT count(*) FROM mairies
        WHERE site_url IS NOT NULL AND scraped_rgaa_at IS NULL
    """)
    scrape_pool = cur.fetchone()[0]

if sent_today < 10 and pool > 0 and not os.path.exists('PAUSE.email.flag'):
    print('send_email')
elif scrape_pool > 0:
    print('scrape_rgaa')
else:
    print('idle')
PY
)"

LOG="logs/run.log"
TS="$(date -u +%FT%TZ)"

case "$ACTION" in
    send_email)
        echo "[$TS] action=send_email" >> "$LOG"
        doppler run --project conform-rgaa --config dev -- python3 scripts/send_email.py >> "$LOG" 2>&1 || \
            echo "[$TS] send_email FAILED" >> "$LOG"
        ;;
    scrape_rgaa)
        echo "[$TS] action=scrape_rgaa" >> "$LOG"
        doppler run --project conform-rgaa --config dev -- python3 scripts/scrape_rgaa.py --batch 20 >> "$LOG" 2>&1 || \
            echo "[$TS] scrape_rgaa FAILED" >> "$LOG"
        ;;
    idle)
        echo "[$TS] action=idle (rien à faire)" >> "$LOG"
        ;;
    *)
        echo "[$TS] action=unknown ($ACTION)" >> "$LOG"
        ;;
esac
