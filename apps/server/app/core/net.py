# -*- coding: utf-8 -*-
"""Mijoz IP'sini aniqlash — YAGONA manba. Railway ingress SHARTNOMASI asosida.

QAROR: `X-Forwarded-For` ning ENG CHAP (birinchi) qiymati olinadi.

⚠️  NEGA AYNAN SHU — VA NEGA BOSHQALARI EMAS.

1) NEGA ENG O'NG EMAS (kod ilgari shunday qilardi).
   O'lchov (staging, haqiqiy Railway ingress): ilova eng o'ngdan ommaviy manzil
   izlaganda `212.102.36.19x` ni topdi — bu operator manzili EMAS, Railway'ning
   CDN (Fastly) POP manzili, va u SO'ROVDAN SO'ROVGA O'ZGARIB TURADI. Oqibati
   ikkita edi: vendor IP allowlist hech qachon mos kelmasdi (doim 403), va
   kassir rate-limit kaliti CDN manziliga bog'lanib parchalanib ketardi.

2) NEGA HOP SANOG'I EMAS.
   Railway CDN (Fastly) yo'lini bosqichma-bosqich yoqmoqda va trafik ba'zan CDN
   orqali, ba'zan to'g'ridan-to'g'ri o'tadi. Railway xodimi buni ochiq aytgan:
   zanjir chuqurligi BARQAROR EMAS. Qat'iy sanoq bugun ishlab, ertaga JIMGINA
   noto'g'ri qiymatga tushardi — ya'ni topologiyaga bog'liq, shartnomaga emas.

3) NEGA `X-Real-IP` EMAS.
   Railway hujjatlashtirilgan nuqson sifatida tan olgan: CDN faol bo'lganda
   `X-Real-IP` mijoz emas, CDN edge manzilini oladi. Bundan tashqari u yaqin
   o'tmishgacha mijoz tomonidan TO'G'RIDAN-TO'G'RI o'rnatilishi mumkin edi.

4) NEGA ENG CHAP XAVFSIZ (bu asosiy savol edi).
   Railway xodimlari bu masalada bir-biriga ZID javob berishgan ("strip qilamiz,
   birinchi qiymat haqiqiy" va "eng o'ng ishonchli"), eski forum yozuvida esa
   mijoz yuborgan `X-Forwarded-For: 8.8.8.8` qaytgani ko'rsatilgan. Shuning uchun
   bu TAXMIN qilinmadi, O'LCHANDI (staging, haqiqiy ingress):

       XFF siz          -> ilova hisobladi: <operator IP>
       XFF: 8.8.8.8     -> ilova hisobladi: <operator IP>   (soxta qiymat YO'QOLDI)

   Ya'ni edge mijoz yuborgan sarlavhani STRIP qiladi va birinchi qiymatni O'ZI
   qo'yadi. Bu Railway'ning rasmiy tavsiyasi bilan ham mos ("Use X-Forwarded-For
   and take the first IP"), va Railway edge HTTP logidagi `srcIp` bilan ham.

⚠️  QOLDIQ XAVF, ochiq aytiladi: bu xossa platformaning xatti-harakatiga bog'liq.
    Railway kelajakda strip qilishni to'xtatsa, eng chap qiymat hujumchi
    boshqaruviga o'tardi. Shuning uchun IP allowlist YOLG'IZ himoya EMAS — vendor
    yo'li master kalit + MAJBURIY TOTP + rate limit bilan ham qo'riqlanadi, ya'ni
    XFF regressiyasining O'ZI kirish bermaydi. Tashqi qatlam sifatida Railway
    Edge Rules (path + client IP/CIDR bo'yicha bloklash) tavsiya etiladi.

TOPOLOGIYA SILJISHI FAIL-CLOSED: ommaviy manzil aniqlanmasa bo'sh satr qaytadi —
allowlist rad etadi (403) va rate-limit hammasini bitta "noma'lum" bucket'ga
yig'adi. Rad etilgan urinishlar `vendor_auth_attempts` ga YOZILADI, ya'ni siljish
jim qolmaydi: aynan shu yozuvlar orqali yuqoridagi CDN muammosi topilgan.
"""
from __future__ import annotations

import ipaddress


def _is_infrastructure(ip: str) -> bool:
    """Manzil INFRATUZILMAGA tegishlimi (ya'ni mijoz bo'la olmaydimi).

    IANA zahiralangan diapazonlar — ta'rif bo'yicha barqaror, Railway
    topologiyasiga bog'liq emas."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return True                      # noto'g'ri shakl — mijoz sifatida qabul qilinmaydi
    return (
        addr.is_private                  # RFC1918 / IPv6 ULA (fd00::/8)
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_reserved
        or addr.is_unspecified
        # RFC6598 — operator ichki tarmog'i (Railway ichki hop'lari shu yerda)
        or addr in ipaddress.ip_network("100.64.0.0/10")
    )


def _normalize(part: str) -> str:
    """`[::1]:443` / `1.2.3.4:5678` kabi shakllarni toza manzilga keltiradi."""
    p = part.strip()
    if p.startswith("["):                # IPv6 qavs ichida, ehtimol port bilan
        end = p.find("]")
        if end > 0:
            return p[1:end]
    if p.count(":") == 1:                # IPv4:port (IPv6 da ikkitadan ko'p ":" bo'ladi)
        head = p.split(":", 1)[0]
        try:
            ipaddress.ip_address(head)
            return head
        except ValueError:
            return p
    return p


def client_ip(request) -> str:
    """So'rovning HAQIQIY mijoz IP'si. Aniqlab bo'lmasa — bo'sh satr (fail-closed)."""
    if request is None:
        return ""
    raw = request.headers.get("x-forwarded-for") or ""
    chain = [_normalize(p) for p in raw.split(",") if p.strip()]

    if chain:
        # Railway ingress shartnomasi: BIRINCHI qiymat — haqiqiy mijoz.
        first = chain[0]
        if not _is_infrastructure(first):
            return first
        # Birinchi qiymat ommaviy emas: proxy oldida yana bir qatlam bor yoki
        # topologiya o'zgargan. TAXMIN QILMAYMIZ — noma'lum deb qaytaramiz.
        return ""

    # `X-Forwarded-For` umuman yo'q — proxy'siz ulanish (lokal dev/test).
    peer = request.client.host if request.client else ""
    return peer
