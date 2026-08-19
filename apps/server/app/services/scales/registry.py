"""Qo'llab-quvvatlanadigan brend/modellar va driver tanlash.
Ro'yxat tizim kengayishi bilan to'ldiriladi (barcha tarozilar deb va'da bermaymiz)."""
from app.services.scales.base import ScaleDriver
from app.services.scales.generic import GenericScaleDriver

# Brend -> qo'llab-quvvatlanadigan modellar
SUPPORTED: dict[str, list[str]] = {
    "CAS": ["CL5000", "CL5200", "CT100"],
    "DIGI": ["SM-100", "SM-5300"],
    "Mettler Toledo": ["bTwin", "3600"],
    "ACLAS": ["LS2", "PS1"],
}


def brands() -> list[dict]:
    return [{"brand": b, "models": m} for b, m in SUPPORTED.items()]


def is_supported(brand: str | None, model: str | None) -> bool:
    if not brand or brand not in SUPPORTED:
        return False
    return model in SUPPORTED[brand] if model else True


def resolve(want_brand: str | None, want_model: str | None) -> tuple[str, str]:
    """Avtomatik aniqlash so'ralganda mos brend/model qaytaradi (stub default: CAS/CL5000)."""
    if want_brand and want_brand in SUPPORTED:
        model = want_model if (want_model in SUPPORTED[want_brand]) else SUPPORTED[want_brand][0]
        return want_brand, model
    return "CAS", "CL5000"


def driver_for(brand: str | None) -> ScaleDriver:
    # Hozircha barcha brendlar umumiy stub-driver orqali; keyin brendga xos driverlar qo'shiladi.
    return GenericScaleDriver(brand or "generic")
