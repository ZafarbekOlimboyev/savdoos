"""Dev uchun jadvallarni yaratish (Alembic o'rniga tez yo'l)."""
import app.models  # noqa: F401
from app.db.base import Base
from app.db.session import engine


def main():
    Base.metadata.create_all(engine)
    print("[OK] Jadvallar yaratildi")


if __name__ == "__main__":
    main()
