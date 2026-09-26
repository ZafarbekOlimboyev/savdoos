# -*- coding: utf-8 -*-
"""Do'konning operatsion holati (Phase 6A) — obuna holatidan ALOHIDA."""
from __future__ import annotations

from app.models.enums import CompanyStatus


def company_status(company) -> str:
    """`companies.status` qiymati; NULL -> ACTIVE.

    ⚠️  Ustun mavjud jadvalga DEFAULT'siz qo'shiladi (`initdb._ADDED_COLUMNS`), shu bois
        eski qatorlarda NULL. NULL «holat noma'lum» EMAS — u «hech kim o'zgartirmagan»,
        ya'ni ACTIVE degani.
    ⚠️  PHASE 6A/1 DA MAJBURLANMAYDI: to'xtatish hamon `Setting(key='suspended')` orqali
        (`core/deps.py:40-44`) va U yagona haqiqat manbai. Bu yordamchi hozir faqat
        KO'RSATISH uchun; birlashtirish aniq migratsiya bilan keyingi bosqichda.
    """
    return getattr(company, "status", None) or CompanyStatus.ACTIVE.value
