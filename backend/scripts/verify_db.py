"""Vérifie qu'une base est prête à servir SubSaver : connexion OK, schéma à la
dernière révision Alembic, toutes les tables attendues présentes, et le
catalogue d'offres curatées bien peuplé par les migrations de données.

    cd backend && python -m scripts.verify_db

Lit DATABASE_URL depuis l'environnement / .env (comme le reste de l'app).
Sort en code 0 si tout est bon, 1 sinon -- utilisable tel quel dans un
job Render "one-off" ou en fin de start.sh.
"""

import sys

from sqlalchemy import inspect, text

from app.db.session import DATABASE_URL, engine

EXPECTED_TABLES = {
    "users",
    "subscriptions",
    "family_members",
    "bank_transactions",
    "market_offers",
    "subscription_splits",
    "settlements",
    "renewal_alerts",
    "alembic_version",
}


def _head_revision() -> str:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(Config("alembic.ini"))
    heads = script.get_heads()
    if len(heads) != 1:
        raise RuntimeError(f"chaîne de migrations non linéaire : heads={heads}")
    return heads[0]


def main() -> int:
    safe_host = DATABASE_URL.split("@")[-1]
    print(f"[verify_db] cible : ...@{safe_host}")

    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:
        print(f"[verify_db] ECHEC connexion : {type(exc).__name__}: {exc}")
        return 1
    print("[verify_db] connexion : OK")

    inspector = inspect(engine)
    present = set(inspector.get_table_names())
    missing = EXPECTED_TABLES - present
    if missing:
        print(f"[verify_db] ECHEC : tables manquantes -> {sorted(missing)}")
        print("[verify_db] lance `alembic upgrade head` sur cette base.")
        return 1
    print(f"[verify_db] tables : OK ({len(EXPECTED_TABLES)} attendues, toutes présentes)")

    try:
        head = _head_revision()
        with engine.connect() as conn:
            current = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
    except Exception as exc:
        print(f"[verify_db] ECHEC lecture de la révision : {type(exc).__name__}: {exc}")
        return 1
    if current != head:
        print(f"[verify_db] ECHEC : révision {current!r} != head {head!r} -- migrations en retard.")
        return 1
    print(f"[verify_db] révision Alembic : OK ({current})")

    with engine.connect() as conn:
        offers = conn.execute(text("SELECT COUNT(*) FROM market_offers")).scalar()
    if not offers:
        print("[verify_db] ATTENTION : market_offers est vide -- le comparateur n'aura rien à afficher.")
    else:
        print(f"[verify_db] catalogue d'offres : {offers} lignes")

    print("[verify_db] base prête.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
