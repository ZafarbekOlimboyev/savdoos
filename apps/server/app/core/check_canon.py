# -*- coding: utf-8 -*-
"""CHECK ifodasini MATN emas, TUZILMA bo'yicha solishtirish (Phase 4A.1).

⚠️  NEGA NOM YETMAYDI. Tayyorlik ilgari CHECK'ni faqat (jadval, nom) bo'yicha
    topardi: `ck_lot_shortfall_resolved_le_qty` NOMLI, lekin `CHECK (true)` bo'lgan
    cheklov ham «joyida» hisoblanardi — himoya yo'q, tayyorlik esa YASHIL.

⚠️  NEGA MATNNI TO'G'RIDAN-TO'G'RI SOLISHTIRMAYMIZ. Postgres ifodani O'ZICHA qayta
    yozadi (PG 16.2 va staging PG 18.6 da o'lchangan — ikkalasi bir xil yozadi,
    lekin bu kafolat emas):

        manba:  kind IN ('real', 'netting')
        PG:     ((kind)::text = ANY ((ARRAY['real'::character varying,
                 'netting'::character varying])::text[]))

    Qavs va tip keltirishning HAMMASINI olib tashlash esa XAVFLI: `NOT (a OR b)` va
    `(NOT a) OR b` bir xil satrga aylanib, buzilgan cheklov YASHIL o'tardi.

    Shu bois ifoda KICHIK grammatika bo'yicha Postgres operator USTUVORLIGI bilan
    daraxtga tahlil qilinadi va faqat MA'NONI o'zgartira OLMAYDIGAN farqlar
    normallashtiriladi:
      · ortiqcha qavslar (daraxtda qavs yo'q);
      · QIYMATNI O'ZGARTIRMAYDIGAN literal keltirish: satr -> text/varchar (uzunliksiz),
        son -> numeric (uzunliksiz), butun son -> integer tiplari, NULL;
      · matn USTUNINI text'ga keltirish — FAQAT ustunning haqiqiy tipi text/varchar
        bo'lsa (`text_columns`, katalogdan). Raqamli ustunni `::text` qilish esa
        taqqoslashni SATR taqqoslashiga aylantiradi ('10.000' <= '9.000') — MA'NOLI;
      · `x = ANY (ARRAY[...])` == `x IN (...)`, `x <> ALL (ARRAY[...])` == `x NOT IN (...)`;
      · AND/OR, `=`/`<>`, `+`/`*` operandlari tartibi; `a > b` == `b < a`;
      · son yozuvi: `0` == `00` (matn bo'yicha, yaxlitlashsiz). ⚠️ `2` va `2.0` TENG EMAS
        (re-review): Postgres'da biri int, biri numeric — `x / 2` butun bo'linish,
        `(1.50)::text` esa '1.50' satri. Shu bois o'nlik qism uzunligi ham identifikatsiyada.
      · qo'shtirnoqli tip nomi (`"character varying"`) o'rnatilgan tip EMAS — u domen yoki
        foydalanuvchi tipi bo'lishi mumkin, keltirish saqlanadi.
    Qolgan HAR QANDAY farq — boshqa operator, boshqa son, uzunlikli yoki `"char"`
    keltirish (`'netting'::varchar(3)` aslida 'net'), NOT ning joyi — ta'rif NOTO'G'RI.

⚠️  TANILMAGAN SINTAKSIS (funksiya, CASE, BETWEEN, AT TIME ZONE, E'...' satr, juda chuqur
    yoki juda uzun ifoda) `CanonError` beradi. Chaqiruvchi buni «noto'g'ri» deb EMAS,
    «tekshirib bo'lmadi» deb ko'rsatadi: tayyorlik baribir QIZIL (fail-closed), lekin
    avtomatik qayta yaratish QILINMAYDI.

Postgres ustuvorligi (pastdan yuqoriga): OR < AND < NOT < IS < taqqoslash
(= <> < <= > >=, ANY/ALL) < IN < + - < * / < unar minus < `::`.

Faqat sof Python — bazaga ulanmaydi, SQLite to'plamida ham sinaladi.
"""
from __future__ import annotations

import re

__all__ = ["CanonError", "canonical", "same_check"]


class CanonError(ValueError):
    """Ifoda qo'llab-quvvatlanadigan kichik grammatikaga sig'madi."""


_TOKEN_RE = re.compile(
    r"\s+"
    r"|(?P<str>'(?:[^']|'')*')"
    r"|(?P<num>\d+(?:\.\d*)?|\.\d+)"
    r'|(?P<qid>"(?:[^"]|"")+")'
    r"|(?P<op><>|!=|<=|>=|::|[=<>+\-*/(),.\[\]])"
    r"|(?P<word>[A-Za-z_][A-Za-z0-9_$]*)"
)

_RESERVED = frozenset({"and", "or", "not", "in", "any", "all", "some", "is", "null", "true",
                       "false", "array", "case", "when", "then", "else", "end", "between",
                       "like", "ilike", "similar", "exists", "cast", "unknown", "distinct",
                       "from", "collate", "at", "isnull", "notnull", "overlaps", "operator",
                       "escape", "within"})
# Matn tiplari. `char(n)`/bpchar/"char" BU YERDA EMAS: ular bo'sh joy bilan to'ldiradi yoki
# qiymatni kesadi — taqqoslash boshqacha ishlaydi.
_TEXTY = frozenset({"text", "character varying", "varchar"})
_SAFE_STR_LITERAL_TYPES = _TEXTY | {"unknown"}
_INT_TYPES = frozenset({"integer", "int", "int4", "bigint", "int8", "smallint", "int2"})
# Ko'p so'zli tip nomlari — YOPIQ ro'yxat. Ixtiyoriy so'zlar ketma-ketligini tip deb
# yutib yuborish (`'x'::timestamp at time zone kind`) operatorni daraxtdan YO'Q qilardi.
_MULTIWORD_TYPES = frozenset({"character varying", "double precision", "bit varying",
                              "timestamp with time zone", "timestamp without time zone",
                              "time with time zone", "time without time zone"})
_CMP_OPS = frozenset({"=", "<>", "<", "<=", ">", ">="})
_FLIP = {">": "<", ">=": "<="}
_MAX_DEPTH = 40
# Katalogdagi haqiqiy CHECK'lar o'nlab token. Chegara sikl bilan quriladigan zanjirlarni
# (`::a::b...`, `a - b - c ...`, `+` ro'yxatini har qadamda saralash) cheklaydi (re-review).
_MAX_TOKENS = 1500


def _tokens(src: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    pos = 0
    while pos < len(src):
        m = _TOKEN_RE.match(src, pos)
        if m is None:
            raise CanonError(f"tanilmagan belgi {pos}-o'rinda")
        pos = m.end()
        if m.lastgroup is not None:          # bo'sh joy guruhsiz — tashlanadi
            out.append((m.lastgroup, m.group(m.lastgroup)))
    return out


def _num(text: str) -> str:
    """Son QIYMATINI matn bo'yicha normallashtiradi — hech qachon yaxlitlamaydi."""
    neg = text.startswith("-")
    t = text[1:] if neg else text
    ip, _, fp = t.partition(".")
    ip = ip.lstrip("0") or "0"
    fp = fp.rstrip("0")
    s = ip + ("." + fp if fp else "")
    return s if (s == "0" or not neg) else "-" + s


def _dec(text: str) -> int:
    """Literal TIPI: -1 = butun (int), aks holda o'nlik qism uzunligi (numeric, `2.0` -> 1)."""
    return len(text.partition(".")[2]) if "." in text else -1


def _unquote_ident(v: str) -> str:
    return v[1:-1].replace('""', '"')


def _assoc(op: str, xs: list[tuple]) -> tuple:
    if len(xs) == 1:
        return xs[0]
    flat: list[tuple] = []
    for x in xs:
        flat.extend(x[1] if x[0] == op else [x])
    return (op, tuple(sorted(flat, key=repr)))


def _cmp(op: str, left: tuple, right: tuple) -> tuple:
    if op in _FLIP:                          # a > b  ==  b < a
        op, left, right = _FLIP[op], right, left
    if op in ("=", "<>"):
        left, right = sorted((left, right), key=repr)
    return ("cmp", op, left, right)


def _arith(op: str, left: tuple, right: tuple) -> tuple:
    if op in ("+", "*"):
        flat: list[tuple] = []
        for x in (left, right):
            flat.extend(x[2] if (x[0] == "arith" and x[1] == op) else [x])
        return ("arith", op, tuple(sorted(flat, key=repr)))
    return ("arith", op, (left, right))      # `-` va `/` tartibga bog'liq


def _items(items: list[tuple] | tuple) -> tuple:
    return tuple(sorted(set(items), key=repr))


class _Parser:
    def __init__(self, toks: list[tuple[str, str]], text_columns: frozenset[str]):
        self.t = toks
        self.i = 0
        self.text_columns = text_columns
        self.depth = 0

    # ── yordamchilar ────────────────────────────────────────────────────────
    def _peek(self, k: int = 0) -> tuple[str | None, str | None]:
        j = self.i + k
        return self.t[j] if j < len(self.t) else (None, None)

    def _word(self, k: int = 0) -> str | None:
        kind, v = self._peek(k)
        return v.lower() if kind == "word" else None

    def _take_op(self, op: str) -> bool:
        kind, v = self._peek()
        if kind == "op" and v == op:
            self.i += 1
            return True
        return False

    def _take_word(self, w: str) -> bool:
        if self._word() == w:
            self.i += 1
            return True
        return False

    def _expect_op(self, op: str) -> None:
        if not self._take_op(op):
            raise CanonError(f"'{op}' kutilgan edi")

    def _enter(self) -> None:
        self.depth += 1
        if self.depth > _MAX_DEPTH:
            raise CanonError("ifoda juda chuqur")

    def _cast(self, node: tuple, typ: str) -> tuple:
        kind = node[0]
        if kind == "str" and typ in _SAFE_STR_LITERAL_TYPES:
            return node
        if kind == "num" and (typ == "numeric" or (typ in _INT_TYPES and node[2] == -1)):
            return node
        if kind == "null":
            return node
        if kind == "bool" and typ in ("boolean", "bool"):
            return node
        if kind == "col" and typ in _TEXTY and node[1] in self.text_columns:
            return node                      # varchar ustun -> text: taqqoslash o'zgarmaydi
        if (kind == "array" and typ.endswith("[]") and typ[:-2] in _TEXTY
                and all(x[0] == "str" or (x[0] == "col" and x[1] in self.text_columns)
                        for x in node[1])):
            return node
        return ("cast", typ, node)           # boshqa HAR QANDAY keltirish — ma'noli

    # ── grammatika: past ustuvorlikdan yuqoriga ─────────────────────────────
    def expr(self) -> tuple:
        xs = [self._and()]
        while self._take_word("or"):
            xs.append(self._and())
        return _assoc("or", xs)

    def _and(self) -> tuple:
        xs = [self._not()]
        while self._take_word("and"):
            xs.append(self._not())
        return _assoc("and", xs)

    def _not(self) -> tuple:
        if self._take_word("not"):
            self._enter()
            node = ("not", self._not())
            self.depth -= 1
            return node
        return self._is()

    def _is(self) -> tuple:
        node = self._cmp()
        while self._take_word("is"):
            neg = self._take_word("not")
            what = self._word()
            if what not in ("null", "true", "false"):
                raise CanonError("IS dan keyin faqat NULL/TRUE/FALSE qo'llab-quvvatlanadi")
            self.i += 1
            node = ("is", node, what, neg)
        return node

    def _cmp(self) -> tuple:
        left = self._in()
        kind, v = self._peek()
        if kind == "op" and (v in _CMP_OPS or v == "!="):
            self.i += 1
            op = "<>" if v == "!=" else v
            quant = self._word()
            if quant in ("any", "all"):
                self.i += 1
                self._expect_op("(")
                arr = self._add()
                self._expect_op(")")
                # Elementlardan biri ma'noli keltirishni saqlab qolsa (`'netting'::varchar(3)`),
                # massivning text[] keltirishi ham qoladi — uni ochib, element darajasidagi
                # farqni solishtirishga beramiz: natija «tahlil qilinmadi» emas, «noto'g'ri».
                if (arr[0] == "cast" and arr[1].endswith("[]") and arr[1][:-2] in _TEXTY
                        and arr[2][0] == "array"):
                    arr = arr[2]
                if arr[0] != "array":
                    raise CanonError("ANY/ALL faqat ARRAY[...] bilan qo'llab-quvvatlanadi")
                items = _items(arr[1])
                if op == "=" and quant == "any":
                    return ("in", left, items, False)
                if op == "<>" and quant == "all":
                    return ("in", left, items, True)
                return ("quant", op, quant, left, items)
            return _cmp(op, left, self._in())
        return left

    def _in(self) -> tuple:
        left = self._add()
        if self._word() == "not" and self._word(1) == "in":
            self.i += 2
            return ("in", left, self._in_list(), True)
        if self._take_word("in"):
            return ("in", left, self._in_list(), False)
        return left

    def _in_list(self) -> tuple:
        self._expect_op("(")
        items = [self._add()]
        while self._take_op(","):
            items.append(self._add())
        self._expect_op(")")
        return _items(items)

    def _add(self) -> tuple:
        node = self._mul()
        while True:
            kind, v = self._peek()
            if kind == "op" and v in ("+", "-"):
                self.i += 1
                node = _arith(v, node, self._mul())
            else:
                return node

    def _mul(self) -> tuple:
        node = self._unary()
        while True:
            kind, v = self._peek()
            if kind == "op" and v in ("*", "/"):
                self.i += 1
                node = _arith(v, node, self._unary())
            else:
                return node

    def _unary(self) -> tuple:
        if self._take_op("-"):
            self._enter()
            x = self._unary()
            self.depth -= 1
            if x[0] == "num":
                neg = x[1][1:] if x[1].startswith("-") else _num("-" + x[1])
                return ("num", neg, x[2])
            return ("neg", x)
        return self._postfix()

    def _postfix(self) -> tuple:
        node = self._primary()
        while self._take_op("::"):          # `::` unar minusdan KUCHLI (Postgres)
            node = self._cast(node, self._typename())
        return node

    def _type_word(self) -> str | None:
        kind, v = self._peek()
        if kind == "word" and v.lower() not in _RESERVED:
            part = v.lower()
        elif kind == "qid":
            # Qo'shtirnoq SAQLANADI (re-review): `"character varying"` o'rnatilgan tip emas,
            # balki shu nomli domen/foydalanuvchi tipi — xavfsiz tiplar ro'yxatiga mos kelmasin.
            part = '"' + _unquote_ident(v) + '"'
        else:
            return None
        self.i += 1
        while self._take_op("."):           # sxema bilan: cash.cash_category
            kind2, v2 = self._peek()
            if kind2 == "word":
                part += "." + v2.lower()
            elif kind2 == "qid":
                part += '."' + _unquote_ident(v2) + '"'
            else:
                raise CanonError("tip nomi noto'g'ri")
            self.i += 1
        return part

    def _typename(self) -> str:
        name = self._type_word()
        if name is None:
            raise CanonError("tip nomi kutilgan edi")
        multi = False                       # qo'shtirnoqli nom ichidagi bo'sh joy — ko'p so'z EMAS
        while True:                         # ko'p so'zli tip — faqat YOPIQ ro'yxatdan
            w = self._word()
            if w is None:
                break
            cand = f"{name} {w}"
            if any(t == cand or t.startswith(cand + " ") for t in _MULTIWORD_TYPES):
                name = cand
                multi = True
                self.i += 1
            else:
                break
        if multi and name not in _MULTIWORD_TYPES:
            raise CanonError(f"tip nomi to'liq emas: {name}")
        if self._take_op("("):
            mods: list[str] = []
            while not self._take_op(")"):
                kind, v = self._peek()
                if kind == "num":
                    mods.append(v)
                    self.i += 1
                elif kind == "op" and v == ",":
                    self.i += 1
                else:
                    raise CanonError("tip modifikatori noto'g'ri")
            name += "(" + ",".join(mods) + ")"
        while self._take_op("["):
            self._expect_op("]")
            name += "[]"
        return name

    def _primary(self) -> tuple:
        kind, v = self._peek()
        if kind is None:
            raise CanonError("ifoda kutilmaganda tugadi")
        if kind == "num":
            self.i += 1
            return ("num", _num(v), _dec(v))
        if kind == "str":
            self.i += 1
            return ("str", v[1:-1].replace("''", "'"))
        if kind == "qid":
            self.i += 1
            return ("col", _unquote_ident(v))
        if kind == "op" and v == "(":
            self.i += 1
            self._enter()
            node = self.expr()
            self.depth -= 1
            self._expect_op(")")
            return node
        if kind == "word":
            w = v.lower()
            if w in ("true", "false"):
                self.i += 1
                return ("bool", w == "true")
            if w == "null":
                self.i += 1
                return ("null",)
            if w == "array":
                self.i += 1
                self._expect_op("[")
                items: list[tuple] = []
                if not self._take_op("]"):
                    while True:
                        items.append(self._add())
                        if self._take_op("]"):
                            break
                        self._expect_op(",")
                return ("array", tuple(items))
            if w in _RESERVED:
                raise CanonError(f"qo'llab-quvvatlanmaydigan kalit so'z: {w}")
            nkind, nv = self._peek(1)
            if nkind == "op" and nv in ("(", "."):
                raise CanonError(f"funksiya yoki malakali nom qo'llab-quvvatlanmaydi: {w}")
            self.i += 1
            return ("col", w)
        raise CanonError(f"kutilmagan belgi: {v}")


def canonical(src: str, *, text_columns=()) -> str:
    """Ifodaning kanonik ko'rinishi. Tanilmagan sintaksisda `CanonError`.

    `text_columns` — jadvaldagi haqiqiy tipi text/varchar bo'lgan ustunlar (katalogdan).
    """
    if not isinstance(src, str) or not src.strip():
        raise CanonError("bo'sh ifoda")
    toks = _tokens(src)
    if len(toks) > _MAX_TOKENS:
        raise CanonError("ifoda juda uzun")
    p = _Parser(toks, frozenset(text_columns))
    try:
        node = p.expr()
        if p.i != len(p.t):
            raise CanonError("ifodadan keyin ortiqcha belgilar qoldi")
        return repr(node)
    except RecursionError as e:              # sikl bilan qurilgan chuqur daraxt (repr ham)
        raise CanonError("ifoda juda chuqur") from e


def same_check(expected_src: str, catalog_expr: str, *, text_columns=()) -> bool:
    """Katalogdagi ifoda kutilgan ta'rif bilan TUZILMA bo'yicha tengmi.

    `CanonError` chaqiruvchiga O'TKAZILADI: «tekshirib bo'lmadi» ≠ «noto'g'ri».
    """
    return (canonical(expected_src, text_columns=text_columns)
            == canonical(catalog_expr, text_columns=text_columns))
