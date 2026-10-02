# -*- coding: utf-8 -*-
"""NORMALLASHTIRILGAN DISCOVERY GRAFI — `binos-1c-metadata-v1` ning o'qishga qulay shakli.

⚠️ GRAFDA BIZNES TALQINI BO'LMAYDI. U «NIMA BOR» ni tasvirlaydi, «NIMA MA'NOSI» ni EMAS.
⚠️ Grafda nishon, ishonch darajasi, xarita YO'Q — ular boshqa hujjatlarning ishi. Bu yerda
   «bu maydon shu maydonga to'g'ri keladi» degan da'vo YOZILMAYDI. Graf faqat hujjatda
   AYTILGAN narsani qirralarga aylantiradi, bir bayt ham qo'shmaydi.
⚠️ Graf qurilishi TASDIQ EMAS: obyekt grafda turgani uning mazmuni to'g'ri yoki ko'chirishga
   yaroqli ekanini ISBOTLAMAYDI.

NEGA GRAF KERAK. Inventarizatsiya hujjati ichma-ich (obyekt → bo'lim → maydon), ya'ni
«kim shu obyektga havola qiladi?» degan savolga javob berish uchun uni har marta to'liq
kezib chiqish kerak bo'ladi. Graf shu savollarni bir marta normallashtiradi va javobni
DETERMINISTIK tartibda beradi.

MANZIL SHARTNOMASI (nuqta — ota-bola ajratuvchisi):
    <obyekt>                      obyektning to'liq nomi, hujjatdan kelgan MA'LUMOT
    <obyekt>.<maydon>             obyekt darajasidagi maydon
    <obyekt>.<bo'lim>             jadval bo'limi
    <obyekt>.<bo'lim>.<maydon>    jadval bo'limi ichidagi maydon
`FieldNode.path` — maydonning obyekt ICHIDAGI yo'li: `F1` yoki `ABCD.F1` (to'qima misol).
Nomda nuqta bo'lmasligini `metadata._ident` kafolatlaydi, shu bois manzil bir xil o'qiladi.

QIRRA YO'NALISHI (`source` —(`relationship_type`)→ `target`):
    references          maydon EGASI obyekt → havola qilingan obyekt (`source_field` = path)
    attribute_of        maydon manzili → egasi (obyekt yoki jadval bo'limi)
    dimension_of        o'lchov manzili → egasi obyekt
    resource_of         resurs manzili → egasi obyekt
    tabular_section_of  bo'lim manzili → egasi obyekt
    enum_of             sanab o'tilgan qiymat manzili → egasi obyekt

DETERMINIZM: hamma tuple tartiblangan (obyektlar `full_name` bo'yicha, maydonlar `path`
bo'yicha, qirralar to'liq kalit bo'yicha). Bir xil kirish — AYNAN bir xil graf.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property

from .metadata import FIELD_LISTS, HIERARCHICAL, MetadataError, validate_metadata
from .schema import SOURCE_KINDS

#: Ruxsat etilgan qirra turlari. Yangi tur qo'shish — shartnoma o'zgarishi.
RELATIONSHIP_TYPES = ("attribute_of", "dimension_of", "enum_of", "references",
                      "resource_of", "tabular_section_of")

#: Obyekt darajasidagi ro'yxat → qirra turi. `FIELD_LISTS` tartibiga bog'langan.
_LIST_RELATIONSHIP = {"attributes": "attribute_of",
                      "dimensions": "dimension_of",
                      "resources": "resource_of"}

PATH_SEP = "."


@dataclass(frozen=True)
class FieldNode:
    """Bitta maydon: rekvizit, o'lchov, resurs yoki jadval bo'limi maydoni.

    ⚠️ `value_type` — hujjatdagi XOM tip matni (platformaning tip tavsifi, masalan uzunligi
    qavs ichida ko'rsatilgan satr tipi).
    Graf uni bo'laklarga ajratmaydi: ajratish platforma versiyasiga bog'liq TALQIN bo'lardi.
    Raqamli aniqlik va uzunlik alohida maydonlarda, MATN sifatida keladi."""

    name: str
    synonym: str | None
    kind: str
    value_type: str
    reference_targets: tuple[str, ...]
    numeric_digits: str | None
    numeric_scale: str | None
    string_length: str | None
    parent_object: str
    path: str

    @property
    def address(self) -> str:
        """Maydonning to'liq manzili: `<obyekt>.<path>`."""
        return f"{self.parent_object}{PATH_SEP}{self.path}"

    @property
    def tabular_section(self) -> str | None:
        """Maydon jadval bo'limida bo'lsa — bo'lim nomi, aks holda `None` (path'dan olinadi)."""
        if PATH_SEP in self.path:
            return self.path.split(PATH_SEP, 1)[0]
        return None


@dataclass(frozen=True)
class ObjectNode:
    """Bitta metadata obyekti va uning bolalari.

    ⚠️ `hierarchical` uchulik: `True`/`False`/`None`. `None` = «yig'uvchi qaramadi», `False` =
    «qaradi va yo'q». Ikkisini qo'shib yuborish — «qaralmadi» ni «yo'q» deb o'qish bo'lardi."""

    full_name: str
    object_kind: str
    name: str
    synonym: str | None
    comment: str | None
    hierarchical: bool | None
    row_count: str | None
    fields: tuple[FieldNode, ...]
    tabular_section_names: tuple[str, ...]
    enum_values: tuple[str, ...]
    predefined: tuple[str, ...]
    register_kind: str | None
    periodicity: str | None
    errors: tuple[str, ...]


@dataclass(frozen=True)
class Relationship:
    """Yo'naltirilgan qirra. Faqat hujjatda AYTILGAN bog'lanish — xulosa chiqarilmaydi."""

    source: str
    source_field: str | None
    target: str
    relationship_type: str

    @property
    def sort_key(self) -> tuple[str, str, str, str]:
        return (self.source, self.relationship_type, self.source_field or "", self.target)


@dataclass(frozen=True)
class DiscoveryGraph:
    """Normallashtirilgan graf + qulay qidiruv.

    ⚠️ `unresolved_references` — hujjatda YO'Q obyektga qilingan havolalar. Ular qirra
    sifatida HAM qoladi (bog'lanish rostdan bor), lekin `by_full_name` ularni topmaydi:
    konfiguratsiya bo'lak-bo'lak olingan bo'lishi mumkin."""

    objects: tuple[ObjectNode, ...]
    relationships: tuple[Relationship, ...]
    unresolved_references: tuple[str, ...]

    @cached_property
    def _by_name(self) -> dict[str, ObjectNode]:
        return {o.full_name: o for o in self.objects}

    def by_full_name(self, full_name: str) -> ObjectNode | None:
        """Obyektni to'liq nomi bo'yicha. `None` = hujjatda yo'q (tashqi/aniqlanmagan)."""
        return self._by_name.get(full_name)

    def objects_of_kind(self, kind: str) -> tuple[ObjectNode, ...]:
        """Berilgan turdagi obyektlar. Noma'lum tur — XATO (imlo xatosi jimgina bo'sh
        ro'yxat bermasin: bo'sh javob «bu turda hech narsa yo'q» degan ma'no beradi)."""
        if kind not in SOURCE_KINDS:
            raise MetadataError(f"noma'lum obyekt turi: {kind!r} — ruxsat etilgani {list(SOURCE_KINDS)}")
        return tuple(o for o in self.objects if o.object_kind == kind)

    def referencing(self, full_name: str) -> tuple[Relationship, ...]:
        """KIM shu obyektga havola qiladi (faqat `references` qirralari)."""
        return tuple(r for r in self.relationships
                     if r.relationship_type == "references" and r.target == full_name)

    def references_from(self, full_name: str) -> tuple[Relationship, ...]:
        """Shu obyekt KIMGA havola qiladi (faqat `references` qirralari)."""
        return tuple(r for r in self.relationships
                     if r.relationship_type == "references" and r.source == full_name)

    def fields_of(self, full_name: str) -> tuple[FieldNode, ...]:
        """Obyektning hamma maydoni (jadval bo'limi maydonlari ham, `path` bilan)."""
        o = self._by_name.get(full_name)
        return o.fields if o is not None else ()


def _field_node(f: dict, *, parent_object: str, path: str) -> FieldNode:
    return FieldNode(
        name=f["name"],
        synonym=f["synonym"],
        kind=f["kind"],
        value_type=f["type"],
        # ⚠️ Havolalar tartiblanadi va takrori olib tashlanadi: hujjatdagi tartib platforma
        #    tip tavsifining tartibi, ya'ni ma'no tashimaydi.
        reference_targets=tuple(sorted(set(f["reference_targets"]))),
        numeric_digits=f["numeric_digits"],
        numeric_scale=f["numeric_scale"],
        string_length=f["string_length"],
        parent_object=parent_object,
        path=path,
    )


def build_graph(doc) -> DiscoveryGraph:
    """Hujjatni grafga aylantiradi. AVVAL `validate_metadata` chaqiriladi — tekshirilmagan
    hujjatdan graf qurilmaydi, aks holda buzuq kirish «tayyor tuzilma» ko'rinishida tarqaydi."""
    unresolved = validate_metadata(doc)

    objects: list[ObjectNode] = []
    relationships: list[Relationship] = []

    for o in doc["objects"]:
        to_liq = o["full_name"]
        fields: list[FieldNode] = []

        # Obyekt darajasidagi maydonlar: rekvizit / o'lchov / resurs.
        for list_name in FIELD_LISTS:
            rel_type = _LIST_RELATIONSHIP[list_name]
            for f in o[list_name]:
                node = _field_node(f, parent_object=to_liq, path=f["name"])
                fields.append(node)
                relationships.append(Relationship(node.address, node.path, to_liq, rel_type))
                for target in node.reference_targets:
                    relationships.append(Relationship(to_liq, node.path, target, "references"))

        # Jadval bo'limlari va ularning maydonlari.
        for sec in o["tabular_sections"]:
            sec_address = f"{to_liq}{PATH_SEP}{sec['name']}"
            relationships.append(Relationship(sec_address, None, to_liq, "tabular_section_of"))
            for f in sec["attributes"]:
                path = f"{sec['name']}{PATH_SEP}{f['name']}"
                node = _field_node(f, parent_object=to_liq, path=path)
                fields.append(node)
                # Bo'lim maydonining egasi — BO'LIM, obyektning o'zi emas.
                relationships.append(
                    Relationship(node.address, node.path, sec_address, "attribute_of"))
                for target in node.reference_targets:
                    relationships.append(Relationship(to_liq, node.path, target, "references"))

        # Sanab o'tilgan qiymatlar: faqat NOMLAR.
        # ⚠️ TARTIB SAQLANMAYDI (tartiblanadi). Sabab: hujjatdagi o'rindan «indeks» yoki
        #    «tartib raqami» chiqarish TALQIN bo'lardi, graf esa talqin qilmaydi.
        for value_name in sorted(o["enum_values"]):
            relationships.append(
                Relationship(f"{to_liq}{PATH_SEP}{value_name}", None, to_liq, "enum_of"))

        objects.append(ObjectNode(
            full_name=to_liq,
            object_kind=o["kind"],
            name=o["name"],
            synonym=o["synonym"],
            comment=o["comment"],
            hierarchical=HIERARCHICAL[o["hierarchical"]],
            row_count=o["row_count"],
            fields=tuple(sorted(fields, key=lambda n: n.path)),
            tabular_section_names=tuple(sorted(s["name"] for s in o["tabular_sections"])),
            enum_values=tuple(sorted(o["enum_values"])),
            predefined=tuple(sorted(o["predefined"])),
            register_kind=o["register_kind"],
            periodicity=o["periodicity"],
            errors=tuple(o["errors"]),
        ))

    return DiscoveryGraph(
        objects=tuple(sorted(objects, key=lambda n: n.full_name)),
        relationships=tuple(sorted(set(relationships), key=lambda r: r.sort_key)),
        unresolved_references=tuple(unresolved),
    )


def graph_stats(graph: DiscoveryGraph) -> dict:
    """Grafning sanoqlari — hamma qiymat MATN, hamma lug'at tartiblangan.

    ⚠️ Sanoqlar MATN, chunki ular hujjatga tushadi va JSON soni bo'lib qolsa boshidagi
    nollar bilan birga ma'no yo'qoladi (`binos-1c-metadata-v1` 1-invarianti)."""
    tur_bo_yicha: dict[str, int] = {}
    for o in graph.objects:
        tur_bo_yicha[o.object_kind] = tur_bo_yicha.get(o.object_kind, 0) + 1

    qirra_bo_yicha: dict[str, int] = {}
    for r in graph.relationships:
        qirra_bo_yicha[r.relationship_type] = qirra_bo_yicha.get(r.relationship_type, 0) + 1

    return {
        "objects": str(len(graph.objects)),
        "objects_by_kind": {k: str(tur_bo_yicha[k]) for k in sorted(tur_bo_yicha)},
        "fields": str(sum(len(o.fields) for o in graph.objects)),
        "relationships": str(len(graph.relationships)),
        "relationships_by_type": {k: str(qirra_bo_yicha[k]) for k in sorted(qirra_bo_yicha)},
        "unresolved_references": str(len(graph.unresolved_references)),
    }
