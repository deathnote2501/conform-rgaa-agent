#!/bin/bash
# status.sh — vue d'ensemble en 5 lignes.
set -euo pipefail
cd "$(dirname "$0")"

doppler run --project conform-rgaa --config dev -- python3 - <<'PY'
import sys
sys.path.insert(0, 'scripts')
import psycopg
from _db import database_url

with psycopg.connect(database_url()) as conn, conn.cursor() as cur:
    cur.execute("SELECT count(*) FROM mairies")
    total = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM mairies WHERE email IS NOT NULL")
    with_email = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM mairies WHERE site_url IS NOT NULL")
    with_site = cur.fetchone()[0]
    cur.execute("""
        SELECT rgaa_status, count(*) FROM mairies
        WHERE rgaa_status IS NOT NULL
        GROUP BY rgaa_status ORDER BY 2 DESC
    """)
    by_status = cur.fetchall()
    cur.execute("""
        SELECT count(*) FROM mairies
        WHERE site_url IS NOT NULL AND scraped_rgaa_at IS NULL
    """)
    scrape_pending = cur.fetchone()[0]
    cur.execute("""
        SELECT count(*) FROM mairies
        WHERE email IS NOT NULL
          AND rgaa_status IN ('non_conforme','partiellement')
          AND contacted_at IS NULL AND unsubscribed_at IS NULL
    """)
    send_pool = cur.fetchone()[0]
    cur.execute("""
        SELECT count(*) FROM mairies
        WHERE contacted_at >= date_trunc('day', now() at time zone 'UTC')
    """)
    sent_today = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM mairies WHERE contacted_at IS NOT NULL")
    contacted_total = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM mairies WHERE replied_at IS NOT NULL")
    replied = cur.fetchone()[0]

print(f'mairies        : {total} (email={with_email}, site={with_site})')
print(f'scrape pending : {scrape_pending}')
print('rgaa_status    :')
for s, n in by_status:
    print(f'  {s:18} {n}')
print(f'send_pool      : {send_pool}  (non_conforme + partiellement, non contactés)')
print(f'sent today UTC : {sent_today}/10')
print(f'contacted tot  : {contacted_total}  | replied : {replied}')
PY
