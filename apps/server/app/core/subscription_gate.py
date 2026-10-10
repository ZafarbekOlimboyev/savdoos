# -*- coding: utf-8 -*-
"""Obuna majburlashi — SERVER chegarasida (Phase 6A/2.5).

⚠️  UI da tugmani yashirish MAJBURLASH EMAS. Qaror shu yerda, marshrut darvozasida
    qabul qilinadi va `evaluate_subscription_access` AUTHORITATIVE bo'lib qoladi:
    holat HAR SO'ROVDA bazadagi qatordan qayta hisoblanadi, ya'ni fon vazifasi
    kechiksa ham muddati o'tgan ijarachi yoza olmaydi.

QAYERGA ULANADI
===============
`main.py` da `include_router(api_router, prefix="/api/v1", dependencies=[...])` —
BITTA joy. Har marshrutga alohida ulanmaydi: 175 ta joyni qo'lda to'g'ri tutib
turish mumkin emas, va unutilgan bittasi jimgina teshik bo'lardi. O'rniga tasnif
`subscription_routes.SUBSCRIPTION_ROUTE_ACTIONS` da, qamrovni esa test qulflaydi.

NEGA RUXSAT KODI BO'YICHA EMAS
==============================
⚠️  Ayni ruxsat kodi o'qish va yozuvda birga ishlatiladi (`hisobot.view` ->
    `GET /reports/*` VA `POST /cash/ops`). Kod bo'yicha xaritalash ikki xatodan
    birini berardi: o'qishlarni ham to'sish yoki yozuvlarni o'tkazib yuborish.

FAIL CLOSED
===========
⚠️  Reestrda YO'Q marshrut: o'zgartiruvchi metodlar (POST/PUT/PATCH/DELETE)
    TO'SILADI. Ya'ni yangi endpoint qo'shilib tasniflanmasa, u majburlashdan
    sirg'alib o'tmaydi — eng yomoni 403 beradi va test uni darhol qizil qiladi.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.security import decode_token
from app.core.subscription_routes import (ALLOW_READ, BLOCK_BUSINESS_WRITE,
                                          CLASS_TO_CATEGORY, ERROR_CODE,
                                          HISTORICAL_BUILD_ERROR_CODE,
                                          HISTORICAL_BUILD_MESSAGE,
                                          NO_TENANT_CONTEXT, OUT_OF_SCOPE_SYSTEM,
                                          SUBSCRIPTION_ROUTE_ACTIONS,
                                          blocked_during_historical_build)
from app.db.session import get_db
from app.models.subscription import Subscription
from app.services.subscription import policy
from app.services.subscription.state import evaluate_subscription_access

PREFIX = "/api/v1"
#: Holat o'zgartira oladigan metodlar — tasnifsiz marshrut uchun standart TO'SIQ.
MUTATING = frozenset({"POST", "PUT", "PATCH", "DELETE"})

#: Operator ko'radigan YAGONA matn. Sabab ochilmaydi (qaysi tarif, qancha qarz —
#: bular hisob sahifasining ishi), lekin nima qilish kerakligi aytiladi.
MESSAGE = ("Obuna cheklangan — yangi amallar vaqtincha to'xtatilgan. "
           "Ma'lumotlaringiz ochiq; davom etish uchun obunani yangilang.")


#: `id(APIRoute)` -> TO'LIQ yo'l shabloni (`/api/v1` siz). Bir marta quriladi.
#  ⚠️  `request.scope["route"].path` YETARLI EMAS: FastAPI `include_router` ni
#      DANGASA saqlaydi (`_IncludedRouter`) va marshrut obyektidagi yo'l ichki,
#      prefikssiz bo'ladi — `POST /api/v1/sales` uchun u `/sales` ko'rinadi, ichma-ich
#      include'da esa yana qisqaroq. Shu bois prefikslar `app.routes` daraxtidan
#      yig'iladi. Ayni usul repo testlarida ham ishlatiladi
#      (`tests/test_mobile_permission_matrix.py:_walk`).
_FULL_PATHS: dict[int, str] = {}
#: `id(APIRoute)` -> metodlar (qamrov tekshiruvi uchun).
_METHODS: dict[int, frozenset] = {}


def _walk(routes, prefix: str) -> None:
    from fastapi.routing import APIRoute
    for r in routes:
        if isinstance(r, APIRoute):
            _FULL_PATHS[id(r)] = prefix + r.path
            _METHODS[id(r)] = frozenset(r.methods or ())
        elif hasattr(r, "original_router") and hasattr(r, "include_context"):
            _walk(r.original_router.routes, prefix + (r.include_context.prefix or ""))


def _full_path(request: Request) -> str | None:
    route = request.scope.get("route")
    if route is None:
        return None
    if not _FULL_PATHS:
        _walk(request.app.routes, "")
    return _FULL_PATHS.get(id(route))


def route_key(request: Request) -> tuple[str, str] | None:
    """(METOD, `/api/v1` siz to'liq yo'l shabloni). Aniqlanmasa — `None`."""
    path = _full_path(request)
    if not isinstance(path, str) or not path.startswith(PREFIX + "/"):
        return None
    return (request.method, path[len(PREFIX):])


def classify_key(key: tuple[str, str] | None, method: str) -> str | None:
    """Sof qaror: kalit -> sinf. Reestrda yo'q bo'lsa — FAIL CLOSED."""
    if key is None or key in NO_TENANT_CONTEXT:
        return None
    action = SUBSCRIPTION_ROUTE_ACTIONS.get(key)
    if action is not None:
        return action
    #  ⚠️  TASNIFSIZ MARSHRUT — METODDAN QAT'I NAZAR TO'SILADI. HTTP metodi
    #      yozuvni ISBOTLAMAYDI: `GET /payments/qr/{txn_id}` `commit()` qiladi,
    #      `POST /products/import/preview` esa hech nima yozmaydi. Ruxsat kodi ham
    #      isbot emas — ayni kod o'qish va yozuvda birga ishlatiladi. Shu bois
    #      «bilmayman» holatida taxmin qilinmaydi: to'siladi.
    #      Amalda bu holatga yetib ham bo'lmaydi — `verify_route_coverage()` ishga
    #      tushishda yiqiladi. Bu ikkinchi qatlam.
    return BLOCK_BUSINESS_WRITE


def classify(request: Request) -> str | None:
    return classify_key(route_key(request), request.method)


def verify_route_coverage(app) -> None:
    """Ishga tushishda: HAR BIR ijarachi marshruti ANIQ tasniflangan bo'lsin.

    ⚠️  Bu `required_schema` darvozasi bilan AYNI falsafada: yetishmasa ishga
        tushish YIQILADI. Sababi — tasnifsiz marshrut jimgina majburlashdan
        chetda qolishi mumkin bo'lgan YAGONA yo'l, va uni ish vaqtida topish
        «kimdir 403 oldi» degan shikoyat bilan bo'lardi. CI esa buni allaqachon
        `tests/test_subscription_enforcement.py` bilan ushlaydi, ya'ni bu holat
        deploy'ga yetib bormaydi.
    """
    _FULL_PATHS.clear()
    _walk(app.routes, "")
    live = {(m, p[len(PREFIX):]) for r_id, p in _FULL_PATHS.items()
            for m in _METHODS.get(r_id, ()) if p.startswith(PREFIX + "/")}
    yoq = sorted(live - set(SUBSCRIPTION_ROUTE_ACTIONS) - NO_TENANT_CONTEXT)
    if yoq:
        raise RuntimeError(
            "obuna tasnifi yo'q marshrut(lar) — `app/core/subscription_routes.py` "
            f"ga yozing: {yoq}")


def _company_id(authorization: str | None) -> uuid.UUID | None:
    """Token'dan kompaniya. Token yaroqsiz bo'lsa `None`.

    ⚠️  Bu AUTENTIFIKATSIYA emas: token'ni marshrutning o'z `get_current_employee`
        darvozasi tekshiradi va yaroqsiz bo'lsa 401 beradi. Bu yerda u faqat
        QAYSI ijarachining obunasini baholash kerakligini aytadi — shu bois
        yaroqsiz token'da jim qaytamiz va 401 ni auth qatlamiga qoldiramiz.
    """
    if not authorization or not authorization.startswith("Bearer "):
        return None
    try:
        payload = decode_token(authorization.split(" ", 1)[1])
        return uuid.UUID(str(payload["company_id"]))
    except Exception:      # noqa: BLE001 — yaroqsiz/eski token: qaror auth qatlamida
        return None


def subscription_gate(request: Request,
                      authorization: str | None = Header(default=None),
                      db: Session = Depends(get_db)) -> None:
    action = classify(request)
    if action is None or action == OUT_OF_SCOPE_SYSTEM:
        return
    #  ═══ DEMO-TARIX QURILISHI — LIVE OQIM YOPIQ ══════════════════════
    #  NEGA SHU JOYDA, ikki chegaradan ANIQ orada:
    #    · `OUT_OF_SCOPE_SYSTEM` erta qaytishidan KEYIN — imtiyozli tarixiy yuza
    #      (`POST /historical/events`, `POST /reports/history/seed`) aynan shu
    #      sinfda, ya'ni blok uni O'ZI chetlab o'tadi va u OCHIQ qoladi.
    #    · `ALWAYS_ALLOWED`/`SAFE_RECOVERY` erta qaytishidan OLDIN — aks holda
    #      `POST /shifts/{id}/close` (`SAFE_RECOVERY`) blokdan sirg'alib o'tardi
    #      va POS klienti TARIXIY smenani yopib, rejani buzishi mumkin edi.
    #  O'qish sinflari predikatga TUSHMAYDI (`HISTORICAL_BUILD_CANDIDATES`),
    #  shu bois o'qish yo'llariga qo'shimcha so'rov YUKLANMAYDI.
    if blocked_during_historical_build(action, route_key(request)):
        _cid = _company_id(authorization)
        #  Token yo'q/yaroqsiz -> jim qaytamiz: 401 ni marshrutning o'z auth
        #  qatlami beradi (obuna darvozasi bilan AYNI fail-open mulohazasi).
        if _cid is not None:
            from app.services.cash import tenant as _cash_tenant
            if _cash_tenant.is_historical_build(db, _cid):
                raise HTTPException(
                    status.HTTP_409_CONFLICT, HISTORICAL_BUILD_MESSAGE,
                    headers={"X-Error-Code": HISTORICAL_BUILD_ERROR_CODE})
    category = CLASS_TO_CATEGORY[action]
    #  O'qish, hisobot, hisob-kitob va smena yopish — obunadan QAT'I NAZAR ochiq.
    #  Bu tekshiruv `policy` matritsasidan chiqadi, bu yerda qayta yozilmaydi.
    if category in policy.ALWAYS_ALLOWED or category in policy.SAFE_RECOVERY:
        return
    company_id = _company_id(authorization)
    if company_id is None:
        return
    sub = (db.query(Subscription)
           .filter(Subscription.company_id == company_id)
           .one_or_none())
    access = evaluate_subscription_access(sub, datetime.now(timezone.utc))
    if policy.is_allowed(category, access.effective_status, managed=access.managed):
        return
    #  ⚠️  BARQAROR KOD sarlavhada: klient uni matn bo'yicha emas, kod bo'yicha
    #      tanisin (matn tarjima qilinadi, kod — yo'q).
    raise HTTPException(status.HTTP_403_FORBIDDEN, MESSAGE,
                        headers={"X-Error-Code": ERROR_CODE})
