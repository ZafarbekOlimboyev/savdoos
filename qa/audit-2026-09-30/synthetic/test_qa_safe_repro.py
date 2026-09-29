# -*- coding: utf-8 -*-
"""MUSTAQIL QA REPRODUKSIYA — SAFE snapshot 85be3991 (qa/binos-independent-security).

Sinovlar INVARIANTNI tasdiqlaydi: nuqsonli kodda QIZIL = nuqson isboti.
"""
import os
import subprocess
import sys
import uuid
from datetime import timedelta
from decimal import Decimal

from tests.test_subscription_lifecycle import (ACTOR, T0, _actor_row,  # noqa: F401 — autouse
                                               _db, _enrolled)

from app.models.subscription import Subscription, SubscriptionPayment
from app.services.subscription import payments as pay


# ══ BINOS-QA-SAFE-01 · record_payment client_uuid=None — idempotentlik YO'Q ═══════════
# Invariant: ayni to'lovning takror chaqiruvi (retry/ikki bosish) ikkinchi to'lov ham,
# ikkinchi davr uzaytirish ham yozmasligi SHART — jadval append-only, keyin tuzatib
# bo'lmaydi. Nuqson: client_uuid=None da find_by_client_uuid None qaytaradi,
# ux_subpay_client_uuid qisman indeksi NULL'ni qoplamaydi -> ikki to'lov, ikki oy.

def test_qaS1_record_payment_none_uuid_double_extends(client):
    with _db() as db:
        cid, _pid = _enrolled(db)
        sub0 = db.query(Subscription).filter(Subscription.company_id == cid).one()
        end0 = sub0.current_period_end

        p1, new1 = pay.record_payment(
            db, company_id=cid, client_uuid=None, amount=Decimal("100000"),
            method="cash", actor=ACTOR, reason="oylik to'lov", now=T0 + timedelta(days=1))
        assert new1 is True

        # AYNI to'lovning retry'si (javob yo'qolgan / ikki marta bosilgan).
        p2, new2 = pay.record_payment(
            db, company_id=cid, client_uuid=None, amount=Decimal("100000"),
            method="cash", actor=ACTOR, reason="oylik to'lov", now=T0 + timedelta(days=1))

        n_pay = (db.query(SubscriptionPayment)
                 .filter(SubscriptionPayment.company_id == cid).count())
        sub1 = db.query(Subscription).filter(Subscription.company_id == cid).one()
        # INVARIANT: takror yozuv YO'Q (new2=False) va davr BIR marta uzaygan.
        assert new2 is False and n_pay == 1, (
            f"DUBL TO'LOV: new2={new2}, to'lovlar={n_pay}, davr {end0} -> "
            f"{sub1.current_period_end} (IKKI oy uzaygan — bitta pul, append-only reyestrda "
            "ikkita qator, storno yozuvchisi yo'q)")


# ══ BINOS-QA-SAFE-02 · index_state: ta'rif qatori YO'Q -> jimgina OK (fail-open) ══════
# Invariant: REQUIRED_INDEX_DEFINITIONS'ga kirgan indeks uchun ta'rif zondida qator
# topilmasa, bu «tekshirildi, shakli TO'G'RI» degani EMAS — OK berilmasligi shart
# (fail-closed modulning o'z shartnomasi). Nuqson: `d = defs.get(index)` None bo'lsa
# shox tushib ketadi va holat OK deb KESHLANADI.

def test_qaS2_missing_definition_row_is_treated_as_ok(monkeypatch):
    from app.core import index_guard as ig
    from app.core import required_schema as rs

    ig.reset_cache()
    idx = next(iter(rs.REQUIRED_INDEX_DEFINITIONS))
    table = rs.REQUIRED_INDEX_DEFINITIONS[idx].get("table", "t") if isinstance(
        rs.REQUIRED_INDEX_DEFINITIONS[idx], dict) else "t"
    monkeypatch.setattr(rs, "_unique_index_states",
                        lambda bind, pairs: {p: rs.IX_OK for p in pairs})
    monkeypatch.setattr(rs, "index_definition_states", lambda bind: {})  # qator YO'Q

    state = ig.index_state(object(), idx, table if isinstance(table, str) else "t")
    ig.reset_cache()
    # INVARIANT: ta'rifi o'qilmagan ro'yxatdagi indeks OK bo'la olmaydi.
    assert state != ig.OK, (
        f"FAIL-OPEN: {idx} ta'rif zondida YO'Q, lekin index_state={state!r} — shakl "
        "tekshirilmagan indeks OK deb keshlandi (TTL davomida yozuvlar qo'riqsiz)")


# ══ BINOS-QA-SAFE-03 · SAVDOOS_INDEX_GUARD_TTL yaroqsiz qiymatda import YIQILADI ══════
# Invariant: bitta yaroqsiz env qiymati (masalan xato yozilgan '10s') modul importini —
# ya'ni butun app boot'ini — yiqitmasligi kerak; xavfsiz default'ga tushish shart.
# Nuqson: import vaqtidagi float(...) ValueError beradi.

def test_qaS3_invalid_ttl_env_must_not_crash_import(tmp_path):
    env = {**os.environ, "SAVDOOS_INDEX_GUARD_TTL": "10s",
           "PYTHONIOENCODING": "utf-8"}
    r = subprocess.run(
        [sys.executable, "-c", "import app.core.index_guard as g; print(g._TTL_SECONDS)"],
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        env=env, capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, (
        f"IMPORT YIQILDI: SAVDOOS_INDEX_GUARD_TTL='10s' bilan app.core.index_guard "
        f"import bo'lmadi (butun server boot yiqiladi):\n{r.stderr[-400:]}")
