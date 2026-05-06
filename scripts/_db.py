"""_db.py — connexion Supabase Postgres via DATABASE_URL ou variables Doppler."""
import os, urllib.parse


def database_url() -> str:
    """Retourne DATABASE_URL si set, sinon construit depuis SUPABASE_*."""
    url = os.environ.get('DATABASE_URL')
    if url:
        return url
    pw = os.environ['SUPABASE_DB_PASSWORD']
    ref = os.environ['SUPABASE_PROJECT_REF']
    return f'postgresql://postgres:{urllib.parse.quote(pw)}@db.{ref}.supabase.co:5432/postgres'
