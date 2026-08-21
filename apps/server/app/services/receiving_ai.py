"""Nakladnoy/hujjat rasmini o'qish (Gemini yoki Claude vision) + mahsulotni SavdoOS bazasi bilan moslash.

Kalit bo'lmasa — DEMO rejim: bazadagi bir nechta mahsulotdan namunaviy qatorlar qaytaradi
(oqim to'liq test qilinsin). GEMINI_API_KEY yoki ANTHROPIC_API_KEY qo'yilsa — real AI.
Ikkisi ham bo'lsa Gemini ustun (bepul tier, kartasiz).
"""
import json
import re
from difflib import SequenceMatcher

from app.core.config import settings

_PROMPT = (
    "Sen — do'kon ombori uchun yordamchisan. Rasmda yetkazib beruvchi/kuryer olib kelgan "
    "mahsulotlar ro'yxati (nakladnoy/накладная) bor. Undagi HAR bir mahsulot qatorini ajrat.\n"
    "Faqat JSON massiv qaytar, boshqa hech narsa yozma. Har element:\n"
    '{"name": "mahsulot nomi", "qty": son, "unit": "dona|kg|litr", "price": son_yoki_null}\n'
    "Qoidalar: qty — butun yoki kasr son; nomni rasmda yozilganidek qoldir; "
    "narx ko'rinmasa null; sarlavha/jami/izoh qatorlarini QO'SHMA."
)


def read_invoice(image_b64: str, media_type: str, product_names: list[str]) -> tuple[list[dict], str]:
    """(qatorlar, manba) qaytaradi. Manba: 'ai' yoki 'demo' yoki 'error:...'."""
    if not settings.ai_any:
        return _demo_rows(product_names), "demo"
    hint = ""
    if product_names:
        hint = "\nDo'kondagi mavjud mahsulotlar (moslashtirish uchun): " + ", ".join(product_names[:200])
    prompt = _PROMPT + hint
    try:
        if settings.gemini_enabled:
            return _read_gemini(image_b64, media_type, prompt), "ai"
        return _read_claude(image_b64, media_type, prompt), "ai"
    except Exception as e:  # noqa: BLE001 — AI xato bo'lsa oqim buzilmasin
        return [], "error:" + str(e)[:120]


def _read_gemini(image_b64: str, media_type: str, prompt: str) -> list[dict]:
    """Google Gemini vision (REST) orqali nakladnoyni o'qiydi."""
    import httpx
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{settings.gemini_model}:generateContent"
    body = {
        "contents": [{"parts": [
            {"inline_data": {"mime_type": media_type, "data": image_b64}},
            {"text": prompt},
        ]}],
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 2048},
    }
    with httpx.Client(timeout=60) as client:
        r = client.post(url, params={"key": settings.gemini_api_key}, json=body)
        if r.status_code != 200:
            raise RuntimeError(f"Gemini {r.status_code}: {r.text[:120]}")
        data = r.json()
    text = ""
    for cand in data.get("candidates", []):
        for part in cand.get("content", {}).get("parts", []):
            if isinstance(part, dict) and "text" in part:
                text += part["text"]
    return _parse_json_rows(text)


def _read_claude(image_b64: str, media_type: str, prompt: str) -> list[dict]:
    """Anthropic Claude vision orqali nakladnoyni o'qiydi."""
    import anthropic  # lazy — demo rejimda paket shart emas
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    resp = client.messages.create(
        model=settings.ai_model,
        max_tokens=2000,
        output_config={"effort": "low"},   # oddiy OCR — chuqur o'ylash shart emas
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": image_b64}},
                {"type": "text", "text": prompt},
            ],
        }],
    )
    if resp.stop_reason == "refusal":
        raise RuntimeError("AI so'rovni rad etdi")
    text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
    return _parse_json_rows(text)


def _parse_json_rows(text: str) -> list[dict]:
    text = text.strip()
    # JSON massivni ajratib olamiz (model atrofga matn qo'shsa ham)
    m = re.search(r"\[.*\]", text, re.DOTALL)
    if m:
        text = m.group(0)
    try:
        data = json.loads(text)
    except Exception:  # noqa: BLE001
        return []
    out = []
    for r in data if isinstance(data, list) else []:
        if not isinstance(r, dict):
            continue
        name = str(r.get("name") or "").strip()
        if not name:
            continue
        try:
            qty = float(r.get("qty") or 0)
        except (TypeError, ValueError):
            qty = 0.0
        if qty <= 0:
            qty = 1.0
        price = r.get("price")
        try:
            price = float(price) if price is not None else None
        except (TypeError, ValueError):
            price = None
        out.append({"name": name, "qty": qty, "unit": str(r.get("unit") or "dona"), "price": price})
    return out


def _demo_rows(product_names: list[str]) -> list[dict]:
    qtys = [24, 12, 18, 10, 6, 30]
    rows = []
    for i, nm in enumerate(product_names[:4]):
        rows.append({"name": nm, "qty": float(qtys[i % len(qtys)]), "unit": "dona", "price": None})
    return rows


# ─────────────────────────────  Mahsulot moslash  ─────────────────────────────

def _norm(s: str) -> str:
    s = (s or "").lower()
    s = re.sub(r"[^0-9a-zа-яё\s]", " ", s)   # harf/raqamdan boshqasini olib tashlaymiz
    return re.sub(r"\s+", " ", s).strip()


def _score(a: str, b: str) -> float:
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return 0.0
    ratio = SequenceMatcher(None, na, nb).ratio()
    ta, tb = set(na.split()), set(nb.split())
    overlap = len(ta & tb) / len(ta | tb) if (ta | tb) else 0.0
    return round(max(ratio, 0.5 * ratio + 0.5 * overlap), 3)


def match_products(ai_rows: list[dict], products: list[dict]) -> list[dict]:
    """Har AI qatoriga eng mos mahsulotni topadi. products: [{id, name, unit_code, base_buy_price}]."""
    out = []
    for row in ai_rows:
        best, best_score = None, 0.0
        for p in products:
            sc = _score(row["name"], p["name"])
            if sc > best_score:
                best, best_score = p, sc
        matched = best is not None and best_score >= 0.6
        out.append({
            "ai_name": row["name"],
            "qty": row["qty"],
            "unit": row.get("unit") or "dona",
            "price": row.get("price"),
            "product_id": (best["id"] if matched else None),
            "matched_name": (best["name"] if matched else None),
            "confidence": best_score,
            "unit_cost": (row.get("price") if row.get("price") else (best.get("base_buy_price") if matched else 0)),
        })
    return out
