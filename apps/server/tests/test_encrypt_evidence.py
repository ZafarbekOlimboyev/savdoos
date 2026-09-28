# -*- coding: utf-8 -*-
"""`scripts/encrypt_evidence.sh` — XULQ testlari (skript HAQIQATAN bajariladi).

Talab: "Encryption must be verified before upload", "Fail closed when encryption is
unavailable", "No silent upload of unencrypted fallback files".

Bu uchtasini matn bilan isbotlab bo'lmaydi — shuning uchun skript haqiqiy fayllar
ustida yurgiziladi va HAR BIR yiqilish yo'lida ochiq nusxa SAQLANGANI tekshiriladi.
Ochiq nusxa o'chib, shifrlangani yaroqsiz bo'lib qolishi — falokat kunidagi eng yomon
holat: nusxa BOR ko'rinadi, lekin OCHILMAYDI.
"""
from __future__ import annotations

import os
import pathlib
import shutil
import subprocess

import pytest

SERVER = pathlib.Path(__file__).resolve().parents[1]
ROOT = SERVER.parent.parent
SCRIPT = ROOT / "scripts" / "encrypt_evidence.sh"

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None or shutil.which("gpg") is None,
    reason="bash va gpg kerak")

PW = "sinov-paroli-shu-testda-yaratilgan"


def _run(files, tmp_path, passphrase=PW, path_env=None):
    env = dict(os.environ)
    env["BACKUP_PASSPHRASE"] = passphrase
    if path_env is not None:
        env["PATH"] = path_env
    return subprocess.run(["bash", str(SCRIPT), *[str(f) for f in files]],
                          cwd=str(ROOT), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env=env)


def _mk(tmp_path, name, body):
    p = tmp_path / name
    p.write_text(body, encoding="utf-8")
    return p


def test_shifrlaydi_tekshiradi_va_ochiq_nusxani_ochiradi(tmp_path):
    f = _mk(tmp_path, "after.json", '{"counts":{"sales":41},"ledger_sums":{"in":123456}}')
    r = _run([f], tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert not f.exists(), "ochiq nusxa O'CHIRILMADI"
    assert (tmp_path / "after.json.gpg").exists(), "shifrlangan fayl yaratilmadi"
    assert "tekshirildi" in r.stdout


def test_shifrlangan_fayl_ASL_tarkibga_qaytadi(tmp_path):
    body = '{"ledger_sums":{"in":987654321,"out":123}}'
    f = _mk(tmp_path, "before.json", body)
    assert _run([f], tmp_path).returncode == 0
    out = tmp_path / "back.json"
    r = subprocess.run(["bash", "-c",
                        'printf "%s" "$1" | gpg --batch --quiet --passphrase-fd 0 -o "$2" -d "$3"',
                        "_", PW, str(out), str(tmp_path / "before.json.gpg")],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert r.returncode == 0, r.stderr
    assert out.read_text(encoding="utf-8") == body, "aylanish tarkibni buzdi"


def test_parol_BOSH_bolsa_FAIL_CLOSED_va_ochiq_nusxa_SAQLANADI(tmp_path):
    f = _mk(tmp_path, "after.json", "maxfiy")
    r = _run([f], tmp_path, passphrase="")
    assert r.returncode != 0, "bo'sh parol bilan o'tib ketdi"
    assert f.exists(), "yiqilganda ochiq nusxa O'CHIRILDI — ma'lumot yo'qoldi"
    assert not (tmp_path / "after.json.gpg").exists()


def test_gpg_YOQ_bolsa_FAIL_CLOSED_va_ochiq_nusxa_SAQLANADI(tmp_path):
    """gpg o'rnatilmagan runner — jimgina "shifrlanmadi, mayli" bo'lmasin."""
    f = _mk(tmp_path, "after.json", "maxfiy")
    empty = tmp_path / "bin_yoq"
    empty.mkdir()
    r = _run([f], tmp_path, path_env=str(empty))
    assert r.returncode != 0, "gpg'siz muhitda o'tib ketdi"
    assert "gpg TOPILMADI" in (r.stdout + r.stderr)
    assert f.exists(), "yiqilganda ochiq nusxa o'chirildi"


def test_yoq_fayl_XATO_EMAS_lekin_HAMMASI_yoq_bolsa_XATO(tmp_path):
    """Job'ga qarab ba'zi dalillar umuman yaratilmaydi — bu normal. Lekin BIRORTASI ham
    bo'lmasa, bu "dalil yo'q" degani va jimgina o'tmasligi kerak."""
    f = _mk(tmp_path, "bor.json", "x")
    r = _run([f, tmp_path / "yoq.json"], tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "1 ta fayl yo'q edi" in r.stdout

    r2 = _run([tmp_path / "yoq1.json", tmp_path / "yoq2.json"], tmp_path)
    assert r2.returncode != 0, "birorta fayl shifrlanmagan holda muvaffaqiyat qaytardi"


def test_parol_buyruq_satriga_QOYILMAYDI():
    """Runner jarayonlar ro'yxatida parol ko'rinmasin."""
    src = SCRIPT.read_text(encoding="utf-8")
    assert "--passphrase-fd 0" in src, "parol stdin orqali berilmayapti"
    assert '--passphrase "$BACKUP_PASSPHRASE"' not in src, "parol buyruq satrida"


def test_fayl_TARKIBI_hech_qachon_chop_etilmaydi(tmp_path):
    maxfiy = "SIR-QIYMAT-9F3A-TOPILMASIN"
    f = _mk(tmp_path, "after.json", '{"x":"%s"}' % maxfiy)
    r = _run([f], tmp_path)
    assert r.returncode == 0
    assert maxfiy not in (r.stdout + r.stderr), "fayl tarkibi jurnalga chiqdi"
