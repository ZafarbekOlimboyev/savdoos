# BinOS PWA — production hosting

Flutter web bundle'i **statik** tarqatiladi (Caddy). API backend **alohida** servisda
(`savdoos`) — bu yerda proxy YO'Q, PWA API'ga to'g'ridan-to'g'ri chiqadi va
`web/sw.js` `/api/` yo'lini umuman ushlamaydi.

| Nima | Qiymat |
|---|---|
| Railway servis | `savdoos-pwa` (backend `savdoos` dan ALOHIDA) |
| Image | `caddy:2.10-alpine` + `Caddyfile` + yig'ilgan `web/` |
| Port | `$PORT` (Railway beradi), standart 8080 |
| Production API | `https://savdoos-production.up.railway.app` |
| Build muhri | `GET /binos-build-id.txt` — ishlab turgan bundle ID'si |

## Yig'ish (AYNAN shu buyruq — CI ham shuni ishlatadi)

```bash
cd apps/mobile
flutter --no-version-check pub get --enforce-lockfile
flutter --no-version-check build web --release --no-pub \
  --no-web-resources-cdn --pwa-strategy=none \
  --dart-define=BINOS_API_BASE=https://savdoos-production.up.railway.app \
  --dart-define=BINOS_ENV=production
cd ../.. && node scripts/pwa_postbuild.mjs        # MAJBURIY (sw.js ni muhrlaydi)
node scripts/pwa_sw_selftest.mjs                  # 36 tekshiruv
```

`--pwa-strategy=none` va `--no-web-resources-cdn` **majburiy**: birinchisi Flutter'ning
ikkinchi service worker'ini chiqarmaydi, ikkinchisi CanvasKit'ni o'z originimizdan beradi.
Tafsilot: `apps/mobile/README.md` ("PWA").

`BINOS_ENV=production` — STAGING chizig'i **ko'rinmaydi** (`lib/ui/env_badge.dart`);
`BINOS_ENV=staging` bilan yig'ilgan bundle production'ga chiqarilmasin.

## Deploy

```bash
bash infra/pwa/deploy.sh production savdoos-pwa 32171ad7-cd7a-4eb8-8080-4806250fd1b8
```

Uchinchi argument — **loyiha id** (`railway status` ko'rsatadi) va u MAJBURIY: yuklash
papkasi vaqtinchalik hamda Railway'ga bog'lanmagan, `--project` bo'lmasa CLI yangi
loyiha yaratib yuborishi mumkin.

Skript **dirty daraxtda TO'XTAYDI** va `sw.js` muhrini tekshiradi. Production bundle
darvozasi — `savdoos-staging` / `api.invalid` / `localhost` / `STAGING` / `SCAN DIAG` /
`diag=scan` yo'qligi — **servis nomiga** qarab ishlaydi: Railway'da muhit bitta
(`production`) va do'kon PWA'sini nomzoddan ajratadigan narsa servis. Nomzod
(`savdoos-pwa-candidate*`) ataylab diagnostika bayrog'i bilan yig'iladi, shu bois
unga deploy qilishda bu darvoza o'tkazilmaydi — qolgan hamma tekshiruv esa ikkalasiga
ham qo'llanadi. Nomzodni skriptdan CHETLAB O'TMANG.

## Nega image ichida Flutter yo'q

Flutter SDK'ni image'ga qo'shish ~2 GB va **ikkinchi, tekshirilmagan build yo'li**
paydo bo'lardi. CI ayni SHA'da ayni bundle'ni yig'ib `pwa_postbuild.mjs` va
`pwa_sw_selftest.mjs` darvozalaridan o'tkazadi; deploy esa AYNI chiqishni yuklaydi.
Provenans: manba SHA + `binos-build-id.txt` + Railway deployment ID.

## Sarlavhalar

`web/index.html` dagi CSP meta tegi `frame-ancestors` va `X-Content-Type-Options` ni
bera olmaydi, boot fayllariga `no-cache` ham kerak — shu uchtasi `Caddyfile` da.
Javob sarlavhasidagi CSP `connect-src` ni AYNAN production API origin'iga **toraytiradi**
(meta tegdagi `https:` dan qat'iyroq): PWA boshqa serverga yo'naltirilib qo'yilmasin.
Ya'ni bu bundle'da Sozlamalar ▸ server orqali boshqa manzil **ishlamaydi** — bu ataylab.
