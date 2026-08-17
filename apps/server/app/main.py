from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import app.models  # noqa: F401  (Base.metadata to'ldirish uchun)
from app.api.v1 import api_router
from app.core.config import settings

app = FastAPI(title="SavdoOS API", version="0.1.0")

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


@app.get("/")
def root():
    return {"service": "SavdoOS API", "docs": "/docs", "health": "/api/v1/health"}
