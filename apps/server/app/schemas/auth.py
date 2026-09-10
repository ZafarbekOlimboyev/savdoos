import uuid

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class LoginPin(BaseModel):
    # employee_id MAJBURIY — server aynan BITTA xodim hash'ini tekshiradi.
    # Ilgari maydon yo'q edi va server PIN'ni do'kondagi HAR BIR xodim bilan
    # qiyoslardi: bu autentifikatsiyasiz DoS yo'li edi (N x bcrypt).
    # Ixtiyoriy qilinsa eski xavfli yo'l ochiq qolardi — shu bois MAJBURIY.
    employee_id: uuid.UUID
    pin: str = Field(min_length=4, max_length=12)  # bo'sh PIN bypass'iga qarshi
    company_code: str | None = None   # ixtiyoriy qo'shimcha tekshiruv (mos kelmasa — umumiy xato)


class LoginPassword(BaseModel):
    phone: str = Field(min_length=4)
    password: str = Field(min_length=1)


class ChangePassword(BaseModel):
    old_password: str | None = None
    new_password: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    employee: "EmployeeOut"


class PinRosterItem(BaseModel):
    """POS kassir tanlash ro'yxati elementi.

    Ataylab QISQA: telefon/rol yo'q. Bu ro'yxat POS qurilmasida keshlanadi,
    shuning uchun unda faqat ekranга kerak bo'lgan narsa turadi."""
    id: uuid.UUID
    full_name: str
    branch_name: str | None = None


class EmployeeOut(ORMModel):
    id: uuid.UUID
    full_name: str
    phone: str | None = None
    role_code: str
    role_name: str
    status: str
    company_name: str | None = None   # do'kon nomi (mobil eksport sarlavhasi va h.k.)
    # ⚠️  Qurilma sozlamasini O'ZINI-O'ZI TUZATISH uchun. Do'kon kodi ilgari faqat
    #     qo'lda kiritilardi va hech qachon tekshirilmasdi: xato terilgan kod bilan
    #     parol logini baribir o'tardi, keyin esa HAR BIR PIN login o'sha xato kod
    #     bilan ketib, doim 401 berardi. Endi POS kodni autentifikatsiyalangan
    #     javobdan oladi. (Kod maxfiy emas — u chaqiruvchining O'Z do'koni kodi.)
    company_code: str | None = None
    branch_name: str | None = None    # xodim filiali (POS chekda haqiqiy filial nomi)
    permissions: list[str] = []


Token.model_rebuild()
