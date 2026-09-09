# -*- coding: utf-8 -*-
"""SAQLANGAN backup ARTEFAKTIDAN tiklash — regressiya.

NEGA ALOHIDA: `test_backup_restore_chain.py` production'dan YANGI dump olib tiklashni
sinaydi — bu tiklash MEXANIZMINI isbotlaydi. Falokat kunida esa boshqa narsa ishlatiladi:
GitHub'da SAQLANGAN artefakt. "Mexanizm ishlaydi" degani "o'sha artefakt ochiladi va
tiklanadi" degani EMAS.

Ikki qatlam sinaladi:
  A) XATTI-HARAKAT — `scripts/restore_from_artifact.sh` HAQIQATAN ishga tushiriladi
     (buzuq checksum, noto'g'ri parol, yetishmayotgan fayl, xavfli maqsad, to'liq oqim).
  B) TUZILISH     — workflow YAML'i tekshiriladi: artefakt rejimi yangi dump olishga
     JIMGINA qayta OLMAYDI, production satrini KO'RMAYDI, tozalash HAR DOIM ishlaydi.
"""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import yaml

SERVER = pathlib.Path(__file__).resolve().parents[2]
ROOT = SERVER.parent.parent
PASSPHRASE = "artifact-test-only-not-a-real-secret"

pgserver = pytest.importorskip("pgserver")

pytestmark = pytest.mark.skipif(
    not shutil.which("bash") or not shutil.which("gpg"),
    reason="artefakt testi uchun bash va gpg kerak",
)

LOCAL_OK = "postgresql://postgres:{pw}@127.0.0.1:{port}/postgres"


def _pgbin() -> pathlib.Path:
    base = pathlib.Path(pgserver.__file__).parent
    for name in ("pg_dump.exe", "pg_dump"):
        hits = list(base.rglob(name))
        if hits:
            return hits[0].parent
    pytest.skip("pg_dump topilmadi")


def _run(cmd, extra_env=None, cwd=None):
    env = dict(os.environ, **(extra_env or {}))
    env["PATH"] = str(_pgbin()) + os.pathsep + env.get("PATH", "")
    env.setdefault("PG_BIN", str(_pgbin()))
    env.setdefault("PYTHON", sys.executable)
    env["PYTHONIOENCODING"] = "utf-8"
    # Meros qolgan production o'zgaruvchilari gardlarni chalg'itmasin — LEKIN chaqiruvchi
    # ularni ATAYLAB bergan bo'lsa (backup olish yoki gardni sinash) saqlab qolamiz.
    for k in ("DATABASE_URL", "PROD_DATABASE_URL"):
        if k not in (extra_env or {}):
            env.pop(k, None)
    return subprocess.run(cmd, capture_output=True, text=True, env=env,
                          cwd=str(cwd or ROOT), timeout=900)


def _plain(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://")


def _norm(url: str) -> str:
    for pfx in ("postgres://", "postgresql://"):
        if url.startswith(pfx):
            return "postgresql+psycopg://" + url[len(pfx):]
    return url


def _seed(engine):
    from sqlalchemy import text
    from sqlalchemy.orm import Session

    import app.models  # noqa: F401
    from app.db.base import Base
    from app.db.cash.deploy import deploy_cash_schema
    from app.models.auth import Employee, Role
    from app.models.catalog import Product, Unit
    from app.models.org import Branch, Company
    from app.models.sales import Sale, SaleItem, SalePayment

    Base.metadata.create_all(engine)
    assert deploy_cash_schema(engine) == "deployed"
    now = datetime.now(timezone.utc)
    with Session(engine) as s:
        co = Company(name="Artifact Co", code="artf", currency="UZS"); s.add(co); s.flush()
        role = Role(code="cashier_artf", name="Cashier"); s.add(role); s.flush()
        emp = Employee(company_id=co.id, full_name="Kassir", role_id=role.id); s.add(emp); s.flush()
        br = Branch(company_id=co.id, code="F01", name="Asosiy"); s.add(br); s.flush()
        unit = Unit(code="dona", name="dona"); s.add(unit); s.flush()
        p = Product(company_id=co.id, article_code="A1", name="Mahsulot", unit_id=unit.id,
                    base_buy_price=500, base_sell_price=1000, tax_rate=0)
        s.add(p); s.flush()
        for i in range(12):
            sale = Sale(company_id=co.id, branch_id=br.id, cashier_id=emp.id,
                        receipt_no=f"R{i:05d}", total=2000, subtotal=2000,
                        sold_at=now - timedelta(hours=i))
            s.add(sale); s.flush()
            s.add(SaleItem(sale_id=sale.id, product_id=p.id, qty=2, unit_price=1000,
                           line_total=2000, name_snapshot="x", unit_cost=500))
            s.add(SalePayment(sale_id=sale.id, method_code="cash", amount=2000,
                              paid_at=now - timedelta(hours=i)))
        s.commit()
    with engine.begin() as con:
        cid = con.execute(text("SELECT id FROM companies LIMIT 1")).scalar()
        bid = con.execute(text("SELECT id FROM branches LIMIT 1")).scalar()
        acc = uuid.uuid4()
        con.execute(text(
            "INSERT INTO cash.cash_accounts (id, tenant_id, branch_id, type, currency, status,"
            " label, created_at) VALUES (:i,:t,:b,'TILL','UZS','ACTIVE','TILL-01', now())"),
            {"i": acc, "t": cid, "b": bid})
        for i in range(6):
            con.execute(text(
                "INSERT INTO cash.cash_ledger_entries (id, tenant_id, cash_account_id, branch_id,"
                " account_type, shift_id, posting_kind, source_type, source_id, leg_index,"
                " direction, category, amount, currency, device_occurred_at, server_received_at,"
                " recorded_at, idempotency_key, provenance, metadata)"
                " VALUES (:i,:t,:a,:b,'TILL',NULL,'OFF_SHIFT','SALE',:s,0,'IN','SALE',:amt,'UZS',"
                " now(), now(), now(), :k, 'NORMAL', '{}'::jsonb)"),
                {"i": uuid.uuid4(), "t": cid, "a": acc, "b": bid, "s": uuid.uuid4(),
                 "amt": 1000 + i, "k": f"artf-{i}"})


@pytest.fixture(scope="module")
def artifact(tmp_path_factory):
    """HAQIQIY artefakt yasaydi: backup skripti -> gpg -> capture-time barmoq izi.

    Ya'ni `db-backup.yml` chiqaradigan tuzilmaning AYNAN o'zi."""
    from sqlalchemy import create_engine

    tmp = tmp_path_factory.mktemp("artifact_src")
    src = pgserver.get_server(str(tmp / "src_pg"))
    src_url = _norm(src.get_uri())
    eng = create_engine(src_url, future=True)
    _seed(eng)
    eng.dispose()

    art = tmp / "artifact"
    art.mkdir()
    r = _run(["bash", "scripts/backup_postgres.sh", str(art)], {"DATABASE_URL": _plain(src_url)})
    assert r.returncode == 0, (r.stdout + r.stderr)[-800:]

    # capture-time barmoq izi (db-backup.yml ham shuni artefaktga qo'shadi)
    r = _run([sys.executable, "-m", "app.tools.db_fingerprint", "--json"],
             {"DATABASE_URL": _plain(src_url)}, cwd=SERVER)
    assert r.returncode == 0, r.stderr[-400:]
    (art / "fingerprint.json").write_text(r.stdout, encoding="utf-8")

    dump = next(art.glob("*.dump"))
    enc = dump.with_suffix(dump.suffix + ".gpg")
    r = _run(["gpg", "--batch", "--yes", "--symmetric", "--cipher-algo", "AES256",
              "--passphrase", PASSPHRASE, "-o", str(enc), str(dump)])
    assert r.returncode == 0, r.stderr[-400:]
    dump.unlink()                                   # ochiq dump artefaktda QOLMAYDI
    return art


@pytest.fixture
def art_copy(artifact, tmp_path):
    """Har test uchun toza nusxa (testlar bir-birini buzmasin)."""
    d = tmp_path / "artifact"
    shutil.copytree(artifact, d)
    return d


@pytest.fixture
def target(tmp_path_factory):
    """BIR MARTALIK maqsad baza (localhost)."""
    srv = pgserver.get_server(str(tmp_path_factory.mktemp("tgt_pg")))
    return _plain(_norm(srv.get_uri()))


def _restore(art_dir, target_url, passphrase=PASSPHRASE, extra=None):
    env = {"BACKUP_PASSPHRASE": passphrase, "REHEARSAL_DATABASE_URL": target_url}
    env.update(extra or {})
    return _run(["bash", "scripts/restore_from_artifact.sh", str(art_dir)], env)


def _table_count(url: str) -> int:
    from sqlalchemy import create_engine, text
    eng = create_engine(_norm(url), future=True)
    try:
        with eng.connect() as c:
            return c.execute(text(
                "SELECT count(*) FROM information_schema.tables "
                "WHERE table_schema IN ('public','cash')")).scalar()
    finally:
        eng.dispose()


# ═══ A) XATTI-HARAKAT ═══════════════════════════════════════════════════════

def test_A_full_artifact_restore_succeeds(art_copy, target):
    """To'liq oqim: artefakt -> checksum -> shifr -> rollar -> restore -> barmoq izi."""
    r = _restore(art_copy, target)
    out = r.stdout + r.stderr
    assert r.returncode == 0, out[-1500:]
    assert "ochiq dump checksum: MOS" in out, out[-600:]
    assert "RESTORE_REHEARSAL_OK" in out, out[-600:]     # capture-time barmoq izi MOS keldi
    assert "ARTIFACT_RESTORE_OK" in out, out[-600:]
    # Ochiq dump o'chirilgan bo'lishi SHART
    assert not list(art_copy.glob("*.dump")), "ochiq dump QOLDI"
    assert "tozalandi" in out


def test_B_wrong_checksum_fails_before_restore(art_copy, target):
    """Buzuq checksum -> TIKLASH BOSHLANMAYDI. Maqsad baza TEGILMAGAN qoladi."""
    sums = next(art_copy.glob("*.dump.sha256"))
    sums.write_text("0" * 64 + "  " + sums.name.replace(".sha256", "") + "\n", encoding="utf-8")

    before = _table_count(target)
    r = _restore(art_copy, target)
    out = r.stdout + r.stderr
    assert r.returncode != 0, out[-800:]
    assert "CHECKSUM MOS EMAS" in out, out[-800:]
    assert "TIKLASH BOSHLANMADI" in out
    assert "pg_restore" not in out.lower().split("checksum mos emas")[-1]
    assert _table_count(target) == before, "checksum xato bo'lsa ham baza O'ZGARDI"


def test_C_wrong_passphrase_fails_before_restore(art_copy, target):
    """Noto'g'ri parol -> shifr ochilmaydi -> tiklash boshlanmaydi."""
    before = _table_count(target)
    r = _restore(art_copy, target, passphrase="butunlay-boshqa-parol")
    out = r.stdout + r.stderr
    assert r.returncode != 0, out[-800:]
    assert "SHIFR OCHILMADI" in out, out[-800:]
    assert _table_count(target) == before, "parol xato bo'lsa ham baza O'ZGARDI"
    # Parol loglarga CHIQMASLIGI shart
    assert "butunlay-boshqa-parol" not in out


def test_D_missing_encrypted_backup_fails(art_copy, target):
    """Shifrlangan nusxa yo'q -> BALAND xato (yangi dump olishga QAYTMAYDI)."""
    next(art_copy.glob("*.dump.gpg")).unlink()
    r = _restore(art_copy, target)
    out = r.stdout + r.stderr
    assert r.returncode != 0
    assert "*.dump.gpg" in out and "YO'Q" in out, out[-600:]
    # Eng muhimi: yangi dump OLINMAGAN
    assert "backup_postgres" not in out and "pg_dump -Fc" not in out


def test_E_ambiguous_artifact_fails(art_copy, target):
    """Bitta artefaktda IKKI shifrlangan nusxa -> qaysi biri ekani NOANIQ -> to'xtaydi."""
    enc = next(art_copy.glob("*.dump.gpg"))
    shutil.copyfile(enc, art_copy / "boshqa-nusxa.dump.gpg")
    r = _restore(art_copy, target)
    out = r.stdout + r.stderr
    assert r.returncode != 0
    assert "NOANIQ" in out, out[-600:]


def test_F_plaintext_dump_in_artifact_is_rejected(art_copy, target):
    """Artefaktda OCHIQ dump bo'lsa — bu xavfsizlik nuqsoni, ishlatilmaydi."""
    (art_copy / "sizib-ketgan.dump").write_bytes(b"x" * 100)
    r = _restore(art_copy, target)
    out = r.stdout + r.stderr
    assert r.returncode != 0
    assert "XAVFSIZLIK" in out and "OCHIQ dump" in out, out[-600:]


def test_G_target_cannot_equal_production(art_copy):
    """Maqsad DATABASE_URL/PROD_DATABASE_URL bilan bir xil bo'lsa — RAD."""
    prod = "postgresql://u:p@sakura.proxy.rlwy.net:11729/railway"
    r = _run(["bash", "scripts/restore_from_artifact.sh", str(art_copy)],
             {"BACKUP_PASSPHRASE": PASSPHRASE, "REHEARSAL_DATABASE_URL": prod,
              "DATABASE_URL": prod})
    out = r.stdout + r.stderr
    assert r.returncode != 0
    assert "RAD ETILDI" in out, out[-600:]


@pytest.mark.parametrize("bad", [
    "postgresql://u:p@db.example.com:5432/savdoos",       # masofaviy
    "postgresql://u:p@sakura.proxy.rlwy.net:11729/railway",  # Railway
    "postgresql://u:p@10.0.0.5:5432/prod",                # 'prod'
])
def test_H_remote_targets_are_refused(art_copy, bad):
    """Maqsad localhost BO'LMASA — tiklash umuman boshlanmaydi."""
    r = _restore(art_copy, bad)
    out = r.stdout + r.stderr
    assert r.returncode != 0, out[-400:]
    assert "RAD ETILDI" in out, out[-600:]


@pytest.mark.parametrize("local_url", [
    # POSIX'dagi `pgserver` AYNAN shu shaklni beradi — unix domen soketi.
    "postgresql://postgres:@/postgres?host=/tmp/pgserver_abc",
    "postgresql://postgres:@/postgres?sslmode=disable&host=/var/run/pg",
    "postgresql://u:p@[::1]:5432/db",
])
def test_H2_unix_socket_and_ipv6_loopback_are_local(art_copy, local_url):
    """⚠️  Unix soket ham LOKAL — lokallik tekshiruvi undan o'tkazib yubormasligi kerak.

    Guard faqat `localhost`/`127.0.0.1` ni tan olardi, `pgserver` esa Linux/macOS'da
    `postgresql://postgres:@/postgres?host=/tmp/...` beradi. Natijada tiklash mashqi
    testlari CI (Linux) da "manzil masofaviy" deb RAD ETILARDI, mahalliy Windows'da
    esa o'tardi — ya'ni gate platformaga qarab boshqacha javob berardi.

    Unix soket tarmoqqa umuman chiqmaydi, ya'ni bu loopback'dan ham qattiqroq
    kafolat; uni rad etish xavfsizlikka hech narsa qo'shmaydi.

    Tiklashning O'ZI bu bazalarda ishlamaydi (ular mavjud emas) — muhimi shuki,
    LOKALLIK tekshiruvidan o'tadi va xato boshqa sababdan chiqadi."""
    r = _restore(art_copy, local_url)
    out = r.stdout + r.stderr
    assert "masofaviy ko'rinadi" not in out, out[-600:]


def test_H3_entrypoint_scripts_are_executable_in_git():
    """⚠️  Kirish skriptlari git'da `100755` bo'lishi SHART.

    `restore_from_artifact.sh` `restore_rehearsal.sh` ni chaqiradi. Fayl git'da
    `100644` edi, ya'ni Linux'da exec biti yo'q — chaqiruv `Permission denied`
    (126) bilan yiqilardi. Windows'da fayl rejimi saqlanmaydi, shuning uchun bu
    MAHALLIY ravishda umuman ko'rinmasdi va faqat CI (Linux) da chiqdi.

    `lib/pg_client.sh` bu ro'yxatda YO'Q — u `source` qilinadi, bajarilmaydi,
    shuning uchun `100644` unga TO'G'RI rejim."""
    import subprocess
    out = subprocess.run(["git", "ls-files", "-s", "scripts/"], cwd=ROOT,
                         capture_output=True, text=True, check=True).stdout
    modes = {}
    for line in out.splitlines():
        meta, path = line.split("	", 1)
        modes[path.strip()] = meta.split()[0]

    for f in ("scripts/backup_postgres.sh", "scripts/restore_from_artifact.sh",
              "scripts/restore_rehearsal.sh"):
        assert modes.get(f) == "100755", (
            f"{f}: git rejimi {modes.get(f)} — Linux'da bajarib bo'lmaydi. "
            f"Tuzatish: git update-index --chmod=+x {f}")


# ═══ B) TUZILISH — workflow kafolatlari ═════════════════════════════════════

@pytest.fixture(scope="module")
def wf():
    p = ROOT / ".github" / "workflows" / "restore-rehearsal.yml"
    return yaml.safe_load(p.read_text(encoding="utf-8")), p.read_text(encoding="utf-8")


def _job_text(raw: str, job: str) -> str:
    """Bitta job'ning xom YAML matni (keyingi job boshlanguncha)."""
    start = raw.index(f"\n  {job}:")
    rest = raw[start + 1:]
    nxt = [i for i in (rest.find("\n  artifact:"), rest.find("\n  fresh:")) if i > 0]
    return rest[:min(nxt)] if nxt else rest


def test_I_artifact_mode_never_takes_a_fresh_dump(wf):
    """ENG MUHIM KAFOLAT: artefakt rejimi yangi dump olishga JIMGINA qayta OLMAYDI.

    Aks holda artefakt yuklanmagan holatda mashq "yashil" bo'lardi, lekin artefakt
    haqida HECH NARSA isbotlamasdi — ya'ni o'zini o'zi aldardi."""
    _data, raw = wf
    art = _job_text(raw, "artifact")
    # IZOHLARNI tashlaymiz: izohda `PROD_DATABASE_URL` ni ESLATISH mumkin (aynan uni
    # ishlatmasligimizni tushuntirish uchun) — muhimi u BAJARILADIGAN YAML'da bo'lmasligi.
    code = chr(10).join(ln for ln in art.splitlines() if not ln.lstrip().startswith("#"))
    assert "backup_postgres.sh" not in code, "artefakt job'i YANGI DUMP olmoqda"
    assert "PROD_DATABASE_URL" not in code, "artefakt job'i production satrini ko'rmoqda"
    assert "restore_from_artifact.sh" in code


def test_J_artifact_job_uses_the_requested_run(wf):
    """Yuklab olish AYNAN so'ralgan run'dan bo'lishi shart."""
    _data, raw = wf
    art = _job_text(raw, "artifact")
    assert "actions/download-artifact" in art
    assert "run-id: ${{ inputs.backup_run_id }}" in art, "boshqa run'dan yuklanmoqda"


def test_K_modes_are_mutually_exclusive(wf):
    """Ikki rejim BIR VAQTDA ishlamaydi va fallback yo'q."""
    data, _raw = wf
    jobs = data["jobs"]
    assert set(jobs) == {"artifact", "fresh"}
    assert jobs["artifact"]["if"] == "github.event_name == 'workflow_dispatch' && inputs.backup_run_id != ''"
    assert "inputs.backup_run_id == ''" in jobs["fresh"]["if"]
    assert "schedule" in jobs["fresh"]["if"]


def test_L_target_is_hardcoded_localhost(wf):
    """Maqsad baza QATTIQ YOZILGAN localhost bo'lishi shart — kirishdan OLINMAYDI."""
    data, _raw = wf
    for job in ("artifact", "fresh"):
        urls = [v for k, v in (data["jobs"][job].get("env") or {}).items()
                if k == "REHEARSAL_DATABASE_URL"]
        urls += [s.get("env", {}).get("REHEARSAL_DATABASE_URL")
                 for s in data["jobs"][job]["steps"] if s.get("env")]
        urls = [u for u in urls if u]
        assert urls, f"{job}: REHEARSAL_DATABASE_URL topilmadi"
        for u in urls:
            assert "localhost" in u, f"{job}: maqsad localhost emas: {u}"
            assert "${{" not in u, f"{job}: maqsad kirishdan olinmoqda: {u}"


def test_M_cleanup_runs_even_on_failure(wf):
    """Ochiq dump xato bo'lganda ham tozalanishi shart."""
    data, _raw = wf
    for job in ("artifact", "fresh"):
        cleanup = [s for s in data["jobs"][job]["steps"]
                   if "Tozalash" in (s.get("name") or "")]
        assert cleanup, f"{job}: tozalash qadami YO'Q"
        assert cleanup[0].get("if") == "always()", f"{job}: tozalash always() emas"


def test_N_no_plaintext_dump_is_ever_uploaded(wf):
    """Natija artefaktida ochiq dump BO'LMASLIGI shart."""
    data, _raw = wf
    for job in ("artifact", "fresh"):
        for step in data["jobs"][job]["steps"]:
            if "upload-artifact" in str(step.get("uses", "")):
                paths = str(step["with"]["path"])
                assert ".dump" not in paths.replace(".dump.gpg", ""), \
                    f"{job}: yuklanadigan yo'llarda dump bor: {paths}"


def test_O_backup_workflow_records_capture_fingerprint():
    """`db-backup.yml` KELAJAKDAGI artefaktlarga capture-time barmoq izi qo'shishi shart —
    aks holda tiklangan bazani solishtiradigan ishonchli asos bo'lmaydi."""
    raw = (ROOT / ".github" / "workflows" / "db-backup.yml").read_text(encoding="utf-8")
    data = yaml.safe_load(raw)
    up = [s for s in data["jobs"]["dump"]["steps"] if "upload-artifact" in str(s.get("uses", ""))][0]
    paths = str(up["with"]["path"])
    assert "fingerprint.json" in paths
    assert "*.meta.json" in paths
    assert "*.dump.gpg" in paths
    # Ochiq dump YUKLANMAYDI
    assert "backups/*.dump\n" not in paths
    # Dump davomida baza tinch turdimi — bu BELGILANADI
    assert "capture_quiescent" in raw
    assert "fingerprint-before.json" in raw
    # Shifrlangan checksum ham yoziladi (parolsiz butunlik tekshiruvi uchun)
    assert "sha256_encrypted" in raw
