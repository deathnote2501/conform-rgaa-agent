#!/usr/bin/env python3
"""send_email.py — envoie 1 email de prospection via Resend.

Pipeline :
  1. Vérifie PAUSE.flag / PAUSE.email.flag → exit si présent
  2. Lit le template mail.md (subject = ligne `# Subject:`, body = reste)
  3. Sélectionne 1 mairie (via --code-insee OU pool auto) :
       - email IS NOT NULL
       - rgaa_status IN ('non_conforme','partiellement')
       - contacted_at IS NULL
       - unsubscribed_at IS NULL
  4. Vérifie cap 10/jour UTC (refus exit 1 si dépassé)
  5. Render placeholders : {{nom}}, {{rgaa_page_url}}, {{rgaa_status_human}}
  6. POST Resend API → marque contacted_at + last_msg_id
  7. Append memory/contact_log.md

Usage : python3 scripts/send_email.py [--code-insee XXXXX] [--template mail.md] [--dry-run]

Env requis : RESEND_API_KEY, RESEND_FROM_EMAIL, RESEND_REPLY_TO,
             DATABASE_URL ou (SUPABASE_DB_PASSWORD + SUPABASE_PROJECT_REF).
"""
import os, sys, json, argparse, urllib.request, datetime, pathlib
import psycopg
from _db import database_url
from _action_token import claim_or_exit

REPO = pathlib.Path(__file__).resolve().parent.parent
PAUSE = REPO / 'PAUSE.flag'
PAUSE_EMAIL = REPO / 'PAUSE.email.flag'
CONTACT_LOG = REPO / 'memory' / 'contact_log.md'
DAILY_CAP = 10

STATUS_HUMAN = {
    'non_conforme': 'non conforme',
    'partiellement': 'partiellement conforme',
    'totalement': 'totalement conforme',
}


def refuse(msg, code=1):
    sys.stderr.write(f'REFUSED: {msg}\n')
    sys.exit(code)


def parse_template(path):
    text = pathlib.Path(path).read_text(encoding='utf-8')
    subject = None
    body_lines = []
    for line in text.splitlines():
        if subject is None and line.lower().startswith('# subject:'):
            subject = line.split(':', 1)[1].strip()
            continue
        body_lines.append(line)
    if not subject:
        refuse(f'template {path} sans `# Subject:` en première ligne')
    body = '\n'.join(body_lines).strip() + '\n'
    return subject, body


def render(text, m):
    return (text
            .replace('{{nom}}', m['nom'])
            .replace('{{rgaa_status_human}}', STATUS_HUMAN.get(m['rgaa_status'], m['rgaa_status'] or ''))
            .replace('{{rgaa_page_url}}', m['rgaa_page_url'] or m['site_url'] or ''))


def pick_target(cur, code_insee=None):
    if code_insee:
        cur.execute("""
            SELECT code_insee, nom, email, site_url, rgaa_status, rgaa_page_url
            FROM mairies WHERE code_insee=%s
        """, (code_insee,))
        row = cur.fetchone()
        if not row:
            refuse(f'code_insee {code_insee} introuvable')
        return row
    cur.execute("""
        SELECT code_insee, nom, email, site_url, rgaa_status, rgaa_page_url
        FROM mairies
        WHERE email IS NOT NULL
          AND rgaa_status IN ('non_conforme','partiellement')
          AND contacted_at IS NULL
          AND unsubscribed_at IS NULL
        ORDER BY rgaa_status, code_insee
        LIMIT 1
    """)
    row = cur.fetchone()
    if not row:
        refuse('aucune mairie éligible (pool épuisé)')
    return row


def check_cap(cur):
    cur.execute("""
        SELECT count(*) FROM mairies
        WHERE contacted_at >= date_trunc('day', now() at time zone 'UTC')
    """)
    n = cur.fetchone()[0]
    if n >= DAILY_CAP:
        refuse(f'cap {DAILY_CAP}/jour atteint ({n} envoyés depuis 00:00Z)')
    return n


def post_resend(api_key, from_addr, reply_to, to_addr, subject, body):
    payload = {
        'from': from_addr,
        'to': [to_addr],
        'reply_to': reply_to,
        'subject': subject,
        'text': body,
    }
    req = urllib.request.Request(
        'https://api.resend.com/emails',
        data=json.dumps(payload).encode('utf-8'),
        headers={
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
        },
        method='POST',
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--code-insee', help='cible précise (override pool)')
    ap.add_argument('--template', default=str(REPO / 'mail.md'))
    ap.add_argument('--dry-run', action='store_true', help='render + select sans envoyer')
    args = ap.parse_args()
    claim_or_exit()

    if PAUSE.exists(): refuse(f'PAUSE.flag présent ({PAUSE})')
    if PAUSE_EMAIL.exists(): refuse(f'PAUSE.email.flag présent ({PAUSE_EMAIL})')

    api_key = os.environ['RESEND_API_KEY']
    from_addr = os.environ['RESEND_FROM_EMAIL']
    reply_to = os.environ['RESEND_REPLY_TO']

    subject_tpl, body_tpl = parse_template(args.template)

    with psycopg.connect(database_url(), autocommit=False) as conn:
        with conn.cursor() as cur:
            sent_today = check_cap(cur)
            row = pick_target(cur, args.code_insee)
            keys = ['code_insee', 'nom', 'email', 'site_url', 'rgaa_status', 'rgaa_page_url']
            m = dict(zip(keys, row))

            if m['rgaa_status'] not in ('non_conforme', 'partiellement') and not args.code_insee:
                refuse(f'rgaa_status={m["rgaa_status"]!r} hors cible')

            subject = render(subject_tpl, m)
            body = render(body_tpl, m)

            print(f'--- TARGET ---')
            print(f'  code_insee = {m["code_insee"]}')
            print(f'  nom        = {m["nom"]}')
            print(f'  email      = {m["email"]}')
            print(f'  rgaa       = {m["rgaa_status"]}  page={m["rgaa_page_url"]}')
            print(f'  cap        = {sent_today}/{DAILY_CAP} envoyés aujourd\'hui')
            print(f'--- SUBJECT ---\n{subject}')
            print(f'--- BODY ---\n{body}')

            if args.dry_run:
                print('\n[dry-run] aucun envoi.')
                return

            resp = post_resend(api_key, from_addr, reply_to, m['email'], subject, body)
            msg_id = resp.get('id')
            print(f'\n→ Resend OK : id={msg_id}')

            cur.execute("""
                UPDATE mairies
                SET contacted_at=now(), last_msg_id=%s, template_used=%s
                WHERE code_insee=%s
            """, (msg_id, os.path.basename(args.template), m['code_insee']))
            conn.commit()

    ts = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')
    CONTACT_LOG.parent.mkdir(parents=True, exist_ok=True)
    with CONTACT_LOG.open('a', encoding='utf-8') as f:
        f.write(f'[{ts}] code_insee={m["code_insee"]} nom={m["nom"]!r} email={m["email"]} rgaa={m["rgaa_status"]} msg_id={msg_id}\n')


if __name__ == '__main__':
    main()
