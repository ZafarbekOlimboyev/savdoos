# BinOS PWA — statik hosting (Railway `savdoos-pwa` servisi).
#
# ⚠️  BU IMAGE FLUTTER'NI YIG'MAYDI. Bundle repo'ga kirmaydi (`build/` gitignore'da),
#     shu bois deploy ikki qadam: (1) ANIQ SHA'dagi TOZA daraxtdan mahalliy/CI build,
#     (2) `infra/pwa/deploy.sh` yuklash papkasini yasab `railway up` qiladi.
#     Tartib va tekshiruvlar: `infra/pwa/README.md`.
#
#     Sabab: Flutter SDK'ni image ichida qurish ~2 GB va CI allaqachon AYNI
#     build'ni shu SHA'da yig'ib darvozadan o'tkazadi (`pwa_postbuild.mjs` +
#     `pwa_sw_selftest.mjs`) — ikkinchi, tekshirilmagan build yo'lini
#     ochish provenansni zaiflashtirardi.
FROM caddy:2.10-alpine

COPY Caddyfile /etc/caddy/Caddyfile
# `web/` — `flutter build web` chiqishi + `pwa_postbuild.mjs` muhri.
COPY web/ /srv/

# Muhr fayli image ichida ham qolsin: ishlab turgan servisda qaysi build ekanini
# `GET /binos-build-id.txt` bilan tekshirish mumkin.
RUN test -f /srv/index.html && test -f /srv/sw.js && test -f /srv/binos-build-id.txt \
    && caddy validate --config /etc/caddy/Caddyfile

EXPOSE 8080
CMD ["caddy", "run", "--config", "/etc/caddy/Caddyfile", "--adapter", "caddyfile"]
