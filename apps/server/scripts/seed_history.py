"""Test do'konga ORQAGA SANALGAN savdo tarixi (grafiklar, oylik hisobotlar to'lishi uchun).

Prod konteynerda ishga tushiriladi (DATABASE_URL avtomatik):
    railway ssh --service savdoos "cd /app/apps/server && python scripts/seed_history.py 'Sinov Dokon' 6"

Argumentlar:
    1) do'kon nomi (standart: "Sinov Dokon")
    2) necha oylik tarix (standart: 6)

demo_seed.seed_chunk'ni 30 kunlik bo'laklarda chaqiradi — eng eskisi setup=True
(kategoriya/mahsulot/xodim tayyorlaydi), oxirgisi finalize=True. Har savdo HAQIQIY
create_sale orqali (chek raqami, ombor ledger, foyda, qarz to'g'ri chiqadi).
Faqat TEST do'kon uchun ishlating — haqiqiy do'konga emas.
"""
import sys

from app.db.session import SessionLocal
from app.models.org import Company
from app.services.demo_seed import seed_chunk


def main() -> int:
    name = sys.argv[1] if len(sys.argv) > 1 else "Sinov Dokon"
    months = int(sys.argv[2]) if len(sys.argv) > 2 else 6
    days = months * 30

    db = SessionLocal()
    try:
        c = (
            db.query(Company)
            .filter(Company.name == name, Company.deleted_at.is_(None))
            .first()
        )
        if not c:
            print(f"XATO: '{name}' do'koni topilmadi.")
            return 1

        # 30 kunlik bo'laklar: [days..days-30], ..., [30..0]
        chunks = []
        f = days
        while f > 0:
            t = max(f - 30, 0)
            chunks.append((f, t))
            f = t

        print(f"'{name}' uchun {months} oy ({days} kun), {len(chunks)} bo'lak:")
        for i, (f, t) in enumerate(chunks):
            res = seed_chunk(
                db, c, f, t,
                setup=(i == 0),
                finalize=(i == len(chunks) - 1),
            )
            print(f"  [{i + 1}/{len(chunks)}] {f}->{t} kun: {res}")
        print("TAYYOR — tarix yuklandi.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
