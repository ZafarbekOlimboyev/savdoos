import math

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import app.models  # noqa: F401  (Base.metadata to'ldirish uchun)
from app.api.v1 import api_router
from app.core.config import settings

# Production'da interaktiv docs/OpenAPI ochiq turmasin (endpointlar ro'yxati sizmasin)
_docs = None if settings.is_production else "/docs"
app = FastAPI(
    title="SavdoOS API", version="0.1.0",
    docs_url=_docs, redoc_url=None if settings.is_production else "/redoc",
    openapi_url=None if settings.is_production else "/openapi.json",
)

# ── Loglash: naqd hodisalari Railway loglarida KO'RINSIN ────────────────────
# uvicorn faqat O'Z logger'larini sozlaydi; ilova logger'lari uchun root'da handler bo'lmasa
# INFO darajasidagi yozuvlar YO'QOLADI (WARNING lastResort orqali stderr'ga chiqadi, INFO esa
# umuman chiqmaydi). Naqd kuzatuvi shunga tayanib qololmaydi — aniq sozlaymiz.
import logging as _logging
import os as _os

_logging.basicConfig(
    level=_os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
# `savdoos.cash` — bitta qatorli JSON hodisalar (app/services/cash/observability.py).
_logging.getLogger("savdoos.cash").setLevel(_logging.INFO)

# ── FAIL-CLOSED: production'da baza SQLite bo'lib qolmasin ──────────────────
# Railway'da DATABASE_URL yo'qolsa (servis uzilgan, havola buzilgan, muhit qayta yaratilgan)
# ilova ilgari konteyner ichidagi vaqtinchalik SQLite faylga o'tib ketardi: savdolar keyingi
# deploy'da YO'QOLARDI va hech kim buni sezmasdi. Bu — JIM ma'lumot yo'qotish.
# Endi bunday holat ishga tushishni TO'XTATADI: yiqilgan servis jimgina yolg'on ishlashdan afzal.
if settings.production_on_sqlite:
    raise RuntimeError(
        "DATABASE_URL berilmagan (yoki SQLite) — LEKIN muhit PRODUCTION deb aniqlandi. "
        "Konteyner ichidagi SQLite fayl har deploy'da yo'qoladi, ya'ni savdolar YO'QOLARDI. "
        "Railway'da Postgres DATABASE_URL o'zgaruvchisini tekshiring. "
        "(Ataylab SQLite kerak bo'lsa — APP_ENV=dev bering.)")

# Xavfsizlik: standart (ochiq) JWT siri bilan token soxtalashtirish mumkin.
# Production'da (Postgres) FAIL-CLOSED — ishga tushmaydi. Lokal dev'da (SQLite) faqat ogohlantirish.
if settings.insecure_secret:
    import logging
    if settings.is_production:
        raise RuntimeError(
            "SECRET_KEY o'rnatilmagan! Production'da standart JWT kalit bilan ishga tushib bo'lmaydi "
            "(token soxtalashtirilishi mumkin). Railway/env orqali SECRET_KEY bering.")
    logging.getLogger("uvicorn.error").warning(
        "XAVFSIZLIK OGOHLANTIRISHI: standart JWT SECRET_KEY ishlatilmoqda — productionda SECRET_KEY bering!")

# Desktop ilova file:// (Origin: null) orqali ulanadi — "*" ruxsat berilganda
# credentials o'chiriladi (CORS spetsifikatsiyasi talabi). Auth Bearer header orqali.
_origins = settings.cors_list
_allow_all = "*" in _origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if _allow_all else _origins,
    allow_credentials=not _allow_all,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api/v1")


# Validatsiya xatosida QAYTARILMAYDIGAN maydonlar.
#
# ⚠️  Pydantic v2 har xato yozuviga `input` — ya'ni YUBORILGAN QIYMATNI — qo'shadi.
#     `/auth/login` ga qisqa PIN yuborilса, 422 javobi o'sha PIN'ni AYNAN qaytarardi.
#     Qiymat yuboruvchining o'ziga qaytadi (uchinchi tomonga oqmaydi), lekin u
#     javob tanasi bilan birga proxy loglariga, xato-kuzatuv tizimlariga va mijoz
#     tomonidagi diagnostikaga tushishi mumkin — kredensial u yerlarda turmasligi kerak.
_SECRET_FIELDS = frozenset({
    "pin", "password", "old_password", "new_password", "passphrase",
    "token", "access_token", "refresh_token", "secret", "secret_key",
    "otp", "code", "key", "vendor_key", "x_vendor_key", "api_key",
})


@app.exception_handler(RequestValidationError)
async def _validation_handler(request: Request, exc: RequestValidationError):
    # Cheksiz/NaN kabi qiymatlar echo qilinganda JSON serializatsiya 500 bermasligi uchun tozalaymiz
    def _san(v):
        if isinstance(v, float) and not math.isfinite(v):
            return str(v)
        if isinstance(v, dict):
            return {k: _san(x) for k, x in v.items()}
        if isinstance(v, (list, tuple)):
            return [_san(x) for x in v]
        return v

    def _sensitive(loc) -> bool:
        return any(isinstance(p, str) and p.lower() in _SECRET_FIELDS for p in (loc or ()))

    out = []
    for err in exc.errors():
        e = dict(err)
        if _sensitive(e.get("loc")):
            e.pop("input", None)          # yuborilgan qiymat QAYTARILMAYDI
            e.pop("ctx", None)            # ba'zi validatorlar qiymatni ctx'ga ham qo'yadi
        else:
            e = _san(e)
        out.append(e)
    return JSONResponse(status_code=422, content={"detail": out})


@app.get("/")
def root():
    return {"service": "SavdoOS API", "docs": "/docs", "health": "/api/v1/health"}


@app.get("/privacy", include_in_schema=False)
def privacy_policy():
    """Maxfiylik siyosati — Google Play ro'yxati uchun ochiq sahifa."""
    import os

    from fastapi.responses import FileResponse
    path = os.path.join(os.path.dirname(__file__), "static", "privacy.html")
    return FileResponse(path, media_type="text/html")
