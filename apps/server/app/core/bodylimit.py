# -*- coding: utf-8 -*-
"""So'rov tanasi hajmi chegarasi — ASGI darajasida.

⚠️  ILGARI CHEGARA UMUMAN YO'Q EDI. Autentifikatsiyasiz mijoz `/auth/login` ga
    istalgan hajmdagi tana yuborishi mumkin edi: server uni TO'LIQ xotiraga
    o'qib, JSON'ga aylantirib, so'ng validatsiyaga berardi. Ya'ni bitta so'rov
    bilan xotira va CPU yeyish mumkin edi — bcrypt'ga yetib borishdan ham oldin.

IKKI CHEGARA, chunki yuklar TABIATAN har xil:
  · AUTH/VENDOR yo'llari — kichik JSON (telefon, PIN, OTP). Bu yerda katta tana
    HECH QACHON qonuniy emas, shu bois chegara TOR va rad etish ERTA bo'ladi.
  · Qolgan yo'llar — hisob-faktura rasmi `image_b64` sifatida JSON ichida keladi
    (schema'da `max_length=15_000_000`). Shu bois umumiy chegara undan yuqori,
    aks holda qonuniy kirim oqimi buzilardi.

⚠️  `Content-Length` ga YOLG'IZ tayanilmaydi: `Transfer-Encoding: chunked` da u
    umuman bo'lmaydi va mijoz uni yolg'on ham ko'rsatishi mumkin. Shuning uchun
    sarlavha ERTA rad etish uchun ishlatiladi, oqim esa BAYT-BAYT sanaladi va
    chegaradan oshgan zahoti uziladi.
"""
from __future__ import annotations

from starlette.datastructures import Headers
from starlette.types import ASGIApp, Message, Receive, Scope, Send

# Auth/vendor yuklari — kichik JSON. 8 KiB juda saxiy chegara.
AUTH_MAX_BYTES = 8 * 1024
# Umumiy chegara — `image_b64` (~15 MB) uchun joy qoldiradi.
DEFAULT_MAX_BYTES = 20 * 1024 * 1024

_AUTH_PREFIXES = ("/api/v1/auth", "/api/v1/admin")


def _limit_for(path: str) -> int:
    return AUTH_MAX_BYTES if path.startswith(_AUTH_PREFIXES) else DEFAULT_MAX_BYTES


class BodyLimitMiddleware:
    """Chegaradan oshgan tanani 413 bilan rad etadi — ilova kodiga YETIB BORMASDAN."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        limit = _limit_for(scope.get("path", ""))
        headers = Headers(scope=scope)
        declared = headers.get("content-length")
        if declared is not None:
            try:
                if int(declared) > limit:
                    await _too_large(send, limit)
                    return
            except ValueError:
                pass                      # buzuq sarlavha — oqim sanog'i baribir ushlaydi

        seen = 0
        too_big = False

        async def counting_receive() -> Message:
            nonlocal seen, too_big
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b"") or b"")
                if seen > limit:
                    too_big = True
                    # Oqimni uzamiz: ilova qolgan baytlarni KUTIB QOLMASIN.
                    return {"type": "http.disconnect"}
            return message

        wrapped_sent = False

        async def guarded_send(message: Message) -> None:
            nonlocal wrapped_sent
            if too_big and not wrapped_sent:
                wrapped_sent = True
                await _too_large(send, limit)
                return
            if too_big:
                return                    # javob allaqachon yuborilgan
            await send(message)

        await self.app(scope, counting_receive, guarded_send)
        if too_big and not wrapped_sent:
            wrapped_sent = True
            await _too_large(send, limit)


async def _too_large(send: Send, limit: int) -> None:
    body = (b'{"detail":"So\'rov tanasi juda katta (ko\'pi bilan '
            + str(limit).encode() + b' bayt)"}')
    await send({"type": "http.response.start", "status": 413,
                "headers": [(b"content-type", b"application/json"),
                            (b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})
