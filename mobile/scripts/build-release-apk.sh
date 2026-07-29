#!/usr/bin/env bash
# Recompila el APK de release de DAO Ciudadana y lo copia al Escritorio.
# Uso: bash mobile/scripts/build-release-apk.sh
set -euo pipefail

REPO="$HOME/.gemini/antigravity/scratch/DAO-Ciudadano"
MOBILE_DIR="$REPO/mobile"
OUT_APK="$MOBILE_DIR/android/app/build/outputs/apk/release/app-release.apk"
DEST="$HOME/Desktop/DAO-Ciudadano-Release.apk"

echo "==> Actualizando repo"
cd "$REPO"
git pull --ff-only origin main

echo "==> Instalando dependencias de mobile (con el fix de MetaMask ya aplicado)"
cd "$MOBILE_DIR"
npm install

echo "==> Limpiando build anterior (importante: había quedado compilado con newArchEnabled=false)"
cd android
./gradlew clean

echo "==> Compilando release (puede tardar varios minutos la primera vez)"
./gradlew assembleRelease

if [ ! -f "$OUT_APK" ]; then
  echo "ERROR: no se generó $OUT_APK. Revisa el log de arriba." >&2
  exit 1
fi

cp "$OUT_APK" "$DEST"
echo ""
echo "✅ Listo: $DEST"
