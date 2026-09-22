#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

cp -n .env.example .env 2>/dev/null || true
cp -n .env.example backend/.env 2>/dev/null || true

docker compose up -d
echo "Aguardando Postgres..."
sleep 3

cd backend
if [[ ! -d .venv ]]; then
  python3 -m venv .venv
  # shellcheck disable=SC1091
  source .venv/bin/activate
  pip install -r requirements.txt
else
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

alembic upgrade head
python -m app.seed

echo ""
echo "OK. Em terminais separados:"
echo "  make api     # http://127.0.0.1:8002/docs"
echo "  make front   # http://localhost:5175"
echo ""
echo "Login: admin@oficina-alfa.com / senha123 / tenant oficina-alfa"
