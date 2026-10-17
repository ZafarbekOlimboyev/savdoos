"""Invoice extraction using only a validated immutable canonical target.

Demo requires explicit canonical mode; missing credentials never select demo.
No runtime provider fallback. Caller retains policy/company locks through HTTP.
"""
import json
import re
from difflib import SequenceMatcher

from app.services.ai_requirement import DISPATCH_ID, PROTOCOL_VERSION, Requirement, reject

# The existing dispatch capability binds Anthropic to this exact API origin/path.
# A different recipient requires a reviewed capability/requirement change.
_ANTHROPIC_ORIGIN = "https://api.anthropic.com"
_ANTHROPIC_MESSAGES_URL = _ANTHROPIC_ORIGIN + "/v1/messages"


def _check_anthropic_request(request):
    # Also checks any SDK URL mutation or attempted redirect before sending.
    if (request.method != "POST" or str(request.url) != _ANTHROPIC_MESSAGES_URL
            or request.headers.get("host") != "api.anthropic.com"):
        raise _UpstreamError("anthropic", 503)

_PROMPT = (
    "Sen — do'kon ombori uchun yordamchisan. Rasmda yetkazib beruvchi/kuryer olib kelgan "
    "mahsulotlar ro'yxati (nakladnoy/накладная) bor. Undagi HAR bir mahsulot qatorini ajrat.\n"
    "Faqat JSON massiv qaytar, boshqa hech narsa yozma. Har element:\n"
    '{"name": "mahsulot nomi", "qty": son, "unit": "dona|kg|litr", "price": son_yoki_null}\n'
    "Qoidalar: qty — butun yoki kasr son; nomni rasmda yozilganidek qoldir; "
    "narx ko'rinmasa null; sarlavha/jami/izoh qatorlarini QO'SHMA."
)


def read_invoice(image_b64: str, media_type: str, product_names: list[str], requirement: Requirement) -> tuple[list[dict], str]:
    """(qatorlar, manba) qaytaradi. Manba: 'ai' yoki 'demo' yoki 'error:...'."""
    if requirement.mode == "demo":
        return _demo_rows(product_names), "demo"
    if requirement.mode != "active" or not requirement.credential:
        reject(503, "AI_WORKER_FENCED")
    hint = ""
    if product_names:
        hint = "\nDo'kondagi mavjud mahsulotlar (moslashtirish uchun): " + ", ".join(product_names[:200])
    prompt = _PROMPT + hint
    try:
        if requirement.provider == "gemini":
            return _read_gemini(image_b64, media_type, prompt, requirement), "ai"
        if requirement.provider == "anthropic":
            return _read_claude(image_b64, media_type, prompt, requirement), "ai"
        reject(503, "AI_WORKER_FENCED")
    except Exception as e:  # noqa: BLE001 — AI xato bo'lsa oqim buzilmasin
        #  ⚠️  ISTISNO MATNI EMAS, FAQAT TURI (CH-16). `source` qiymati
        #      `api/v1/receiving.py` da `log.warning` bilan jurnalga yoziladi.
        #      `str(e)` esa provayderning XOM javob tanasini (model chiqishi,
        #      ba'zan so'rov ta'rifi) va httpx holatida SO'ROV URL'ini olib
        #      kelardi — URL'da esa ilgari API kaliti turardi (pastga qara).
        #      Diagnostika uchun istisno SINFI va HTTP holati yetarli; ularni
        #      `_UpstreamError` o'zi tashiydi.
        if isinstance(e, _UpstreamError):
            return [], f"error:{e.provider} HTTP {e.status}"
        return [], "error:" + type(e).__name__


class _UpstreamError(RuntimeError):
    """Provayder xatosi — MAZMUNSIZ: faqat kim va qanday holat.

    Javob tanasi ATAYLAB saqlanmaydi: u model chiqishini yoki yuborilgan
    hujjat tafsilotini qaytarishi mumkin va bu jurnalda turmasligi kerak."""

    def __init__(self, provider: str, status: int):
        super().__init__(f"{provider} HTTP {status}")
        self.provider = provider
        self.status = status


def _read_gemini(image_b64: str, media_type: str, prompt: str, target: Requirement) -> list[dict]:
    """Google Gemini vision (REST) orqali nakladnoyni o'qiydi."""
    import httpx
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{target.model}:generateContent"
    body = {
        "contents": [{"parts": [
            {"inline_data": {"mime_type": media_type, "data": image_b64}},
            {"text": prompt},
        ]}],
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 2048},
    }
    #  ⚠️  API KALITI SARLAVHADA, URL QUERY'DA EMAS (CH-16). Ilgari u
    #      `params={"key": ...}` edi: so'rov URL'i httpx istisnosiga, proxy
    #      jurnaliga va xato kuzatuv tizimiga TO'LIQ kalit bilan tushardi.
    #      `x-goog-api-key` — Google'ning o'zi tavsiya qiladigan usul.
    with httpx.Client(timeout=60) as client:
        r = client.post(url, headers={"x-goog-api-key": target.credential}, json=body)
        if r.status_code != 200:
            raise _UpstreamError("gemini", r.status_code)
        data = r.json()
    text = ""
    for cand in data.get("candidates", []):
        for part in cand.get("content", {}).get("parts", []):
            if isinstance(part, dict) and "text" in part:
                text += part["text"]
    return _parse_json_rows(text)


def _read_claude(image_b64: str, media_type: str, prompt: str, target: Requirement) -> list[dict]:
    """Anthropic Claude vision orqali nakladnoyni o'qiydi."""
    import anthropic  # lazy — demo rejimda paket shart emas
    if (target.mode != "active" or target.provider != "anthropic"
            or target.protocol_version != PROTOCOL_VERSION or target.dispatch_id != DISPATCH_ID):
        raise _UpstreamError("anthropic", 503)
    # Use the SDK's native HTTPX client type, without its default wrapper's
    # environment proxy mounts (SDK 1.15 builds those even with trust_env=False).
    # Older SDKs use httpx, current SDKs httpx2; unknown backends fail closed.
    http_type = next((base for base in anthropic.DefaultHttpxClient.__mro__
                      if base.__name__ == "Client" and
                      base.__module__.split(".")[0] in ("httpx", "httpx2")), None)
    if http_type is None:
        raise _UpstreamError("anthropic", 503)
    # No caller-supplied transport, proxy, mounts or hooks are accepted.
    with http_type(timeout=60, follow_redirects=False, trust_env=False,
                   event_hooks={"request": [_check_anthropic_request]}) as http:
        with anthropic.Anthropic(api_key=target.credential, base_url=_ANTHROPIC_ORIGIN,
                                 http_client=http, timeout=60, max_retries=0) as client:
            if str(client.base_url).rstrip("/") != _ANTHROPIC_ORIGIN:
                raise _UpstreamError("anthropic", 503)
            resp = client.messages.create(
                model=target.model,
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
        raise _UpstreamError("anthropic", 0)     # mazmun tashilmaydi
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
