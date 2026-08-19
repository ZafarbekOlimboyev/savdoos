"""Umumiy (stub) driver — apparat I/O hali ulanmagan.

DIQQAT: real qurilma bilan TCP/serial aloqa shu yerda amalga oshiriladi.
Hozircha ulanish parametrlari to'g'ri bo'lsa muvaffaqiyat qaytaradi (arxitektura tayyor,
haqiqiy protokol driver kelganda qo'shiladi). Yadro kodi o'zgarmaydi."""
from app.services.scales.base import Conn, ProbeResult, ScaleDriver, ScaleProduct


class GenericScaleDriver(ScaleDriver):
    def __init__(self, brand: str = "generic"):
        self.brand = brand

    def probe(self, conn: Conn, want_brand=None, want_model=None) -> ProbeResult:
        if conn.connection_type == "lan":
            if not conn.host:
                return ProbeResult(ok=False, message="IP manzil ko'rsatilmagan")
        else:
            if not conn.com_port:
                return ProbeResult(ok=False, message="COM port tanlanmagan")
        # Real driver bu yerda qurilmadan brend/modelni o'qiydi. Stub: so'ralganini tasdiqlaydi.
        from app.services.scales.registry import resolve, is_supported
        brand, model = resolve(want_brand, want_model)
        return ProbeResult(ok=True, brand=brand, model=model, supported=is_supported(brand, model))

    def sync_products(self, conn: Conn, products: list[ScaleProduct]) -> int:
        # Real driver bu yerda har PLU/nom/narxni qurilma protokoli bo'yicha yuboradi.
        return len(products)
