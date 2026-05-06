-- 002_rgaa_in_footer.sql — track si la mention RGAA est dans le footer.
-- Idempotent.

ALTER TABLE mairies ADD COLUMN IF NOT EXISTS rgaa_in_footer boolean;

-- Reset des scrape déjà faits sans cette donnée → ils seront re-traités
-- par scrape_rgaa.py (51 lignes au moment de la migration, négligeable).
UPDATE mairies
   SET scraped_rgaa_at = NULL,
       rgaa_status = NULL,
       rgaa_page_url = NULL
 WHERE scraped_rgaa_at IS NOT NULL
   AND rgaa_in_footer IS NULL;
