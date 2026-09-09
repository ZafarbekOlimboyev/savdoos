#!/usr/bin/env bash
# SavdoOS · PostgreSQL mijoz binarlarini ANIQ tanlash + versiya gardi.
#
# ═══ NEGA BU FAYL BOR ════════════════════════════════════════════════════════
# Birinchi HAQIQIY production backup'i AYNAN shu sababdan yiqildi:
#
#     pg_dump: error: aborting because of server version mismatch
#     server version: 18.6 ... pg_dump version: 16.15
#
# Holbuki workflow `postgresql-client-17` ni MUVAFFAQIYATLI o'rnatgan edi (17.11).
# Sabab: Debian/Ubuntu'da `/usr/bin/pg_dump` — bu haqiqiy binar EMAS, u
# `/usr/share/postgresql-common/pg_wrapper` ga symlink. Wrapper qaysi versiyani
# ishga tushirishni O'ZI hal qiladi (standart klaster bo'yicha), va GitHub runner
# obrazida PostgreSQL 16 oldindan o'rnatilgani uchun u DOIM 16 ni tanlardi.
# Ya'ni yangi mijozni o'rnatish YETARLI EMAS — binar ANIQ ko'rsatilishi kerak.
#
# Shu bois: hech qachon PATH'dagi `pg_dump` ga ishonmaymiz. Versiyali katalogdan
# (`/usr/lib/postgresql/<major>/bin`) ANIQ binar tanlanadi va ishlatishdan OLDIN
# server bilan solishtiriladi.
#
# Ishlatish:
#     . scripts/lib/pg_client.sh
#     pg_client_resolve            # PG_DUMP / PG_RESTORE / PSQL o'zgaruvchilarini to'ldiradi
#     pg_client_require_ge "$URL"  # mijoz major >= server major ekanini TASDIQLAYDI
#
# Bekor qilish: PG_BIN=/usr/lib/postgresql/18/bin (yoki pgserver bin katalogi).

# `fail` chaqiruvchi skriptda aniqlanadi; bo'lmasa oddiy variant.
if ! command -v fail >/dev/null 2>&1 && ! declare -F fail >/dev/null 2>&1; then
  fail() { echo "::error::$*" >&2; exit 1; }
fi

# ═══ YAGONA (KANONIK) VERSIYA PARSERI ════════════════════════════════════════
# Butun repoda major versiyani AJRATIB OLADIGAN YAGONA joy shu. `action.yml` ham,
# testlar ham SHU funksiyani chaqiradi — o'z naqshini SAQLAMAYDI.
#
# NEGA: ilgari `action.yml` da ALOHIDA nusxa bor edi va u ochko'z naqsh ishlatardi:
#     sed -nE 's/.*[^0-9]([0-9]+)(\.[0-9]+)*.*/\1/p'
# Ochko'z `.*` satr oxirigacha yutib, OXIRGI sonni tutardi:
#     "pg_dump (PostgreSQL) 18.6 (Ubuntu 18.6-1.pgdg24.04+2)"  ->  2
# Ya'ni paket raqami (+2) major deb o'qilardi va production backup'i
# "major=2, expected=18" bilan YIQILDI. `pg_client.sh` tuzatilgan edi, `action.yml`
# esa YO'Q — ikki nusxa AJRALIB ketgani uchun. Endi nusxa BITTA.
#
# Qoida: naqsh "PostgreSQL)" TOKENIGA bog'lanadi va undan KEYINGI sonni oladi.
# "satrdagi oxirgi son" yoki "satrdagi birinchi son" kabi taxminlar ISHLATILMAYDI.

pg_parse_major() {   # pg_parse_major <versiya matni>  -> major yoki BO'SH
  local line major
  line="$(printf '%s\n' "$1" | head -1)"

  # 1) Mijoz binarlari: "pg_dump (PostgreSQL) 18.6 (Ubuntu 18.6-1.pgdg24.04+2)"
  #    "PostgreSQL)" dan KEYINGI son olinadi — paket qismiga umuman yetib bormaydi.
  major="$(printf '%s\n' "$line" \
    | sed -nE 's/.*PostgreSQL\)[[:space:]]+([0-9]+).*/\1/p' | head -1)"

  # 2) `SHOW server_version`: "18.6 (Debian 18.6-1.pgdg13+2)" — "PostgreSQL" so'zi YO'Q,
  #    versiya SATR BOSHIDA turadi. Shu bois BOSHIGA bog'laymiz (oxiriga EMAS).
  if [ -z "$major" ]; then
    major="$(printf '%s\n' "$line" \
      | sed -nE 's/^[[:space:]]*([0-9]+)([.[:space:]].*)?$/\1/p' | head -1)"
  fi

  printf '%s\n' "$major"
}

# Fail-closed variant: aniqlab bo'lmasa ANIQ xato bilan to'xtaydi.
# "Bilmayman" ni jimgina o'tkazib yuborish aynan production nosozligiga olib borgan edi.
pg_parse_major_strict() {   # pg_parse_major_strict <matn> <kontekst>
  local major ctx raw
  # DIQQAT: `${2:-...}` ichida APOSTROF ISHLATILMAYDI. Bash uni parametr kengaytmasi
  # ichida QO'SHTIRNOQ deb o'qiydi va butun faylning sintaksisi buziladi
  # ("unexpected EOF"). Shu bois matn oldindan oddiy o'zgaruvchiga olinadi.
  ctx="${2:-manba}"
  raw="$(printf '%s' "$1" | head -1)"
  major="$(pg_parse_major "$1")"
  case "$major" in
    ''|*[!0-9]*)
      fail "Versiyani aniqlab bo'lmadi ($ctx). Olingan matn: [$raw]" ;;
  esac
  printf '%s\n' "$major"
}

pg_client_major() {   # pg_client_major <binar>
  pg_parse_major "$("$1" --version 2>/dev/null)"
}

pg_server_major() {   # pg_server_major <url>
  # `SHOW server_version` -> "18.6 (Debian 18.6-1.pgdg13+2)"
  pg_parse_major "$("$PSQL" -tAc 'SHOW server_version' "$1" 2>/dev/null)"
}

# PG_DUMP / PG_RESTORE / PSQL ni to'ldiradi. Tanlov tartibi:
#   1) PG_BIN aniq berilgan bo'lsa — SHU
#   2) /usr/lib/postgresql/<major>/bin — ENG YUQORI major
#   3) PATH (oxirgi chora; pg_wrapper xavfi bor, shu bois ogohlantiramiz)
pg_client_resolve() {
  local dir=""

  if [ -n "${PG_BIN:-}" ]; then
    dir="$PG_BIN"
    [ -x "$dir/pg_dump" ] || [ -x "$dir/pg_dump.exe" ] \
      || fail "PG_BIN='$dir' — bu katalogda pg_dump topilmadi."
  else
    # Versiyali kataloglar orasidan ENG YUQORI major (18 > 17 > 16 ...).
    local best=0 cand
    for cand in /usr/lib/postgresql/*/bin /usr/pgsql-*/bin /opt/homebrew/opt/postgresql@*/bin; do
      [ -x "$cand/pg_dump" ] || continue
      local m
      m="$(pg_client_major "$cand/pg_dump")"
      case "$m" in ''|*[!0-9]*) continue ;; esac
      if [ "$m" -gt "$best" ]; then best="$m"; dir="$cand"; fi
    done
    if [ -z "$dir" ]; then
      command -v pg_dump >/dev/null 2>&1 \
        || fail "pg_dump topilmadi. PostgreSQL client o'rnating (yoki PG_BIN bering)."
      echo "::warning::Versiyali PostgreSQL katalogi topilmadi — PATH'dagi binar ishlatiladi." \
           "Debian/Ubuntu'da bu pg_wrapper bo'lishi va ESKI versiyani tanlashi mumkin."
      PG_DUMP="$(command -v pg_dump)"
      PG_RESTORE="$(command -v pg_restore)"
      PSQL="$(command -v psql)"
      export PG_DUMP PG_RESTORE PSQL
      return 0
    fi
  fi

  # `.exe` — Windows (pgserver) uchun
  if [ -x "$dir/pg_dump" ]; then
    PG_DUMP="$dir/pg_dump"; PG_RESTORE="$dir/pg_restore"; PSQL="$dir/psql"
  else
    PG_DUMP="$dir/pg_dump.exe"; PG_RESTORE="$dir/pg_restore.exe"; PSQL="$dir/psql.exe"
  fi
  export PG_DUMP PG_RESTORE PSQL
}

# Mijoz serverdan ESKI bo'lmasligi SHART.
#
# pg_dump serverdan eski bo'lsa QAT'IY rad etadi (bizni yiqitgan holat). pg_dump YANGI
# bo'lishi esa qo'llab-quvvatlanadi va xavfsiz — shu bois shart `>=`, `==` EMAS
# (aks holda Railway serverni yangilagan kunning ertasiga backup to'xtardi).
pg_client_require_ge() {   # pg_client_require_ge <url>
  local srv cli
  srv="$(pg_server_major "$1")"
  cli="$(pg_client_major "$PG_DUMP")"

  case "$srv" in ''|*[!0-9]*) fail "server versiyasini aniqlab bo'lmadi (ulanish xatomi?)." ;; esac
  case "$cli" in ''|*[!0-9]*) fail "pg_dump versiyasini aniqlab bo'lmadi: $PG_DUMP" ;; esac

  echo "PostgreSQL · server_major=$srv · pg_dump_major=$cli · binar=$PG_DUMP"

  if [ "$cli" -lt "$srv" ]; then
    fail "MIJOZ ESKI: pg_dump major=$cli, server major=$srv. pg_dump bunday holatda \
ATAYLAB rad etadi va NUSXA OLINMAYDI. postgresql-client-$srv o'rnating va \
/usr/lib/postgresql/$srv/bin ni ishlating (PATH'dagi pg_dump pg_wrapper bo'lishi mumkin)."
  fi
}
