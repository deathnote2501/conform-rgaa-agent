# conform-rgaa-agent

Agent autonome qui contacte 10 mairies par jour pour proposer un accompagnement
RGAA (audit / mise en conformité accessibilité numérique). Cible exclusive :
mairies dont le site web déclare publiquement un statut `non conforme` ou
`partiellement conforme` au RGAA.

Source emails : api-lannuaire.service-public.fr (98.9% des 35 857 mairies
exposent déjà leur email officiel via cette API publique Etalab).
Envoi : Resend depuis `bonjour@rgaa-ia.fr`.
Réponses : redirection OVH `bonjour@rgaa-ia.fr` → Gmail (filtre + label gérés
côté Gmail par Jérôme).

## Pipeline

```
INGEST (1×/sem, lundi 03h UTC)
  api-lannuaire → mairies (code_insee, nom, email, site_url)
                    ~35 462 emails déjà en API, ~276 sans email mais avec site

SCRAPE RGAA (continu, batch 20)
  pour chaque mairie avec site_url et rgaa_status NULL :
    fetch homepage → cherche statut "Accessibilité : non/partiellement/totalement conforme"
    + lien vers page de déclaration → store status + page_url

SEND EMAIL (cap 10/jour UTC)
  pool : email IS NOT NULL
       AND rgaa_status IN ('non_conforme','partiellement')
       AND contacted_at IS NULL
  → render mail.md → POST Resend → update contacted_at
```

## Commandes utiles

```bash
# Voir l'état
bash status.sh

# Pauser les envois (scrape continue)
touch PAUSE.email.flag

# Tout pauser
touch PAUSE.flag

# Test envoi sans rien envoyer (render + select uniquement)
doppler run -- python3 scripts/send_email.py --dry-run

# Envoi forcé sur une commune précise
doppler run -- python3 scripts/send_email.py --code-insee 63113

# Scrape ad-hoc
doppler run -- python3 scripts/scrape_rgaa.py --batch 50

# Re-ingest API manuellement
doppler run -- python3 scripts/ingest_api.py
```

## Setup initial

1. Doppler : `doppler setup --project conform-rgaa --config dev` dans ce dossier
2. Migration : `doppler run -- psql "$DATABASE_URL" < infra/migrations/001_mairies.sql`
   (ou via Supabase Studio si pas de psql direct)
3. Cron : `crontab -u agent infra/crontab.txt`
4. Filtre Gmail (manuel UI) : `to:bonjour@rgaa-ia.fr` → label de ton choix

## Templates

`mail.md` au root du projet. Format :
```
# Subject: <ligne sujet>

<corps de l'email>
```

Placeholders disponibles : `{{nom}}`, `{{rgaa_status_human}}`, `{{rgaa_page_url}}`.
Modifier le fichier suffit, aucun redéploiement.

## Stack

- Python 3.12 (`psycopg`), pas de framework
- Postgres = Supabase (project conform-rgaa)
- Email = Resend API
- Secrets = Doppler (project conform-rgaa, config dev)
- Cron unique sur agent@VPS

## Inspirations

Pattern "1 action par run" + cap journalier + PAUSE.flag empruntés à
`/opt/vps-acquire`. Pas d'auto-reply ici (Jérôme répond manuellement).
