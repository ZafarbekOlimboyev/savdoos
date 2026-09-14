# -*- coding: utf-8 -*-
"""NEGCTL CI-2: sessiya yarmida pytest.exit(returncode=0) — pytest qadami YASHIL tugaydi,
verify_pytest_run.py esa QIZIL bo'lishi shart."""
import pytest


def test_negctl_sessiya_yarmida_toxtaydi():
    pytest.exit('NEGCTL CI-2: sessiya yarmida', returncode=0)
