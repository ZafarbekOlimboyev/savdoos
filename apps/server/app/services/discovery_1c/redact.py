# -*- coding: utf-8 -*-
"""Sirlarni topish va olib tashlash — FAIL-CLOSED.

Discovery to'plami do'kon kompyuteridan chiqadi va qo'ldan-qo'lga o'tadi. Shu bois unda
ulanish satri, parol, token yoki masofaviy kirish identifikatori BO'LMASLIGI kerak.

Ikki rejim:
  · `scan()`  — topilganlarni ro'yxatlaydi. Validator shuni chaqiradi va topilsa RAD etadi.
  · `redact()`— topilgan joyni niqob bilan almashtiradi. Yig'uvchi to'plamni YOZISHDAN OLDIN
                shuni ishlatadi; validator esa ishonmaydi va qayta tekshiradi.

Ataylab EHTIYOTKOR: shubhali narsa topilsa RAD etiladi. Yolg'on ijobiy — bir marta qo'lda
tekshirish; yolg'on salbiy — mijozning paroli GitHub'ga ketishi.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

MASK = "[REDACTED]"

#: Kalit nomi shunga o'xshasa — qiymati HECH QACHON chiqmaydi (qiymatiga qaralmaydi).
SECRET_KEY_RE = re.compile(
    r"(?i)(password|passwd|pwd|parol|secret|token|api[_-]?key|apikey|credential|"
    r"private[_-]?key|connection[_-]?string|conn[_-]?str|anydesk|teamviewer|rdp)"
)

#: Qiymat naqshlari. Har biri: (nom, regex, izoh).
VALUE_PATTERNS: tuple[tuple[str, re.Pattern, str], ...] = (
    # 1C ulanish satri bo'laklari — `Usr=`/`Pwd=` eng xavflisi, lekin `File=`/`Srvr=` ham
    # do'kon mashinasining ichki tuzilmasini oshkor qiladi.
    ("1c_connection_string", re.compile(r"(?i)\b(File|Srvr|Ref|Usr|Pwd|DBUser|DBPwd)\s*="),
     "1C ulanish satri bo'lagi"),
    # `scheme://user:password@host`
    ("url_credentials", re.compile(r"(?i)\b[a-z][a-z0-9+.\-]*://[^\s/:@]+:[^\s/@]+@"),
     "URL ichidagi login:parol"),
    ("email", re.compile(r"(?i)\b[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}\b"),
     "e-mail manzili"),
    # Xalqaro telefon: `+` va 9–15 raqam (orasida probel/tire/qavs bo'lishi mumkin).
    # Tovar nomidagi oddiy raqam bunga tushmaydi — `+` va raqam soni SHART.
    ("phone", re.compile(r"\+\d(?:[\s\-()]*\d){8,14}"), "telefon raqami"),
    # PEM kalit bloklari.
    ("private_key_block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
     "shaxsiy kalit bloki"),
    # `password: ...` / `пароль — ...` / `parol: ...` ko'rinishidagi erkin matn.
    # ⚠️ LOTIN `parol` ATAYLAB bor: bu loyihada operator hujjatlari ham, yozishmalar ham lotin
    #    o'zbekchada. Ilgari faqat kirill `парол` va inglizcha shakl qamrab olingandi, ya'ni
    #    operator O'Z TILIDA yozgan parol redaksiyadan JIMGINA o'tib ketardi.
    ("inline_password",
     re.compile(r"(?i)\b(парол\w*|parol\w*|maxfiy\w*|password|passwd|pwd)\b\s*[:=—-]\s*\S+"),
     "matn ichidagi parol"),
)


@dataclass(frozen=True)
class Finding:
    path: str
    pattern: str
    detail: str

    def __str__(self) -> str:  # xato matnida qiymatning O'ZI ko'rsatilmaydi
        return f"{self.path}: {self.detail} ({self.pattern})"


def _walk(node, path: str):
    if isinstance(node, dict):
        for k, v in node.items():
            yield from _walk(v, f"{path}.{k}" if path else str(k))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _walk(v, f"{path}[{i}]")
    else:
        yield path, node


def scan(data) -> list[Finding]:
    """To'plamdagi (yoki uning bir qismidagi) barcha shubhali joylar."""
    out: list[Finding] = []
    for path, value in _walk(data, ""):
        leaf = path.rsplit(".", 1)[-1].split("[", 1)[0]
        if SECRET_KEY_RE.search(leaf) and value not in (None, "", MASK):
            out.append(Finding(path, "secret_key_name", f"kalit nomi sirga o'xshaydi ({leaf!r})"))
            continue
        if not isinstance(value, str) or value == MASK:
            continue
        for name, rx, detail in VALUE_PATTERNS:
            if rx.search(value):
                out.append(Finding(path, name, detail))
                break
    return out


def redact(data):
    """Nusxasini qaytaradi: shubhali qiymatlar niqoblangan. Asl obyekt o'zgarmaydi."""
    if isinstance(data, dict):
        out = {}
        for k, v in data.items():
            if SECRET_KEY_RE.search(k):
                out[k] = MASK if v not in (None, "") else v
            else:
                out[k] = redact(v)
        return out
    if isinstance(data, list):
        return [redact(v) for v in data]
    if isinstance(data, str) and data != MASK:
        for _name, rx, _detail in VALUE_PATTERNS:
            if rx.search(data):
                return rx.sub(MASK, data)
    return data
