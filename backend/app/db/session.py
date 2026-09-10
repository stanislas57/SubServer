from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import settings


def _normalize_database_url(url: str) -> str:
    """Render (comme Heroku) expose ses URLs Postgres sous la forme
    `postgres://...`. SQLAlchemy 2.x ne connaît pas ce dialecte et lève
    NoSuchModuleError DES L'IMPORT de ce module : le process uvicorn meurt
    avant même d'ouvrir un port, ce qui se voit uniquement comme un "Exited
    with status 1" côté hébergeur. On normalise donc vers le driver
    réellement installé (psycopg2) plutôt que de dépendre du copier-coller
    exact de l'URL depuis le dashboard.
    """
    if url.startswith("postgres://"):
        return "postgresql+psycopg2://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg2://" + url[len("postgresql://") :]
    return url


DATABASE_URL = _normalize_database_url(settings.DATABASE_URL)

# pool_recycle : Render coupe les connexions Postgres inactives ; sans
# recyclage, la première requête après une période creuse échoue sur une
# connexion morte que pool_pre_ping seul ne suffit pas toujours à rattraper.
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
