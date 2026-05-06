#!/usr/bin/env python3
"""ingest_api.py — ingère les mairies depuis api-lannuaire.service-public.fr.

Utilise l'endpoint `/exports/json` (pas de cap offset+limit ≤ 10000 comme
sur `/records`). Upsert dans Supabase `mairies` par batch de 500.

Splitte les emails multiples (séparés par `;`) → garde le 1er email avec
domaine "propre" (domaine commune.fr) sinon le 1er tout court. Site_url =
1ère URL du champ JSON `site_internet`.

Usage : python3 scripts/ingest_api.py [--limit N]
        --limit 0 (défaut) = tout (~35 857 entrées 'mairie')

Env requis : DATABASE_URL ou (SUPABASE_DB_PASSWORD + SUPABASE_PROJECT_REF).
"""
import os, sys, json, time, argparse, urllib.parse, urllib.request
import psycopg
from _db import database_url
from _action_token import claim_or_exit

EXPORT_URL = 'https://api-lannuaire.service-public.fr/api/explore/v2.1/catalog/datasets/api-lannuaire-administration/exports/json'
WHERE = 'pivot like "%mairie%"'
SELECT = 'id,nom,adresse_courriel,site_internet,code_insee_commune'
BATCH = 500
USER_AGENT = 'conform-rgaa-agent/0.1'
GENERIC_HOSTS = {
    'wanadoo.fr', 'orange.fr', 'free.fr', 'sfr.fr', 'gmail.com',
    'outlook.com', 'outlook.fr', 'hotmail.fr', 'hotmail.com',
    'yahoo.fr', 'yahoo.com', 'laposte.net', 'aol.com', 'live.fr',
}


def fetch_all():
    """Pull tout le dataset filtré via /exports/json (pas de pagination)."""
    qs = urllib.parse.urlencode({
        'where': WHERE,
        'select': SELECT,
        'limit': -1,
    })
    req = urllib.request.Request(f'{EXPORT_URL}?{qs}', headers={'User-Agent': USER_AGENT})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())


def pick_email(raw):
    """Splitte sur ';', priorise un domaine non-générique."""
    if not raw:
        return None
    parts = [e.strip().lower() for e in raw.split(';') if e.strip() and '@' in e]
    if not parts:
        return None
    for e in parts:
        host = e.partition('@')[2]
        if host not in GENERIC_HOSTS:
            return e
    return parts[0]


def pick_site(raw):
    """site_internet est une chaîne JSON [{libelle, valeur}, ...]."""
    if not raw:
        return None
    try:
        arr = json.loads(raw)
    except Exception:
        return None
    for item in arr:
        v = (item.get('valeur') or '').strip()
        if v.startswith('http'):
            return v.rstrip('/')
    return None


def parse_code_insee(raw_id, fallback):
    if fallback:
        return fallback
    return None


def upsert_batch(cur, rows):
    if not rows:
        return 0
    cur.executemany(
        """
        INSERT INTO mairies (code_insee, nom, email, site_url, source, ingested_at)
        VALUES (%s, %s, %s, %s, 'api-lannuaire', now())
        ON CONFLICT (code_insee) DO UPDATE SET
            nom = EXCLUDED.nom,
            email = EXCLUDED.email,
            site_url = EXCLUDED.site_url,
            ingested_at = now()
        """,
        rows,
    )
    return len(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--limit', type=int, default=0, help='0=tout')
    args = ap.parse_args()
    claim_or_exit()

    print('Fetching full export from api-lannuaire...')
    records = fetch_all()
    print(f'Got {len(records)} records, building rows...')

    seen_codes = set()
    skipped_no_insee = 0
    rows = []
    for r in records:
        code = r.get('code_insee_commune')
        if not code:
            skipped_no_insee += 1
            continue
        if code in seen_codes:
            continue
        seen_codes.add(code)
        rows.append((
            code,
            r.get('nom') or '',
            pick_email(r.get('adresse_courriel')),
            pick_site(r.get('site_internet')),
        ))
        if args.limit and len(rows) >= args.limit:
            break
    print(f'Built {len(rows)} unique rows (skipped_no_insee={skipped_no_insee}, dedup={len(records) - len(rows) - skipped_no_insee})')

    total_upserted = 0
    with psycopg.connect(database_url(), autocommit=False) as conn:
        with conn.cursor() as cur:
            for i in range(0, len(rows), BATCH):
                chunk = rows[i:i + BATCH]
                total_upserted += upsert_batch(cur, chunk)
                conn.commit()
                print(f'upserted {total_upserted}/{len(rows)}')
    print(f'\n=== done : upserted={total_upserted} skip_no_insee={skipped_no_insee} ===')


if __name__ == '__main__':
    main()
