#!/usr/bin/env bash
# BinOS PWA — yuklash papkasini yasab Railway'ga chiqaradi.
#
#   bash infra/pwa/deploy.sh <environment> <service>
#   masalan: bash infra/pwa/deploy.sh production savdoos-pwa
#
# ⚠️  DIRTY DARAXTDAN DEPLOY QILMAYDI. Bundle qaysi commit'dan yig'ilgani
#     isbotlanishi kerak, shu bois `git status` toza bo'lmasa TO'XTAYDI.
# ⚠️  Build'ni O'ZI qilmaydi (ataylab): build buyrug'i `README.md` da va CI'da
#     AYNAN bir xil. Bu skript faqat mavjud `apps/mobile/build/web` ni yuklaydi.
set -Eeuo pipefail

ENVIRONMENT="${1:?muhit kerak: production | staging}"
SERVICE="${2:?servis nomi kerak}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WEB="$ROOT/apps/mobile/build/web"

if [ -n "$(git -C "$ROOT" status --porcelain)" ]; then
  echo "TO'XTADI: ishchi daraxt toza emas — bundle qaysi commit'dan ekani isbotlanmaydi." >&2
  git -C "$ROOT" status --porcelain >&2
  exit 1
fi
SHA="$(git -C "$ROOT" rev-parse HEAD)"

for f in index.html sw.js pwa.js flutter_bootstrap.js main.dart.js binos-build-id.txt; do
  [ -f "$WEB/$f" ] || { echo "TO'XTADI: $WEB/$f yo'q — avval build + pwa_postbuild.mjs." >&2; exit 1; }
done
BUILD_ID="$(tr -d '[:space:]' < "$WEB/binos-build-id.txt")"
grep -q "\"buildId\": \"$BUILD_ID\"" "$WEB/sw.js" \
  || { echo "TO'XTADI: sw.js build ID bilan muhrlanmagan (pwa_postbuild.mjs yurgizilmagan)." >&2; exit 1; }

# Muhrlanmagan/staging bundle production'ga CHIQMASIN.
if [ "$ENVIRONMENT" = "production" ]; then
  for bad in savdoos-staging api.invalid localhost 127.0.0.1 STAGING; do
    if grep -rqF "$bad" "$WEB" --exclude='*.symbols' 2>/dev/null; then
      echo "TO'XTADI: production bundle ichida '$bad' topildi." >&2
      exit 1
    fi
  done
  grep -rqF 'savdoos-production.up.railway.app' "$WEB/main.dart.js" \
    || { echo "TO'XTADI: bundle production API bazasini o'z ichiga olmagan." >&2; exit 1; }
fi

UP="$(mktemp -d)"
trap 'rm -rf "$UP"' EXIT
cp "$ROOT/infra/pwa/Dockerfile" "$ROOT/infra/pwa/Caddyfile" "$UP/"
mkdir -p "$UP/web"
cp -R "$WEB/." "$UP/web/"

echo "manba SHA   : $SHA"
echo "build ID    : $BUILD_ID"
echo "muhit/servis: $ENVIRONMENT / $SERVICE"
cd "$UP"
railway up --ci --environment "$ENVIRONMENT" --service "$SERVICE"
