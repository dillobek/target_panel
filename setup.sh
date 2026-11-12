#!/usr/bin/env bash
# Targetpanel: .env yaratish va ishga tushirish. Serverda: bash setup.sh
set -euo pipefail
cd "$(dirname "$0")"

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker o'rnatilmoqda..."
  curl -fsSL https://get.docker.com | sh
fi

if [ ! -f .env ]; then
  read -rsp "Adminka uchun parol o'ylab toping: " ADMIN_PASSWORD; echo
  read -rp "Meta App Secret (webhook uchun, hozir bo'lmasa Enter): " META_APP_SECRET

  cat > .env <<EOF
DB_PASSWORD=$(openssl rand -hex 16)
JWT_SECRET=$(openssl rand -hex 32)
ENCRYPTION_KEY=$(openssl rand -base64 32)
ADMIN_PASSWORD=${ADMIN_PASSWORD}
META_API_VERSION=v26.0
META_APP_SECRET=${META_APP_SECRET}
META_WEBHOOK_VERIFY_TOKEN=$(openssl rand -hex 16)
TZ=Asia/Tashkent
EOF
  chmod 600 .env
  echo ".env yaratildi. ENCRYPTION_KEY ni yo'qotmang — usiz saqlangan tokenlar ochilmaydi."
fi

docker compose up -d --build
sleep 5
docker compose ps
echo
echo "Tayyor. Kompyuteringizda:  ssh -L 3000:localhost:3000 root@13.140.128.2"
echo "Keyin brauzerda oching:    http://localhost:3000"
echo "Adminka → Sozlamalar: bot tokeni, admin va AI kalitini shu yerda ulaysiz."
