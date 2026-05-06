#!/usr/bin/env python3
"""scrape_rgaa.py — détecte la mention RGAA sur le site d'une mairie.

Pour chaque mairie où site_url IS NOT NULL AND scraped_rgaa_at IS NULL :
  1. Fetch homepage (urllib, SSL relax car certs publics souvent buggés)
  2. Extrait la portion footer (balise <footer>, ou class/id contenant 'footer',
     sinon les 8000 derniers chars de l'HTML)
  3. Cherche `Accessibilité : <statut>` ou `Conformité RGAA : <statut>` :
       - d'abord dans le footer → si trouvé, rgaa_in_footer=true (signal RGAA légal)
       - sinon dans tout le texte de la home (en mode dégradé, rgaa_in_footer=false)
  4. Cherche les <a> dont href/texte contient 'accessibilit' (dans tout l'HTML)
  5. Suit le meilleur lien (max 2) → si statut trouvé sur la page liée,
     rgaa_in_footer reste false (mention seulement sur la page dédiée).
  6. Sinon teste paths /accessibilite, /accessibilite-numerique, /declaration-accessibilite
  7. Update mairies.rgaa_status + rgaa_page_url + rgaa_in_footer + scraped_rgaa_at

Statuts : non_conforme, partiellement, totalement, aucune_mention, fetch_error.
rgaa_in_footer : true si la mention `Accessibilité : <statut>` est dans le footer
                 de la home, false si trouvée ailleurs ou pas trouvée du tout.

Usage : python3 scripts/scrape_rgaa.py [--batch N]   (défaut N=20)

Env requis : DATABASE_URL ou (SUPABASE_DB_PASSWORD + SUPABASE_PROJECT_REF).
"""
import os, sys, re, ssl, time, argparse, urllib.parse, urllib.request, html as html_mod
import psycopg
from _db import database_url
from _action_token import claim_or_exit

USER_AGENT = 'Mozilla/5.0 (X11; Linux x86_64) conform-rgaa-agent/0.1'
TIMEOUT = 10
SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

PAT_NON  = re.compile(r'(?:accessibilit[eé]|conformit[eé](?:[\s\xa0]+rgaa)?)[\s\xa0:\-]+(?:non[\s \-]+conforme|non[\s \-]+conformit[eé])', re.I)
PAT_PART = re.compile(r'(?:accessibilit[eé]|conformit[eé](?:[\s\xa0]+rgaa)?)[\s\xa0:\-]+(?:partiellement[\s \-]+conforme|partielle\b)', re.I)
PAT_TOT  = re.compile(r'(?:accessibilit[eé]|conformit[eé](?:[\s\xa0]+rgaa)?)[\s\xa0:\-]+(?:totalement[\s \-]+conforme|totale\b)', re.I)

A11Y_PATHS = [
    '/accessibilite', '/accessibilite-numerique',
    '/declaration-accessibilite', '/declaration-d-accessibilite',
    '/mentions-legales',
]
MAX_FETCHES_PER_SITE = 4


def safe_url(url):
    try:
        p = urllib.parse.urlsplit(url)
        return urllib.parse.urlunsplit((
            p.scheme, p.netloc,
            urllib.parse.quote(p.path, safe='/%:@'),
            urllib.parse.quote(p.query, safe='=&%:@/'),
            p.fragment,
        ))
    except Exception:
        return url


def fetch(url):
    req = urllib.request.Request(safe_url(url), headers={'User-Agent': USER_AGENT})
    with urllib.request.urlopen(req, timeout=TIMEOUT, context=SSL_CTX) as r:
        raw = r.read(800_000)
        ctype = r.headers.get('Content-Type', '').lower()
        enc = ctype.split('charset=')[-1].split(';')[0].strip() if 'charset=' in ctype else 'utf-8'
        return r.geturl(), raw.decode(enc, errors='ignore')


def text_only(html):
    h = re.sub(r'<script[^>]*>.*?</script>', ' ', html, flags=re.I | re.S)
    h = re.sub(r'<style[^>]*>.*?</style>', ' ', h, flags=re.I | re.S)
    h = html_mod.unescape(re.sub(r'<[^>]+>', ' ', h))
    return re.sub(r'\s+', ' ', h)


def extract_footer_html(html):
    """Isole le footer : <footer>, ou class/id contenant 'footer', sinon
    les 8000 derniers chars (les footers sont en bas de page)."""
    lower = html.lower()
    # 1. Dernière balise HTML5 <footer>...
    pos = lower.rfind('<footer')
    if pos >= 0:
        return html[pos:]
    # 2. Dernier élément avec class/id contenant 'footer'
    last = -1
    for m in re.finditer(r'(?:class|id)\s*=\s*["\'][^"\']*\bfooter\b', lower):
        last = m.start()
    if last >= 0:
        # remonte au début de la balise ouvrante
        tag_start = lower.rfind('<', 0, last)
        return html[max(0, tag_start):]
    # 3. Fallback : derniers 8000 chars
    return html[-8000:] if len(html) > 8000 else html


def detect_status(text):
    if PAT_NON.search(text):  return 'non_conforme'
    if PAT_PART.search(text): return 'partiellement'
    if PAT_TOT.search(text):  return 'totalement'
    return None


def find_a11y_links(html, base_url):
    """Tous les <a> avec 'accessibilit' dans href ou texte. Trie par pertinence."""
    out = []
    for m in re.finditer(r'<a\b([^>]+)>(.*?)</a>', html, re.I | re.S):
        attrs = m.group(1)
        text = html_mod.unescape(re.sub(r'<[^>]+>', '', m.group(2))).strip()
        href_match = re.search(r'href=["\']([^"\']+)["\']', attrs, re.I)
        if not href_match:
            continue
        href = href_match.group(1).strip()
        if not href or href.startswith(('javascript:', 'mailto:', 'tel:')):
            continue
        if 'accessibilit' not in (text + ' ' + href).lower():
            continue
        full = urllib.parse.urljoin(base_url, href).split('#')[0]
        # score : préfère hrefs courts contenant /accessibilite (vs /actualites/...)
        path = urllib.parse.urlsplit(full).path.lower()
        score = 0
        if re.search(r'/accessibilit[eé][a-z\-]*/?$', path): score += 10
        if 'declaration' in path: score += 3
        if 'actualit' in path or 'news' in path: score -= 5
        if 'rgaa' in path: score += 2
        out.append((score, text, full))
    out.sort(key=lambda x: -x[0])
    # déduplique par URL
    seen, dedup = set(), []
    for s, t, u in out:
        if u in seen: continue
        seen.add(u); dedup.append((s, t, u))
    return dedup


def scrape_one(site_url):
    """Retourne (status, page_url, in_footer, note)."""
    fetches = 0
    try:
        final_url, html = fetch(site_url)
        fetches += 1
    except Exception as e:
        return ('fetch_error', None, False, f'home fetch: {e}')

    # Détection ciblée footer puis fallback texte complet
    footer_html = extract_footer_html(html)
    footer_text = text_only(footer_html)
    full_text = text_only(html)
    footer_status = detect_status(footer_text)
    home_status = detect_status(full_text)

    links = find_a11y_links(html, final_url)
    best_link_url = links[0][2] if links else None

    # 1. statut détecté DANS le footer (le bon endroit légalement)
    if footer_status:
        return (footer_status, best_link_url, True, 'footer')
    # 2. statut détecté ailleurs sur la home (mention présente mais pas en footer)
    if home_status:
        return (home_status, best_link_url, False, 'home_outside_footer')

    # 3. suivre le meilleur lien a11y (max 2)
    for _, _, url in links[:2]:
        if fetches >= MAX_FETCHES_PER_SITE: break
        try:
            _, h2 = fetch(url)
            fetches += 1
            s = detect_status(text_only(h2))
            if s:
                return (s, url, False, 'via_link')
        except Exception:
            continue

    # 4. fallback paths conventionnels
    base = urllib.parse.urlsplit(final_url)
    base_root = f'{base.scheme}://{base.netloc}'
    for p in A11Y_PATHS:
        if fetches >= MAX_FETCHES_PER_SITE: break
        cand = base_root + p
        try:
            _, h2 = fetch(cand)
            fetches += 1
            s = detect_status(text_only(h2))
            if s:
                return (s, cand, False, 'fallback_path')
        except Exception:
            continue

    return ('aucune_mention', None, False, f'links={len(links)}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--batch', type=int, default=20)
    args = ap.parse_args()
    claim_or_exit()

    counts = {'non_conforme': 0, 'partiellement': 0, 'totalement': 0,
              'aucune_mention': 0, 'fetch_error': 0}

    with psycopg.connect(database_url(), autocommit=False) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT code_insee, nom, site_url
                FROM mairies
                WHERE site_url IS NOT NULL AND scraped_rgaa_at IS NULL
                ORDER BY code_insee
                LIMIT %s
            """, (args.batch,))
            rows = cur.fetchall()
            print(f'Picked {len(rows)} mairies à scraper')

            for code, nom, site in rows:
                print(f'\n[{code}] {nom!r}  → {site}')
                try:
                    status, page_url, in_footer, note = scrape_one(site)
                except Exception as e:
                    status, page_url, in_footer, note = 'fetch_error', None, False, f'{type(e).__name__}: {e}'
                counts[status] = counts.get(status, 0) + 1
                footer_mark = '✓footer' if in_footer else '—'
                print(f'  status={status}  in_footer={footer_mark}  page={page_url}  ({note})')
                cur.execute("""
                    UPDATE mairies
                    SET rgaa_status=%s, rgaa_page_url=%s, rgaa_in_footer=%s, scraped_rgaa_at=now()
                    WHERE code_insee=%s
                """, (status, page_url, in_footer, code))
                conn.commit()
                time.sleep(0.5)

    print(f'\n=== batch done : {counts} ===')


if __name__ == '__main__':
    main()
