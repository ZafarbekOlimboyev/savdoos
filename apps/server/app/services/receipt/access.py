# -*- coding: utf-8 -*-
"""Hujjatni (chek / qaytarish) O'QISH qoidasi — chek endpointlari va chop etish jurnali uchun BITTA.

⚠️  YAGONA MANBA. `GET /sales/{id}/receipt` va `POST /print-jobs` bir hujjat uchun ikki
    xil qaror bersa, chop etish jurnali ko'rish taqiqlangan hujjatning MAVJUDLIGINI
    (200/404 farqi bilan) ochib qo'yardi. Shu bois ikkalasi shu funksiyalarni chaqiradi.
⚠️  Rad etish — doim 404 (begona do'kon, begona filial, o'chirilgan, ruxsatsiz):
    mavjudlik haqida oracle yo'q.
⚠️  MUALLIF ISTISNOSI (faqat O'Z hujjati, faqat chek/jurnal uchun):
      · `kassa.sell` bor, lekin `SALES_DOC_TIER` yo'q kassir — faqat O'ZI urgan sotuv
        chekini oladi. Onlayn chek faqat server DTO'sidan chiqadi: bu istisnosiz tarix
        ko'rishi yopilgan kassir o'zi sotgan xaridga chek bera olmasdi. Yangi narsa
        ochilmaydi — `POST /sales` javobi ayni raqam/summalarni unga allaqachon bergan.
        `GET /sales/{id}` (tarix) O'ZGARMAYDI.
      · biriktirilgan filiali nofaol/o'chirilgan kassir sotuvi `actor_branch` zaxira
        filialiga tushadi (ko'rinadigan to'plamdan TASHQARI) — o'z hujjati baribir
        o'qiladi. Boshqa kassirning o'sha filialdagi hujjati — 404 (doira kengaymaydi).
"""
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.orm import Session, lazyload

from app.core.deps import (FULL_ACCESS_ROLES, SALES_DOC_TIER, effective_permissions, has_any,
                           visible_branches)
from app.services.receipt import errors as E

RETURN_READ = ("qaytarishlar.view", "qaytarishlar.create")
OWN_SALE_READ = ("kassa.sell",)


def _perms(emp, db: Session):
    # `has_any` bir so'rovda bir necha marta — override'lar bir marta o'qiladi.
    return None if emp.role.code in FULL_ACCESS_ROLES else effective_permissions(emp, db)


def readable_sale(db: Session, emp, sale_id, *, check_perm: bool = True):
    """Chek — `SALES_DOC_TIER` + kompaniya + ko'rinadigan filial (`GET /sales/{id}` bilan AYNI);
    `kassa.sell` (tier'siz) — faqat O'Z sotuvi. Muallif o'z hujjatini filial doirasidan
    tashqarida ham o'qiydi (nofaol filial kassiri)."""
    from app.models.sales import Sale
    perms = _perms(emp, db)
    doc_tier = has_any(emp, db, SALES_DOC_TIER, perms)
    # `check_perm=False` ham tier'siz aktorni O'Z sotuviga cheklaydi (pastda) — darvoza
    # `kassa.sell` ni ham o'tkazadi, ya'ni bu cheklov endpointda ham shart.
    if check_perm and not doc_tier and not has_any(emp, db, OWN_SALE_READ, perms):
        raise HTTPException(404, E.SALE_NOT_FOUND)
    sale = (db.get(Sale, sale_id, options=[lazyload(Sale.items), lazyload(Sale.payments)])
            if sale_id is not None else None)
    if sale is None or sale.company_id != emp.company_id or sale.deleted_at is not None:
        raise HTTPException(404, E.SALE_NOT_FOUND)
    own = sale.cashier_id is not None and sale.cashier_id == emp.id
    if not doc_tier and not own:
        raise HTTPException(404, E.SALE_NOT_FOUND)
    vis = visible_branches(emp, db)
    if vis is not None and sale.branch_id not in vis and not own:
        raise HTTPException(404, E.SALE_NOT_FOUND)
    return sale


def readable_return(db: Session, emp, return_id, *, check_perm: bool = True):
    """Qaytarish — `qaytarishlar.view` (filial doirasida hammasi) yoki faqat
    `qaytarishlar.create` (faqat O'Z qaytarishi: kassir boshqa kassir pul qaytarganini
    ko'rmaydi). Muallif o'z qaytarishini filial doirasidan tashqarida ham o'qiydi."""
    from app.models.sales import Return
    if check_perm and not has_any(emp, db, RETURN_READ):
        raise HTTPException(404, E.RETURN_NOT_FOUND)
    # `lazyload`: qatorlar DTO'da ANIQ tartib bilan alohida o'qiladi — selectin ikki marta yuklardi.
    ret = (db.get(Return, return_id, options=[lazyload(Return.items)])
           if return_id is not None else None)
    if ret is None or ret.company_id != emp.company_id or ret.deleted_at is not None:
        raise HTTPException(404, E.RETURN_NOT_FOUND)
    own = ret.cashier_id is not None and ret.cashier_id == emp.id
    vis = visible_branches(emp, db)
    if vis is not None and ret.branch_id not in vis and not own:
        raise HTTPException(404, E.RETURN_NOT_FOUND)
    if not has_any(emp, db, ("qaytarishlar.view",)) and not own:
        raise HTTPException(404, E.RETURN_NOT_FOUND)
    return ret


def readable_doc(db: Session, emp, doc_type: str, doc_id):
    return (readable_sale(db, emp, doc_id) if doc_type == "SALE"
            else readable_return(db, emp, doc_id))
