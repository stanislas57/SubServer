#!/usr/bin/env bash
# Commande de démarrage du service backend (Render : Start Command = ./start.sh).
#
# Garde-fous volontaires :
#
# 1. `alembic upgrade head` NE bloque PAS le démarrage. Une migration qui
#    échoue (base injoignable, base expirée, verrou) sortirait en status 1 et
#    mettrait l'API entière hors ligne en boucle de crash, sans aucun endpoint
#    pour diagnostiquer. On loggue l'échec en évidence et on sert quand même :
#    GET /health répond, GET /health/db dit si la base est joignable.
#    -> Les migrations doivent donc rester ICI (start), JAMAIS dans le Build
#       Command de Render : un build qui touche la base retombe sur le même
#       "Build failed" opaque dès que la base a le moindre souci.
# 2. uvicorn écoute sur 0.0.0.0:$PORT. Un bind sur 127.0.0.1 ou un port en dur
#    rend le service invisible depuis le routeur de l'hébergeur.
set -u

PORT="${PORT:-8000}"

echo "[start] Application des migrations Alembic..."
if alembic upgrade head; then
  echo "[start] Migrations OK -- revision courante : $(alembic current 2>/dev/null | tail -1)"
  # Diagnostic non bloquant : schéma complet ? catalogue d'offres peuplé ?
  python -m scripts.verify_db || echo "[start] verify_db signale un souci (non bloquant, cf. ci-dessus)."
else
  echo "[start] ERREUR : migrations en échec -- l'API démarre quand même avec le schéma existant."
  echo "[start] Diagnostiquer : GET /health/db, puis les logs ci-dessus."
fi

echo "[start] Démarrage d'uvicorn sur 0.0.0.0:${PORT}..."
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT}"
