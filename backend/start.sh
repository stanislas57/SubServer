#!/usr/bin/env bash
# Commande de démarrage du service backend (Render : Start Command = ./start.sh).
#
# Deux garde-fous volontaires ici :
#
# 1. `alembic upgrade head` NE bloque PAS le démarrage. Une migration qui
#    échoue (base injoignable, base free tier expirée, verrou) sortirait en
#    status 1 et mettrait l'API entière hors ligne en boucle de crash, sans
#    aucun endpoint pour diagnostiquer. On loggue l'échec en évidence et on
#    sert quand même : GET /health répond, GET /health/db dit précisément si
#    la base est joignable.
# 2. uvicorn écoute sur 0.0.0.0:$PORT. Un bind sur 127.0.0.1 ou sur un port
#    en dur rend le service invisible depuis le routeur de l'hébergeur.
set -u

PORT="${PORT:-8000}"

echo "[start] Application des migrations Alembic..."
if alembic upgrade head; then
  echo "[start] Migrations OK."
else
  echo "[start] ERREUR : migrations en échec -- l'API démarre quand même avec le schéma existant."
  echo "[start] Diagnostiquer avec : GET /health/db"
fi

echo "[start] Démarrage d'uvicorn sur 0.0.0.0:${PORT}..."
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT}"
