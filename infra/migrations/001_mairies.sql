-- 001_mairies.sql — table mairies (Supabase Postgres)
-- Idempotent. Ingestée depuis api-lannuaire.service-public.fr,
-- enrichie par scrape_rgaa, consommée par send_email.

CREATE TABLE IF NOT EXISTS mairies (
    code_insee       text PRIMARY KEY,
    nom              text NOT NULL,
    email            text,
    site_url         text,
    source           text NOT NULL DEFAULT 'api-lannuaire',
    ingested_at      timestamptz NOT NULL DEFAULT now(),

    -- scrape RGAA (footer mention accessibilité)
    rgaa_status      text CHECK (rgaa_status IN ('non_conforme','partiellement','totalement','aucune_mention','fetch_error')),
    rgaa_page_url    text,
    scraped_rgaa_at  timestamptz,

    -- envoi email (Resend)
    contacted_at     timestamptz,
    last_msg_id      text,
    template_used    text,
    bounced_at       timestamptz,
    replied_at       timestamptz,
    unsubscribed_at  timestamptz
);

CREATE INDEX IF NOT EXISTS mairies_rgaa_status_idx  ON mairies(rgaa_status);
CREATE INDEX IF NOT EXISTS mairies_contactable_idx  ON mairies(contacted_at)
    WHERE email IS NOT NULL AND rgaa_status IN ('non_conforme','partiellement');
CREATE INDEX IF NOT EXISTS mairies_scrape_pending_idx ON mairies(scraped_rgaa_at)
    WHERE site_url IS NOT NULL AND scraped_rgaa_at IS NULL;
