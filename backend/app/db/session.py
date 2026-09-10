from urllib.parse import parse_qs, urlparse, urlunparse

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import settings

# Hôtes qui EXIGENT du TLS et refusent une connexion sans `sslmode` explicite
# (Neon, Supabase, la plupart des Postgres managés hors réseau interne). On
# ajoute alors `sslmode=require` à la volée pour qu'une URL copiée un peu vite
# depuis le dashboard fonctionne quand même -- plutôt qu'un "connection closed"
# opaque au premier appel.
_SSL_REQUIRED_HOST_MARKERS = ("neon.tech", "supabase.co", "supabase.com", "render.com")


def _normalize_database_url(url: str) -> str:
    """Rend l'URL de base utilisable telle qu'elle sort d'un dashboard, sans
    supposer un format exact.

    1. `postgres://` / `postgresql://` -> `postgresql+psycopg2://`.
       SQLAlchemy 2.x ne connaît pas le dialecte nu `postgres` et lève
       NoSuchModuleError DES L'IMPORT de ce module : le process meurt avant
       d'ouvrir un port, ce qui ne se voit que comme un "Exited with status 1".
    2. Ajoute `sslmode=require` si l'hôte l'impose (cf. _SSL_REQUIRED_HOST_MARKERS)
       et qu'il est absent -- Neon en particulier ferme la connexion sinon.
    Idempotent : une URL déjà au bon format (`postgresql+psycopg2://...` avec
    `sslmode`) ressort inchangée.
    """
    if url.startswith("postgres://"):
        url = "postgresql+psycopg2://" + url[len("postgres://") :]
    elif url.startswith("postgresql://"):
        url = "postgresql+psycopg2://" + url[len("postgresql://") :]

    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    needs_ssl = any(marker in host for marker in _SSL_REQUIRED_HOST_MARKERS)
    if needs_ssl and "sslmode" not in parse_qs(parsed.query):
        sep = "&" if parsed.query else ""
        parsed = parsed._replace(query=f"{parsed.query}{sep}sslmode=require")
        url = urlunparse(parsed)

    return url


DATABASE_URL = _normalize_database_url(settings.DATABASE_URL)

# pool_pre_ping : Neon (comme Render) met la base en veille après quelques
# minutes d'inactivité et coupe les connexions ouvertes ; sans ping, la
# première requête après une période creuse échoue sur une connexion morte.
# pool_recycle : filet complémentaire, on ne garde jamais une connexion plus
# de 30 min.
engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_recycle=1800)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
