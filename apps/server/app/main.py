import math

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import app.models  # noqa: F401  (Base.metadata to'ldirish uchun)
from app.api.v1 import api_router
from app.core.config import settings

app = FastAPI(title="SavdoOS API", version="0.1.0")

# Xavfsizlik: production'da standart JWT sirini ishlatmang (Railway env: SECRET_KEY)
if settings.secret_key == "dev-secret-change-me":
    import logging
    logging.getLogger("uvicorn.error").warning(
        "XAVFSIZLIK OGOHLANTIRISHI: standart JWT SECRET_KEY ishlatilmoqda — productionda .env/Railway env orqali o'zgartiring!")

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
    return JSONResponse(status_code=422, content={"detail": _san(exc.errors())})


@app.get("/")
def root():
    return {"service": "SavdoOS API", "docs": "/docs", "health": "/api/v1/health"}
