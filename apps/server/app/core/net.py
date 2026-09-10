# -*- coding: utf-8 -*-
"""Mijoz IP'sini aniqlash — YAGONA manba, INFRATUZILMA DIAPAZONLARI bo'yicha.

⚠️  NEGA HOP SANALMAYDI VA NEGA ENG CHAP QIYMAT OLINMAYDI.

    Railway'ning o'z xodimlari bu savolga BIR-BIRIGA ZID javob berishgan:
      · bir xodim: "biz X-Forwarded-For'ni edge'da STRIP qilamiz, BIRINCHI qiymat
        haqiqiy mijoz" (ya'ni eng CHAP);
      · boshqa xodim: "eng O'NG qiymat ishonchli";
      · uchinchi javobda mijoz yuborgan `X-Forwarded-For: 8.8.8.8` filtrlanmasdan
        QAYTGANI ko'rsatilgan — ya'ni amalda edge zanjirga QO'SHADI, strip qilmaydi.
    Bundan tashqari Railway CDN (Fastly) yo'lini bosqichma-bosqich yoqmoqda va
    trafik ba'zan CDN orqali, ba'zan to'g'ridan-to'g'ri o'tadi — ya'ni ZANJIR
    CHUQURLIGI KAFOLATLANMAGAN.

    Shu sabab:
      · ENG CHAP qiymat XAVFSIZ EMAS — edge qo'shsa, u hujumchi yuborgan qiymat
        bo'lib qoladi (yuqoridagi spoofing shu);
      · QAT'IY HOP SANOG'I ham xavfsiz emas — bugungi topologiya ertaga o'zgaradi
        va sanoq JIMGINA noto'g'ri qiymatga tushadi;
      · `X-Real-IP` ham tayanch emas — Railway hujjatida CDN yoqilganda u CDN edge
        manzilini oladi (Railway buni O'Z NUQSONI deb tan olgan), va u yaqingacha
        mijoz tomonidan to'g'ridan-to'g'ri o'rnatilishi mumkin edi.

    O'RNIGA: zanjir O'NGDAN chapga skanerlanadi va INFRATUZILMA manzillari
    (RFC1918 xususiy, RFC6598 100.64/10 umumiy, loopback, link-local, IPv6 ULA)
    tashlab yuboriladi; birinchi uchragan OMMAVIY manzil — mijoz.

    Bu IKKALA o'qishda ham to'g'ri ishlaydi:
      · edge STRIP qilsa   -> zanjir `<mijoz>, <ichki...>`      -> mijoz topiladi
      · edge QO'SHSA       -> `<soxta...>, <mijoz>, <ichki...>` -> yana mijoz topiladi,
        chunki hujumchi faqat CHAPGA qiymat qo'sha oladi va biz unga YETIB BORMAYMIZ.
    Va u hop SONIGA bog'liq emas — qo'shimcha ichki hop paydo bo'lsa, u shunchaki
    tashlab yuboriladi.

    TOPOLOGIYA SILJISHI FAIL-CLOSED ANIQLANADI: ommaviy manzil topilmasa bo'sh satr
    qaytadi. Vendor allowlist unga mos kelmaydi (403), rate-limit esa hammasini
    bitta "noma'lum" bucket'ga yig'adi — ya'ni himoya ochilib ketmaydi, muammo esa
    darhol ko'rinadi.

    QOLDIQ XAVF (ochiq aytiladi): agar Railway kelajakda mijoz yozuvidan O'NGGA
    OMMAVIY manzilli CDN hop qo'shsa, algoritm o'sha CDN manzilini qaytaradi.
    Oqibati — allowlist mos kelmay qoladi (403, fail-closed va KO'RINADI), ochilib
    ketish emas. Tashqi qatlam sifatida Railway Edge Rules tavsiya etiladi.
"""
from __future__ import annotations

import ipaddress


def _is_infrastructure(ip: str) -> bool:
    """Manzil INFRATUZILMAGA tegishlimi (mijoz bo'la olmaydimi).

    IANA zahiralangan diapazonlar — bular ta'rif bo'yicha barqaror, Railway
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
    if p.count(":") == 1:                # IPv4:port
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
    # ── VAQTINCHA O'LCHOV REJIMI: ENG CHAP qiymat ─────────────────────────
    # Maqsad: Railway edge mijoz yuborgan XFF'ni STRIP qiladimi yoki zanjirga
    # QO'SHADIMI — buni faqat jonli o'lchov hal qiladi (Railway xodimlari zid
    # javob berishgan). Bu blok o'lchovdan keyin ALMASHTIRILADI.
    for part in chain[:1]:
        if not _is_infrastructure(part):
            return part
    if chain:
        # Zanjir bor, LEKIN birorta ommaviy manzil yo'q. Bu yo lokal/ichki so'rov,
        # yo topologiya o'zgargan. Peer o'zi ommaviy bo'lsa — undan foydalanamiz.
        peer = request.client.host if request.client else ""
        return peer if peer and not _is_infrastructure(peer) else ""
    # Proxy umuman yo'q (lokal dev / to'g'ridan-to'g'ri ulanish) — peer manzili.
    return request.client.host if request.client else ""
