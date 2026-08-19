"""Scale Driver abstraksiyasi. SavdoOS yadrosi brendga bog'lanmaydi —
yangi tarozi qo'shish uchun faqat yangi ScaleDriver yoziladi."""
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class Conn:
    """Ulanish parametrlari (LAN yoki USB/COM)."""
    connection_type: str            # lan | usb
    host: str | None = None
    port: int | None = None
    com_port: str | None = None
    baud: int | None = None


@dataclass
class ScaleProduct:
    plu: str
    name: str
    price_per_kg: float


@dataclass
class ProbeResult:
    ok: bool
    brand: str | None = None
    model: str | None = None
    supported: bool = True
    message: str = ""


class ScaleDriver(ABC):
    brand: str = "generic"

    @abstractmethod
    def probe(self, conn: Conn, want_brand: str | None = None, want_model: str | None = None) -> ProbeResult:
        """Qurilma bilan aloqa o'rnatib, brend/modelni aniqlaydi."""

    @abstractmethod
    def sync_products(self, conn: Conn, products: list[ScaleProduct]) -> int:
        """Mahsulotlarni (PLU/nom/kg-narx) taroziga yuboradi; yuborilgan sonini qaytaradi."""
