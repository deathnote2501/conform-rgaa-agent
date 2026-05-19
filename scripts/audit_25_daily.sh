#!/bin/bash
# audit_25_daily.sh — exécute 25 audits RGAA 44 critères via le worker rgaa-ia.fr.
# Cron : 4×/jour 6h, 10h, 14h, 18h UTC → ~100 audits/jour.
#
# Pourquoi un wrapper ? audit-mairies.mjs sélectionne mal au-delà de ~75 mairies
# déjà auditées (over-fetch limit*3, hardcodé). On pré-pioche 25 code_insees
# non encore audités côté DB, et on appelle audit-mairies.mjs --code-insee X
# pour chacun. Coût : 1 chromium boot par audit (~3-5s d'overhead).

cd /opt/conform-rgaa-agent
LOG="/opt/conform-rgaa-agent/logs/audit.log"
mkdir -p /opt/conform-rgaa-agent/logs

ts() { date -u +%FT%TZ; }
echo "[$(ts)] === audit_25_daily.sh start ===" >> "$LOG"

INSEES=$(doppler run --project conform-rgaa --config dev -- python3 -c "
import sys; sys.path.insert(0, 'scripts')
from _db import database_url
import psycopg
with psycopg.connect(database_url()) as conn, conn.cursor() as cur:
    cur.execute('''
        SELECT code_insee FROM mairies
        WHERE site_url IS NOT NULL
          AND code_insee NOT IN (SELECT code_insee FROM mairie_audits WHERE campaign=%s)
        ORDER BY code_insee LIMIT 25
    ''', ('2026',))
    for r in cur.fetchall(): print(r[0])
")

if [ -z "$INSEES" ]; then
    echo "[$(ts)] aucune mairie à auditer (pool épuisé pour campaign 2026)" >> "$LOG"
    exit 0
fi

cd /opt/rgaa
for INSEE in $INSEES; do
    echo "[$(ts)]   audit $INSEE…" >> "$LOG"
    if doppler run --project conform-rgaa --config dev -- node worker/scripts/audit-mairies.mjs --campaign 2026 --code-insee "$INSEE" >> "$LOG" 2>&1; then
        echo "[$(ts)]   $INSEE OK" >> "$LOG"
    else
        echo "[$(ts)]   $INSEE FAILED (continuing)" >> "$LOG"
    fi
done

echo "[$(ts)] === audit_25_daily.sh done ===" >> "$LOG"
