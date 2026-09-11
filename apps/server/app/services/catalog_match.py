# -*- coding: utf-8 -*-
"""1С Cutover V2 — MAHSULOT MOSLASHTIRISH (deterministik, YOZUVSIZ).

Bu modul BAZAGA HECH NARSA YOZMAYDI. U faqat manba qatorini mavjud katalogga
solishtirib, qaysi mahsulot ekanini (yoki ekanini aniqlab bo'lmasligini) aytadi.

MOSLASHTIRISH DARAJALARI (yuqoridan pastga; yuqorisi topilsa quyisi UMUMAN
ko'rilmaydi):

  1. source_system + external_id   — 1С «Ссылка»/GUID. Nomdan MUSTAQIL, shu bois
                                     nom o'zgarsa ham AYNI mahsulotga tushadi.
  2. article_code                  — do'kon ichida noyob bo'lsa
  3. barkod                        — manba barkodi AYNAN bitta mahsulotga tegishli
  4. normallashgan nom             — IKKALA tomonda ham noyob bo'lsa
  5. —                             — AMBIGUOUS

QAT'IY QOIDA: turli darajalar TURLI mahsulotni ko'rsatsa — natija AMBIGUOUS.
Yuqori daraja "yutadi" degan qoida YO'Q: ziddiyat ma'lumot buzuqligining alomati
va uni jimgina hal qilish noto'g'ri mahsulotning narxini o'zgartirishga olib kelardi.

⚠️  O'CHIRILGAN MAHSULOT: tashqi identifikatsiya noyobligi soft-delete'dan OMON
    QOLADI (ux_products_external_identity da `deleted_at IS NULL` filtri yo'q).
    Shu bois o'chirilgan mahsulotga mos kelgan qator YANGI deb tasniflanmaydi —
    u DELETED_MATCH bo'ladi va operator qaror qabul qiladi. Aks holda bitta 1С
    GUID'i ikkita SavdoOS mahsulotiga bo'linib, tarix ikkiga ajralardi.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from enum import Enum


class MatchLevel(str, Enum):
    EXTERNAL_ID = "external_id"
    ARTICLE = "article"
    BARCODE = "barcode"
    NAME = "name"
    NONE = "none"


class MatchOutcome(str, Enum):
    MATCHED = "matched"            # bitta faol mahsulot aniq topildi
    DELETED_MATCH = "deleted_match"  # topildi, lekin O'CHIRILGAN — operator qarori kerak
    NEW = "new"                    # hech qanday dalil topilmadi
    AMBIGUOUS = "ambiguous"        # bir nechta nomzod yoki darajalar ziddiyati


def norm_key(name) -> str:
    """Nom bo'yicha moslashtirish kaliti — registr/probel/Unicode shakldan xoli."""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", str(name or ""))).strip().casefold()


def norm_barcode(v) -> str | None:
    """Backend qoidasining AYNI nusxasi: faqat raqamlar, uzunlik 6-14."""
    d = re.sub(r"\D", "", str(v or ""))
    return d if 6 <= len(d) <= 14 else None


@dataclass
class CatalogIndex:
    """Katalogning YOZUVSIZ ko'rinishi — bir marta quriladi, ko'p qator uchun ishlatiladi.

    Barcha xaritalar `product_id` ga olib boradi. `deleted` to'plami o'chirilgan
    mahsulotlarni belgilaydi — moslashtirish ularni TOPADI, lekin natija
    DELETED_MATCH bo'ladi.
    """
    by_external: dict[tuple[str, str], str] = field(default_factory=dict)
    by_article: dict[str, str] = field(default_factory=dict)
    by_barcode: dict[str, str] = field(default_factory=dict)
    by_name: dict[str, str] = field(default_factory=dict)
    # Kalit BIR NECHTA mahsulotга to'g'ri kelgan bo'lsa — u ISHONCHSIZ, ishlatilmaydi.
    ambiguous_article: set[str] = field(default_factory=set)
    ambiguous_barcode: set[str] = field(default_factory=set)
    ambiguous_name: set[str] = field(default_factory=set)
    deleted: set[str] = field(default_factory=set)
    products: dict[str, dict] = field(default_factory=dict)

    @classmethod
    def build(cls, rows, barcodes) -> "CatalogIndex":
        """`rows` — mahsulot lug'atlari; `barcodes` — (product_id, barcode) juftliklari.

        Mahsulot lug'atida kutiladigan kalitlar: id, name, article_code, source_system,
        external_id, deleted (bool) va solishtirish uchun qolgan maydonlar.
        """
        ix = cls()
        for r in rows:
            pid = str(r["id"])
            ix.products[pid] = r
            if r.get("deleted"):
                ix.deleted.add(pid)
            ss, ext = r.get("source_system"), r.get("external_id")
            if ss and ext:
                # DB-darajasida noyob (ux_products_external_identity) — to'qnashuv bo'lmasligi kerak.
                ix.by_external[(str(ss), str(ext))] = pid
            _put(ix.by_article, ix.ambiguous_article, (r.get("article_code") or "").strip(), pid)
            _put(ix.by_name, ix.ambiguous_name, norm_key(r.get("name")), pid)
        for pid, bc in barcodes:
            _put(ix.by_barcode, ix.ambiguous_barcode, str(bc), str(pid))
        return ix


def _put(store: dict, bad: set, key, pid: str) -> None:
    """Kalitni qo'shadi; ikkinchi marta uchrasa — kalit ISHONCHSIZ deb belgilanadi."""
    if not key:
        return
    prev = store.get(key)
    if prev is not None and prev != pid:
        bad.add(key)           # ikki xil mahsulot bir kalitda -> bu kalit bilan moslashtirilmaydi
        return
    store[key] = pid


@dataclass
class MatchResult:
    outcome: MatchOutcome
    product_id: str | None = None
    level: MatchLevel = MatchLevel.NONE
    # Nima uchun shunday qaror qilingani — hisobotда va audit'da ko'rinadi.
    evidence: list[str] = field(default_factory=list)
    conflict: list[str] = field(default_factory=list)


def match_row(row: dict, ix: CatalogIndex, source_system: str = "1c") -> MatchResult:
    """Bitta manba qatorini katalogga solishtiradi. HECH NARSA YOZMAYDI."""
    hits: list[tuple[MatchLevel, str]] = []
    evidence: list[str] = []
    ambiguous_reason: list[str] = []

    ext = (row.get("external_id") or "").strip()
    if ext:
        pid = ix.by_external.get((source_system, ext))
        if pid:
            hits.append((MatchLevel.EXTERNAL_ID, pid))
            evidence.append(f"external_id={ext}")

    art = (row.get("article") or "").strip()
    if art:
        if art in ix.ambiguous_article:
            ambiguous_reason.append(f"artikul {art} bir nechta mahsulotда")
        else:
            pid = ix.by_article.get(art)
            if pid:
                hits.append((MatchLevel.ARTICLE, pid))
                evidence.append(f"article={art}")

    for raw in (row.get("barcodes") or []):
        bc = norm_barcode(raw)
        if not bc:
            continue
        if bc in ix.ambiguous_barcode:
            ambiguous_reason.append(f"barkod {bc} bir nechta mahsulotда")
            continue
        pid = ix.by_barcode.get(bc)
        if pid:
            hits.append((MatchLevel.BARCODE, pid))
            evidence.append(f"barcode={bc}")

    nm = norm_key(row.get("name"))
    if nm:
        if nm in ix.ambiguous_name:
            ambiguous_reason.append(f"nom «{row.get('name')}» bir nechta mahsulotда")
        else:
            pid = ix.by_name.get(nm)
            if pid:
                hits.append((MatchLevel.NAME, pid))
                evidence.append(f"name={nm}")

    if not hits:
        # Ishonchsiz kalitlar bo'lgani "yangi" degani EMAS — mahsulot bor bo'lishi mumkin,
        # lekin qaysi biri ekanini ayta olmaymiz.
        if ambiguous_reason:
            return MatchResult(MatchOutcome.AMBIGUOUS, None, MatchLevel.NONE,
                               evidence, ambiguous_reason)
        return MatchResult(MatchOutcome.NEW, None, MatchLevel.NONE, evidence)

    distinct = {pid for _, pid in hits}
    if len(distinct) > 1:
        # ZIDDIYAT: dalillar turli mahsulotni ko'rsatmoqda. Yuqori daraja "yutmaydi" —
        # bu ma'lumot buzuqligining alomati va jimgina tanlash noto'g'ri mahsulotning
        # narxini o'zgartirishga olib kelardi.
        by_lvl = {}
        for lvl, pid in hits:
            by_lvl.setdefault(pid, []).append(lvl.value)
        return MatchResult(
            MatchOutcome.AMBIGUOUS, None, MatchLevel.NONE, evidence,
            [f"dalillar ziddiyati: " + "; ".join(f"{p}<-{'+'.join(v)}" for p, v in by_lvl.items())]
            + ambiguous_reason)

    pid = distinct.pop()
    level = min((lvl for lvl, _ in hits), key=_LEVEL_ORDER.index)
    if pid in ix.deleted:
        # Tashqi identifikatsiya soft-delete'dan omon qoladi -> ikkinchi mahsulot YARATILMAYDI.
        return MatchResult(MatchOutcome.DELETED_MATCH, pid, level, evidence, ambiguous_reason)
    return MatchResult(MatchOutcome.MATCHED, pid, level, evidence, ambiguous_reason)


_LEVEL_ORDER = [MatchLevel.EXTERNAL_ID, MatchLevel.ARTICLE, MatchLevel.BARCODE,
                MatchLevel.NAME, MatchLevel.NONE]
