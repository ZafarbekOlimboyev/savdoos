#!/bin/bash
# BinOS Owner — iOS reliz darvozasi va takrorlanadigan qurilishi.
#
# NEGA BU SKRIPT BOR
#   Build 62 va 63 buyruq satridagi `--build-number` dan kelgan, repodan EMAS:
#   `pubspec.yaml` da 56 turardi, haqiqiy raqam esa gitignore qilingan
#   `ios/Flutter/Generated.xcconfig` da edi. Toza clone yoki CI qo'shimcha
#   bayroqsiz 56 ni ishlab chiqarardi — u esa App Store Connect'ga allaqachon
#   yuklangan, ya'ni Apple takroriy raqam deb rad etadi.
#
#   `BINOS_PRIVACY_URL` ham xuddi shunday: u ataylab STANDART QIYMATSIZ
#   compile-time define (qarang `lib/platform/env.dart`). Berilmasa ilova
#   Sozlamalarida maxfiylik havolasi KO'RINMAYDI — Apple Guideline 5.1.1
#   bo'yicha rad etadigan holat. Darvoza bor edi (`Env.releaseBlockers`),
#   lekin uni faqat test chaqirardi: arxivlashni hech narsa to'smasdi.
#
# QOIDA
#   Versiya va build raqami FAQAT `apps/mobile/pubspec.yaml` dan keladi.
#   Maxfiylik manzili majburiy, tekshiriladi va imzolangan artefakt ICHIDA
#   ham qayta tasdiqlanadi. Har qanday xato relizni TO'XTATADI (exit != 0).
#
# FOYDALANISH
#   scripts/release_ios.sh                      # darvoza + imzosiz release build
#   scripts/release_ios.sh --signed             # + arxiv va imzolangan IPA eksporti
#   scripts/release_ios.sh --skip-url-probe     # tarmoqsiz CI uchun (ANIQ tanlov)
#
#   BINOS_PRIVACY_URL=https://…/privacy scripts/release_ios.sh
#   yoki: scripts/release_ios.sh --privacy-url https://…/privacy
#
# BU SKRIPT HECH QACHON: App Store Connect'ga yuklamaydi, submit qilmaydi,
# sertifikat yaratmaydi/revoke qilmaydi, git push/merge qilmaydi.

set -euo pipefail

# ── Reliz raqami chegaralari ─────────────────────────────────────────────────
# App Store Connect'da mavjud eng katta build raqami (2026-10-29, FAQAT O'QISH
# `GET /v1/apps/6822128456/builds`): 56..62 va 65, hammasi VALID.
# ⚠️  R6.6 da 62 dan 65 ga OSHIRILDI: 65 R6.2 da yuklandi va
#     MISSING_EXPORT_COMPLIANCE holatida turadi. Chegara 62 da qolsa skript
#     65 ni qayta ishlatishga ruxsat berardi — Apple esa rad etardi.
readonly MIN_BUILD_EXCLUSIVE=66
# ASC'da bo'sh, lekin MAHALLIY imzolangan IPA'lar uchun allaqachon
# ishlatilgan raqamlar. Bitta raqam = bitta manba SHA, shuning uchun ular
# qayta ishlatilmaydi:
#   63 — S3 tuzatishidan OLDINGI source (`BinOS-63.ipa`)
#   64 — R6 source'ning uch bosqichi (42dafff, 04f91d6, 152b06f)
#   67 — R6.9 source (`0b32ade`), `BinOS-67.ipa`,
#        SHA-256 36d057d04675e4b43d0e5b8bf4a1f92a816bc0ac392af3e45617bdd4657f3667.
#        ⚠️  R7.2 da QO'SHILDI: 67 ASC'ga YUKLANMAGAN, shu bois
#            `MIN_BUILD_EXCLUSIVE` (ASC chegarasi, 66) uni to'smaydi — lekin
#            mahalliy imzolangan artefakt BOR va «bir raqam = bir manba SHA»
#            qoidasi bo'yicha raqam KUYGAN. R7.2 integratsiyasi mobil manbani
#            o'zgartirdi (`apps/mobile/lib` 9 fayl, `permission_matrix.json`),
#            ya'ni 67 endi boshqa source'ni ifodalay olmaydi.
readonly BURNED_BUILDS="63 64 67"
# `apps/mobile/test/ios_version_test.dart` shu ikki qiymatni o'qib, o'z
# konstantalari bilan solishtiradi — ya'ni ular bir-biridan ayrilib ketmaydi.

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
readonly APP_DIR="$REPO_ROOT/apps/mobile"
readonly BUNDLE_ID="com.binos.owner"

SIGNED=0
SKIP_URL_PROBE=0
PRIVACY_URL="${BINOS_PRIVACY_URL:-}"
EVIDENCE_DIR="${BINOS_EVIDENCE_DIR:-$APP_DIR/build/release-evidence}"

die() { printf '\n\033[31m⛔ BLOCKED:\033[0m %s\n' "$1" >&2; exit 1; }
ok()   { printf '  \033[32m✓\033[0m %s\n' "$1"; }
info() { printf '  · %s\n' "$1"; }
step() { printf '\n\033[1m══ %s\033[0m\n' "$1"; }

while [ $# -gt 0 ]; do
  case "$1" in
    --signed)         SIGNED=1; shift ;;
    --skip-url-probe) SKIP_URL_PROBE=1; shift ;;
    --privacy-url)    PRIVACY_URL="${2:-}"; shift 2 ;;
    --evidence-dir)   EVIDENCE_DIR="${2:-}"; shift 2 ;;
    -h|--help)        sed -n '2,32p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *)                die "noma'lum argument: $1" ;;
  esac
done

# ── 1. Versiya: YAGONA manba ────────────────────────────────────────────────
step "1. Versiya — yagona manba: pubspec.yaml"
[ -f "$APP_DIR/pubspec.yaml" ] || die "pubspec.yaml topilmadi: $APP_DIR"

VERSION_LINE_COUNT=$(grep -cE '^version:[[:space:]]*[0-9]+\.[0-9]+\.[0-9]+\+[0-9]+[[:space:]]*$' \
                     "$APP_DIR/pubspec.yaml" || true)
[ "$VERSION_LINE_COUNT" = "1" ] || \
  die "pubspec.yaml da aynan bitta \`version: x.y.z+build\` satri bo'lishi shart (topildi: $VERSION_LINE_COUNT)"

FULL_VERSION=$(sed -nE 's/^version:[[:space:]]*([0-9]+\.[0-9]+\.[0-9]+)\+([0-9]+)[[:space:]]*$/\1/p' \
               "$APP_DIR/pubspec.yaml")
BUILD_NUMBER=$(sed -nE 's/^version:[[:space:]]*([0-9]+\.[0-9]+\.[0-9]+)\+([0-9]+)[[:space:]]*$/\2/p' \
               "$APP_DIR/pubspec.yaml")
ok "versiya $FULL_VERSION, build $BUILD_NUMBER (pubspec.yaml)"

# ⚠️  Buyruq satridan build raqami QABUL QILINMAYDI. Agar kerak bo'lsa,
#     pubspec o'zgartirilib commit qilinadi — shunda toza clone ham AYNI
#     metadata'ni hosil qiladi.
[ -z "${BINOS_BUILD_NUMBER:-}" ] || \
  die "BINOS_BUILD_NUMBER qo'lda berilgan ($BINOS_BUILD_NUMBER). Raqam faqat pubspec.yaml dan olinadi — uni o'zgartirib commit qiling."

[ "$BUILD_NUMBER" -gt "$MIN_BUILD_EXCLUSIVE" ] || \
  die "build $BUILD_NUMBER App Store Connect'da allaqachon bor (56..$MIN_BUILD_EXCLUSIVE). Apple takroriy raqamni rad etadi."
for b in $BURNED_BUILDS; do
  [ "$BUILD_NUMBER" -ne "$b" ] || \
    die "build $b MAHALLIY imzolangan IPA uchun allaqachon ishlatilgan. Boshqa raqam tanlang."
done
ok "raqam bo'sh va eskirmagan (>$MIN_BUILD_EXCLUSIVE, $BURNED_BUILDS emas)"

# ── 2. Manba SHA ────────────────────────────────────────────────────────────
step "2. Manba holati"
SOURCE_SHA=$(git -C "$REPO_ROOT" rev-parse HEAD)
SOURCE_BRANCH=$(git -C "$REPO_ROOT" rev-parse --abbrev-ref HEAD)
# ⚠️  `awk` ishlatiladi, `grep -v` EMAS: toza daraxtda `grep -v` hamma satrni
#     filtrlab tashlab exit 1 beradi va `set -o pipefail` skriptni JIMGINA
#     o'ldiradi — ya'ni reliz aynan toza daraxtda ishlamasdi. `awk` har holda 0.
DIRTY_COUNT=$(git -C "$REPO_ROOT" status --porcelain | awk '!/^\?\? \.wt-/ && NF' | wc -l | tr -d ' ')
ok "branch $SOURCE_BRANCH @ ${SOURCE_SHA:0:7}"
if [ "$DIRTY_COUNT" != "0" ]; then
  info "⚠️  ishchi daraxtda $DIRTY_COUNT o'zgarish — artefakt ${SOURCE_SHA:0:7} ga AYNAN mos kelmaydi"
  DIRTY="true"
else
  ok "ishchi daraxt toza — artefakt manba SHA'siga aynan mos"
  DIRTY="false"
fi

# ── 3. Maxfiylik siyosati darvozasi ─────────────────────────────────────────
step "3. Maxfiylik siyosati manzili (Apple Guideline 5.1.1)"
[ -n "$PRIVACY_URL" ] || die "BINOS_PRIVACY_URL berilmagan. Bu qiymat ataylab standart qiymatsiz: taxmin qilingan havola App Review'da o'lik chiqadi. Bering: --privacy-url https://…/privacy"

# Dart tarafidagi `Env.normalizePrivacyUrl` qoidalarining AYNI o'zi.
case "$PRIVACY_URL" in
  https://*) ;;
  *) die "maxfiylik manzili https bo'lishi shart (berilgan: $PRIVACY_URL)" ;;
esac
PRIVACY_HOST=$(printf '%s' "$PRIVACY_URL" | sed -E 's#^https://([^/?#]+).*#\1#')
case "$PRIVACY_HOST" in
  *@*)         die "manzilda login/parol bor — ommaviy havola bunday bo'lmaydi" ;;
  localhost|127.0.0.1|::1|*.local|*.localhost|*.invalid)
               die "manzil dasturchi mashinasiga ishora qiladi: $PRIVACY_HOST" ;;
esac
case "$PRIVACY_HOST" in
  *.*) ;;
  *)   die "manzil hosti ro'yxatga olinadigan domen bo'lishi shart: $PRIVACY_HOST" ;;
esac
ok "shakl to'g'ri: $PRIVACY_URL"

PRIVACY_HTTP="skipped"
if [ "$SKIP_URL_PROBE" = "1" ]; then
  info "⚠️  tarmoq tekshiruvi ANIQ o'tkazib yuborildi (--skip-url-probe)"
else
  PRIVACY_HTTP=$(curl -sS -o /dev/null -L --max-time 25 -w '%{http_code}' "$PRIVACY_URL" 2>/dev/null || true)
  [ -n "$PRIVACY_HTTP" ] || PRIVACY_HTTP="000"
  [ "$PRIVACY_HTTP" = "200" ] || \
    die "maxfiylik sahifasi ommaga ochiq emas: HTTP $PRIVACY_HTTP ($PRIVACY_URL). App Review o'lik havolani rad etadi."
  ok "ommaga ochiq: HTTP 200"
fi

# ── 4. Release qurilishi ────────────────────────────────────────────────────
step "4. iOS release qurilishi"
cd "$APP_DIR"
info "flutter build ios --release --no-codesign (build raqami pubspec'dan)"
# ⚠️  `--build-number` ATAYLAB BERILMAYDI: Flutter uni pubspec'dan oladi, ya'ni
#     toza clone ayni metadata'ni hosil qiladi.
flutter build ios --release --no-codesign \
  --dart-define=BINOS_PRIVACY_URL="$PRIVACY_URL" >/dev/null
ok "qurildi"

GENERATED="$APP_DIR/ios/Flutter/Generated.xcconfig"
GEN_BUILD=$(sed -nE 's/^FLUTTER_BUILD_NUMBER=(.*)$/\1/p' "$GENERATED")
GEN_NAME=$(sed -nE 's/^FLUTTER_BUILD_NAME=(.*)$/\1/p' "$GENERATED")
[ "$GEN_BUILD" = "$BUILD_NUMBER" ] || \
  die "generatsiya qilingan build raqami pubspec'dan FARQ qiladi: $GEN_BUILD != $BUILD_NUMBER"
[ "$GEN_NAME" = "$FULL_VERSION" ] || \
  die "generatsiya qilingan versiya pubspec'dan FARQ qiladi: $GEN_NAME != $FULL_VERSION"
ok "Generated.xcconfig pubspec bilan mos: $GEN_NAME+$GEN_BUILD"

# ── 5. Artefakt tekshiruvi ──────────────────────────────────────────────────
step "5. Artefakt ichidagi reliz konfiguratsiyasi"
APP_BUNDLE="$APP_DIR/build/ios/iphoneos/Runner.app"
[ -d "$APP_BUNDLE" ] || die "qurilgan .app topilmadi: $APP_BUNDLE"

plist_get() { /usr/libexec/PlistBuddy -c "Print :$1" "$APP_BUNDLE/Info.plist" 2>/dev/null || echo ""; }
A_BUNDLE=$(plist_get CFBundleIdentifier)
A_BUILD=$(plist_get CFBundleVersion)
A_VERSION=$(plist_get CFBundleShortVersionString)
[ "$A_BUNDLE" = "$BUNDLE_ID" ] || die "bundle id mos emas: $A_BUNDLE != $BUNDLE_ID"
[ "$A_BUILD" = "$BUILD_NUMBER" ] || die "artefaktdagi build raqami mos emas: $A_BUILD != $BUILD_NUMBER"
[ "$A_VERSION" = "$FULL_VERSION" ] || die "artefaktdagi versiya mos emas: $A_VERSION != $FULL_VERSION"
ok "$A_BUNDLE — $A_VERSION ($A_BUILD)"

# ⚠️  Maxfiylik manzili ARTEFAKT ICHIDA tasdiqlanadi: `String.fromEnvironment`
#     qiymati AOT snapshot'ga const satr sifatida tushadi. Darvoza faqat
#     skriptda bo'lsa, qo'lda qilingan qurilish uni chetlab o'tardi.
SNAPSHOT="$APP_BUNDLE/Frameworks/App.framework/App"
[ -f "$SNAPSHOT" ] || die "Dart snapshot topilmadi: $SNAPSHOT"
# ⚠️  `grep -q` ISHLATILMAYDI: u mos kelganda darhol chiqadi, `strings` SIGPIPE
#     oladi va `set -o pipefail` butun quvurni muvaffaqiyatsiz deb hisoblaydi —
#     ya'ni URL joyida bo'lsa ham darvoza yolg'ondan to'sardi.
SNAPSHOT_HITS=$(strings "$SNAPSHOT" 2>/dev/null | grep -cF -- "$PRIVACY_URL" || true)
[ "${SNAPSHOT_HITS:-0}" -ge 1 ] || \
  die "maxfiylik manzili artefakt ichida YO'Q — dart-define qurilishga yetib bormagan"
ok "maxfiylik manzili snapshot ichida topildi ($SNAPSHOT_HITS marta)"

# ATS istisnosi va iPhone-only invariantlari (R5 lokalizatsiya tuzatishi bilan birga)
if /usr/libexec/PlistBuddy -c "Print :NSAppTransportSecurity" "$APP_BUNDLE/Info.plist" >/dev/null 2>&1; then
  die "artefaktda NSAppTransportSecurity istisnosi bor — test sozlamasi relizga sizib o'tgan"
fi
ok "ATS istisnosi yo'q"
LPROJ_COUNT=$(find "$APP_BUNDLE" -name 'InfoPlist.strings' | wc -l | tr -d ' ')
[ "$LPROJ_COUNT" -ge 4 ] || die "tizim ruxsat oynalari lokalizatsiyasi yo'q ($LPROJ_COUNT InfoPlist.strings) — Apple Guideline 4 radi qaytadi"
[ ! -d "$APP_BUNDLE/en.lproj" ] || die "en.lproj mavjud — inglizcha so'rov + o'zbekcha UI aynan rad etilgan nomuvofiqlik"
ok "lokalizatsiya: $LPROJ_COUNT InfoPlist.strings, en.lproj yo'q"

# ── 6. Imzolash (ixtiyoriy) ─────────────────────────────────────────────────
ARCHIVE_PATH=""
IPA_PATH=""
IPA_SHA=""
if [ "$SIGNED" = "1" ]; then
  step "6. Arxiv va imzolangan IPA eksporti"
  : "${BINOS_SIGNING_IDENTITY:?--signed uchun BINOS_SIGNING_IDENTITY kerak}"
  : "${BINOS_EXPORT_OPTIONS:?--signed uchun BINOS_EXPORT_OPTIONS (ExportOptions.plist) kerak}"
  OUT_DIR="${BINOS_SIGNED_OUT:-$APP_DIR/build/signed}"
  mkdir -p "$OUT_DIR"
  ARCHIVE_PATH="$OUT_DIR/Runner.xcarchive"
  xcodebuild -workspace "$APP_DIR/ios/Runner.xcworkspace" -scheme Runner \
    -configuration Release -sdk iphoneos -archivePath "$ARCHIVE_PATH" archive
  xcodebuild -exportArchive -archivePath "$ARCHIVE_PATH" \
    -exportOptionsPlist "$BINOS_EXPORT_OPTIONS" -exportPath "$OUT_DIR/ipa"
  IPA_PATH=$(find "$OUT_DIR/ipa" -name '*.ipa' | sed -n 1p)
  [ -n "$IPA_PATH" ] || die "IPA eksport qilinmadi"
  IPA_SHA=$(shasum -a 256 "$IPA_PATH" | cut -d' ' -f1)
  ok "IPA: $IPA_PATH"
  ok "SHA-256: $IPA_SHA"
else
  step "6. Imzolash"
  info "o'tkazib yuborildi (--signed berilmagan). Imzosiz release build tekshirildi."
fi

# ── 7. Build dalili ─────────────────────────────────────────────────────────
step "7. Build dalili"
mkdir -p "$EVIDENCE_DIR"
EVIDENCE="$EVIDENCE_DIR/build-$BUILD_NUMBER-${SOURCE_SHA:0:7}.json"
cat > "$EVIDENCE" <<JSON
{
  "app": "$BUNDLE_ID",
  "version": "$FULL_VERSION",
  "build_number": $BUILD_NUMBER,
  "source_sha": "$SOURCE_SHA",
  "source_branch": "$SOURCE_BRANCH",
  "working_tree_dirty": $DIRTY,
  "privacy_policy_url": "$PRIVACY_URL",
  "privacy_policy_http": "$PRIVACY_HTTP",
  "privacy_url_in_artifact": true,
  "signed": $([ "$SIGNED" = "1" ] && echo true || echo false),
  "ipa_path": "$IPA_PATH",
  "ipa_sha256": "$IPA_SHA",
  "built_at_utc": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "flutter": "$(flutter --version 2>/dev/null | sed -n 1p)",
  "xcode": "$(xcodebuild -version 2>/dev/null | sed -n 1p)",
  "uploaded_to_app_store_connect": false
}
JSON
ok "yozildi: $EVIDENCE"
cat "$EVIDENCE" | sed 's/^/    /'

printf '\n\033[32m✓ RELIZ DARVOZALARI O`TDI\033[0m — %s %s (%s) @ %s\n' \
  "$BUNDLE_ID" "$FULL_VERSION" "$BUILD_NUMBER" "${SOURCE_SHA:0:7}"
[ "$SIGNED" = "1" ] || printf '  Imzolangan IPA uchun: scripts/release_ios.sh --signed\n'
printf '  Bu skript App Store Connect`ga HECH NARSA yuborMAYDI.\n'
