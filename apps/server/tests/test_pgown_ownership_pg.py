# -*- coding: utf-8 -*-
"""EGALIK KAFOLATI — HAQIQIY postgres processlari bilan.

NEGA BU FAYL BOR
================
`tests/test_pg_temp_cleanup.py` MEXANIZMNI soxta server bilan sinaydi va o'z
izohida aytadi: «Bu yerda HAQIQIY PostgreSQL ko'tarilmaydi». Ya'ni u PAPKALAR
tozalanishini isbotlaydi, PROCESSLAR o'lishini esa YO'Q.

Bu fayl aynan shu bo'shliqni yopadi va eng xavfli savolga javob beradi:
tozalash FAQAT o'zi yaratgan klasterga tegadimi.

⚠️  BU MASHINADA BEGONA `postgres.exe` LAR BOR (boshqa ishlardan, yuzlab).
    Agar tozalash nom bo'yicha ishlaganda (`taskkill /IM postgres.exe` yoki
    «hamma postgres») u BEGONA ishni o'ldirardi. Shu bois quyidagi test
    «aloqasiz» klaster YONIDA tozalashni bajaradi va aloqasiz klaster
    TIRIK QOLISHINI talab qiladi.
⚠️  IKKI KLASTER ishlatiladi, ko'p emas: mashina resursi cheklangan.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

pgserver = pytest.importorskip("pgserver")
psutil = pytest.importorskip("psutil")

from tests import pgown  # noqa: E402


def _tirik(pid: int | None) -> bool:
    if pid is None:
        return False
    try:
        p = psutil.Process(pid)
        return p.is_running() and p.status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False


def _jonli_pg_va_launcher() -> tuple[set[int], set[int]]:
    """(postgres PIDlari, launcher cmd.exe PIDlari) — REGRESSIYA bazasi uchun.

    ⚠️  SANOQ TEST FAYLIDA, `pgown` da EMAS. `pgown` kodida process RO'YXATINI
        aylanish ATAYLAB taqiqlangan (`test_TOZALASH_nom_boyicha_QIDIRMAYDI`):
        u yerda nom bo'yicha tanlash ommaviy o'ldirishga yo'l ochardi. Bu yerda
        esa sanoq FAQAT tasdiqlash uchun — hech narsa to'xtatilmaydi.
    """
    pg: set[int] = set()
    lc: set[int] = set()
    for q in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            nm = (q.info.get("name") or "").lower()
            cmd = " ".join(q.info.get("cmdline") or [])
        except Exception:      # noqa: BLE001
            continue
        if nm.startswith("postgres"):
            pg.add(q.info["pid"])
        elif nm == "cmd.exe" and "postgres.exe" in cmd:
            lc.add(q.info["pid"])
    return pg, lc


def _suratga_ol(pidlar) -> list:
    """`(pid, create_time)` juftliklari — PID QAYTA ISHLATILISHINI sezish uchun.

    ⚠️  Windows PIDlarni qayta beradi. Faqat PID bo'yicha «o'ldimi» deb
        tekshirish qisqa oynada ham yolg'on TIRIK berishi mumkin, shu bois
        tug'ilish vaqti ham yoziladi va keyin solishtiriladi.
    """
    chiqdi = []
    for pid in pidlar:
        try:
            chiqdi.append((pid, psutil.Process(pid).create_time()))
        except Exception:      # noqa: BLE001
            chiqdi.append((pid, None))
    return chiqdi


def _hamon_tirik(surat) -> list:
    """Suratdagi qaysi processlar HAMON O'SHA process bo'lib tirik.

    `create_time` mos kelmasa — PID qayta ishlatilgan, ya'ni bizning process
    O'LGAN. Bu ro'yxat BO'SH bo'lishi kutiladi.
    """
    tirik = []
    for pid, ct in surat:
        try:
            p = psutil.Process(pid)
            if not p.is_running() or p.status() == psutil.STATUS_ZOMBIE:
                continue
            if ct is not None and abs(p.create_time() - ct) > 0.5:
                continue          # PID qayta ishlatilgan — boshqa process
            tirik.append(pid)
        except Exception:      # noqa: BLE001
            continue
    return tirik


def _xom_klaster(yol: Path):
    """Tracker'ni CHETLAB O'TIB klaster ochadi — ya'ni `pgown` uchun «aloqasiz».

    ⚠️  `pgserver.get_server` conftest tomonidan o'ralgan va har chaqiruv
        `pgown.track` ga tushadi. «Aloqasiz» klaster kerak bo'lgani uchun
        sinfning o'zi chaqiriladi.
    """
    from pgserver.postgres_server import PostgresServer
    yol.mkdir(parents=True, exist_ok=True)
    return PostgresServer(yol, cleanup_mode="stop")


# ══ 1. EGALIK: o'zini to'xtatadi, ALOQASIZNI tirik qoldiradi ════════════════

def test_PG_tozalash_FAQAT_oz_klasterini_toxtatadi(tmp_path):
    """⚠️  BU TESTNING MOHIYATI — XAVFSIZLIK, qulaylik emas.

    O'lchanadi: `pgown` ro'yxatidagi klaster o'ladi, ro'yxatda BO'LMAGAN
    klaster esa TIRIK qoladi. Ikkinchi shart buzilsa tozalash begona ishni
    o'ldirishi mumkin degani.
    """
    #  ⚠️  MASHINA BO'YICHA SURAT faqat DIAGNOSTIKA uchun — TASDIQ EMAS.
    #      Oldingi versiya shu to'plamlarni TO'G'RILIK tasdiqi qilib ishlatardi
    #      (`assert not (pg1 - pg0)` va «BEGONA postgres yo'qoldi»). Bu mashinada
    #      bir vaqtda bir nechta seans ishlaydi: har PostgreSQL backend ham
    #      `postgres` nomli, ya'ni begona klasterga bitta ulanish ochilishi/
    #      yopilishi to'plamni siljitadi; boshqa seansning `pytest_sessionfinish`
    #      i esa `cleanup_all` chaqirib o'z klasterlarini TO'DA bilan o'chiradi.
    #      Demak global o'zgarmaslik MASHINA xossasi, `pgown` xossasi EMAS — va
    #      yolg'on qizilning xabari `pgown` ni begona ishni o'ldirishda NOHAQ
    #      ayblardi. To'g'ri tasdiq quyida: AYNIQ PIDlar bo'yicha.
    pg0, lc0 = _jonli_pg_va_launcher()

    mening_yol = tmp_path / "mine" / "pgdata"
    aloqasiz_yol = tmp_path / "other" / "pgdata"
    mening_yol.parent.mkdir(parents=True, exist_ok=True)

    #  (a) MENING klasterim — o'ralgan `get_server` orqali, ya'ni ro'yxatda.
    mening = pgserver.get_server(str(mening_yol))        # noqa: F841
    mening_pid = pgown._pid_from_pgdata(mening_yol)
    #  (b) ALOQASIZ klaster — tracker'dan chetda.
    aloqasiz = _xom_klaster(aloqasiz_yol)
    aloqasiz_pid = pgown._pid_from_pgdata(aloqasiz_yol)

    try:
        #  ⚠️  SURATLAR HOZIR olinadi: process to'xtagandan KEYIN na bolalar
        #      ro'yxatini, na launcher bog'lanishini tiklab bo'lmaydi.
        mening_surat = _suratga_ol(pgown.owned_tree(mening_yol))
        aloqasiz_daraxt = pgown.owned_tree(aloqasiz_yol)
        aloqasiz_surat = _suratga_ol([aloqasiz_pid, *aloqasiz_daraxt])
        #  NC-A MUTATSIYA: ESKI MODEL — postmaster'ning `ppid()` i SHARTSIZ
        #  launcher deb olinadi. Linux'da bu `init` (PID 1) bo'ladi.
        aloqasiz_launcher = None
        try:
            aloqasiz_launcher = psutil.Process(aloqasiz_pid).ppid()
        except Exception:      # noqa: BLE001
            pass

        assert _tirik(mening_pid), "mening klasterim ko'tarilmadi"
        assert _tirik(aloqasiz_pid), "aloqasiz klaster ko'tarilmadi"
        assert mening_pid != aloqasiz_pid
        #  ⚠️  POZITIV NAZORAT: egalik ISBOTLANGAN bo'lishi shart, aks holda
        #      quyidagi «daraxt o'ldi» tasdiqlari BO'SH ro'yxat ustida vakuum.
        assert mening_pid in [p for p, _ in mening_surat], (
            "o'z klasterim egaligi isbotlanmadi (owned_tree bo'sh)")
        assert aloqasiz_pid in aloqasiz_daraxt, (
            "aloqasiz klaster egaligi isbotlanmadi (owned_tree bo'sh)")

        #  ⚠️  LAUNCHER PLATFORMAGA BOG'LIQ — eski kod buni e'tiborsiz qoldirib
        #      `ppid()` ni SHARTSIZ launcher deb olardi.
        #      • Windows: `pg_ctl -l <log> start` postmaster'ni
        #        `cmd /c ""postgres.exe" -D "<pgdata>" ..."` orqali ko'taradi va
        #        `cmd.exe` OTA bo'lib tirik qoladi → HAQIQIY launcher BOR va u
        #        to'xtatishdan keyin o'lishi SHART. Bu yerda uning topilishini
        #        TALAB qilamiz: POZITIV NAZORAT, aks holda pastdagi «launcher
        #        o'ldi» tasdig'i jim vakuumga aylanardi.
        #      • POSIX: `pg_ctl` fork qiladi, bola shell orqali postgres'ni
        #        `exec` qiladi, `pg_ctl` esa chiqib ketadi → postmaster YETIM
        #        qoladi va `init` (PID 1) ga o'tadi. Launcher YO'Q, `ppid()` esa
        #        1 bo'ladi. Eski tasdiq aynan shu sababli Linux'da HAR DOIM
        #        yiqilardi (`init` hech qachon o'lmaydi), oqish EMAS.
        #  NC-A MUTATSIYA: pozitiv nazorat olib tashlandi.

        #  ⚠️  `cleanup_all()` GLOBAL ro'yxatni bo'shatadi. Boshqa testlarning
        #      (masalan `tests/cash` ning seans klasteri) yozuvlariga tegmasligi
        #      uchun ro'yxat VAQTINCHA faqat o'z yozuvimizga qisqartiriladi.
        saqlangan = pgown._OWNED[:]
        mening_yozuv = [r for r in saqlangan
                        if str(r["pgdata"]) == str(mening_yol)]
        assert mening_yozuv, "mening klasterim ro'yxatga TUSHMAGAN (tracker ishlamadi)"
        try:
            pgown._OWNED[:] = mening_yozuv
            pgown.cleanup_all(verbose=True)
        finally:
            pgown._OWNED[:] = [r for r in saqlangan if r not in mening_yozuv]

        #  ══ (1) O'Z klasterimning AYNIQ daraxti o'ldi ══════════════════════
        qoldi_mening = _hamon_tirik(mening_surat)
        assert not qoldi_mening, (
            f"o'z klasterim daraxtidan process QOLDI: {qoldi_mening}")

        #  ══ (2) BEGONA klaster TEGILMADI ═══════════════════════════════════
        assert _tirik(aloqasiz_pid), (
            "ALOQASIZ klaster O'LDIRILDI — tozalash egalikdan tashqariga chiqdi")
        #  ...va hamon TIRIK klaster sifatida IZCHIL: egalik daraxti bo'sh emas
        #  va postmaster hamon uning ichida.
        hali = pgown.owned_tree(aloqasiz_yol)
        assert aloqasiz_pid in hali, (
            "ALOQASIZ klasterning egalik daraxti buzildi — postmaster tirik, "
            f"lekin daraxt {hali}")
        #  ...va PAPKASI ham tegilmagan — egalik chegarasining PAPKA tomoni.
        assert aloqasiz_yol.is_dir(), (
            "ALOQASIZ klaster papkasi `cleanup_all` da o'chirildi — tozalash "
            "egalikdan tashqariga chiqdi")

        #  ══ O'zimizdan keyin: ALOQASIZ klasterni ATAYLAB to'xtatamiz ═══════
        #  ⚠️  U BEGONA QOLADI — `_OWNED` ga qo'shilmaydi, `adopt` qilinmaydi.
        try:
            aloqasiz.cleanup()
        except Exception:      # noqa: BLE001
            pass
        qoldi = pgown.owned_tree(aloqasiz_yol)
        if qoldi:
            pgown._stop_tree(qoldi)

        #  AYNIQ postmaster + o'lchangan bolalar o'ldi (PID qayta ishlatilishiga
        #  chidamli: `create_time` ham solishtiriladi).
        qoldi_aloqasiz = _hamon_tirik(aloqasiz_surat)
        assert not qoldi_aloqasiz, (
            f"begona klaster daraxtidan process QOLDI: {qoldi_aloqasiz}")
        #  HAQIQIY launcher aniqlangan bo'lsa — u ham o'ldi. `None` bo'lsa
        #  (POSIX) TASDIQLANMAYDI: tekshirishga narsa yo'q.
        #  NC-A MUTATSIYA: eski SHARTSIZ tasdiq.
        assert not _tirik(aloqasiz_launcher), (
            "aloqasiz klasterning launcher `cmd.exe` i TIRIK qoldi")

        #  ══ PAPKA: process O'LGANI ISBOTLANGANDAN KEYIN ════════════════════
        #  ⚠️  BU YERDA OQISH BOR EDI (o'lchangan: 37.5 MB/yurish). `pgserver`
        #      `cleanup_mode='stop'` da serverni to'xtatadi, lekin `pgdata` ni
        #      O'CHIRMAYDI (`postgres_server.py:236-237` dagi `return` :240 dagi
        #      `rmtree` ga yetib bormaydi); klaster esa ATAYLAB kuzatilmagani
        #      uchun `pgown.cleanup_all` ham uni ko'rmaydi.
        #  ⚠️  OQISHNING O'ZINI QADAB QO'YAMIZ: papka tozalashdan OLDIN BOR
        #      bo'lishi SHART. Aks holda regressiya hech narsa o'lchamasdi —
        #      `remove_dead_pgdata` «allaqachon yo'q» qaytarib jim o'tardi va
        #      tasdiq ham shuni qabul qilardi.
        assert aloqasiz_yol.is_dir(), (
            "begona klasterning `pgdata` papkasi tozalashdan OLDIN yo'q — "
            "oqish regressiyasi ma'nosini yo'qotdi")
        natija = pgown.remove_dead_pgdata(aloqasiz_yol, must_be_under=tmp_path)
        assert natija == "o'chirildi", natija

        #  ══ REGRESSIYA: AYNIQ YO'L bo'yicha, hajm taxminisiz ═══════════════
        assert not aloqasiz_yol.exists(), (
            f"aloqasiz klaster papkasi QOLDI: {aloqasiz_yol}")
        assert not mening_yol.exists(), (
            f"kuzatilgan klaster papkasi QOLDI: {mening_yol}")
        assert tmp_path.is_dir(), "tmp_path O'CHIRILDI — ota daraxtga tegildi"

        #  ⚠️  DIAGNOSTIKA, TASDIQ EMAS: mashina bo'yicha o'zgarish faqat
        #      yiqilganda o'qish uchun chop etiladi.
        pg1, lc1 = _jonli_pg_va_launcher()
        print(f"[diag] postgres {len(pg0)} -> {len(pg1)} "
              f"(+{len(pg1 - pg0)} / -{len(pg0 - pg1)})  "
              f"launcher {len(lc0)} -> {len(lc1)} "
              f"(+{len(lc1 - lc0)} / -{len(lc0 - lc1)})")
    finally:
        #  ⚠️  ENG OXIRGI HIMOYA. Yuqorida biror tasdiq yiqilsa ham 37.5 MB
        #      papka QOLMASIN: oldingi versiyada tozalash FAQAT muvaffaqiyatli
        #      yo'lda bo'lgani uchun HAR QIZIL yurish oqishni qaytarardi.
        #  ⚠️  BU BLOK HECH NARSA TASDIQLAMAYDI va HECH QACHON istisno
        #      ko'tarmaydi — aks holda ASL yiqilishni NIQOBLARDI.
        #  ⚠️  Muvaffaqiyatli yo'lda no-op: `cleanup()` idempotent, `owned_tree`
        #      bo'sh, `remove_dead_pgdata` «allaqachon yo'q» qaytaradi.
        try:
            aloqasiz.cleanup()
        except Exception:      # noqa: BLE001
            pass
        try:
            q = pgown.owned_tree(aloqasiz_yol)
            if q:
                pgown._stop_tree(q)
        except Exception:      # noqa: BLE001
            pass
        try:
            pgown.remove_dead_pgdata(aloqasiz_yol, must_be_under=tmp_path)
        except Exception:      # noqa: BLE001
            pass


# ══ 2. EGALIK ISBOTLANMASA — HECH NARSA TO'XTATILMAYDI ═════════════════════

def test_EGALIK_isbotlanmasa_TEGILMAYDI(tmp_path):
    """⚠️  PID QAYTA ISHLATILISHI. Windows PID'larni qayta beradi va eskirgan
        `postmaster.pid` butunlay BOSHQA processni ko'rsatishi mumkin.
        `pgserver` ning o'z fallback'i buni TEKSHIRMAYDI
        (`utils.PostmasterInfo._init_process_meta` da `create_time` solishtiruvi
        IZOHGA OLINGAN), ya'ni u begona processni `terminate()` qilishi mumkin.
        Bu yerda uchinchi shart — JONLI processning buyruq satri — talab
        qilinadi, shu bois quyidagi holatlar BO'SH ro'yxat beradi.
    """
    d = tmp_path / "soxta"
    d.mkdir()

    #  (a) `postmaster.pid` YO'Q -> egalik yo'q
    assert pgown.owned_tree(d) == []

    #  (b) `postmaster.pid` MENING python processimni ko'rsatadi. PID TIRIK,
    #      lekin u postgres EMAS va buyruq satrida bu yo'l YO'Q.
    (d / "postmaster.pid").write_text(f"{os.getpid()}\n{d}\n1\n5432\n\n\n\nready\n")
    assert pgown.owned_tree(d) == [], (
        "tirik, lekin BEGONA process egalik deb sanaldi — bu kill xavfi")

    #  (c) mavjud bo'lmagan PID -> egalik yo'q
    (d / "postmaster.pid").write_text(f"{os.getpid() + 100000}\n{d}\n1\n5432\n\n\n\nready\n")
    assert pgown.owned_tree(d) == []

    #  (d) buzuq fayl -> egalik yo'q (istisno ko'tarilmaydi)
    (d / "postmaster.pid").write_text("bu son emas\n")
    assert pgown.owned_tree(d) == []
    (d / "postmaster.pid").write_text("")
    assert pgown.owned_tree(d) == []


def test_TOZALASH_nom_boyicha_QIDIRMAYDI():
    """⚠️  REGRESSIYA TO'SIG'I: tozalash kodida process NOMI bo'yicha tanlash
        yoki ommaviy o'ldirish PAYDO BO'LMASIN. Bu mashinada yuzlab begona
        `postgres.exe` bor — bitta `taskkill /IM` butun boshqa ishni yo'q qilardi.
    """
    import io as _io
    import tokenize

    #  ⚠️  FAQAT BAJARILADIGAN KOD tekshiriladi. Izohlar va satr literallari
    #      CHIQARIB TASHLANADI, chunki bu modul taqiqlarning O'ZINI izohda
    #      nomma-nom sanaydi (`taskkill /IM ...` TAQIQ deb yozilgan) — xom matn
    #      bo'yicha qidiruv o'z hujjatiga urilib yolg'on qizil berardi.
    kod = []
    with _io.open(pgown.__file__, "rb") as fh:
        for tok in tokenize.tokenize(fh.readline):
            if tok.type in (tokenize.COMMENT, tokenize.STRING):
                continue
            kod.append(tok.string)
    kod = " ".join(kod)
    for taqiq in ("/IM", "process_iter", "pkill", "killall", "Get-Process",
                  "taskkill"):
        assert taqiq not in kod, (
            f"tozalash KODIDA nom bo'yicha qidiruv: {taqiq!r} — bu mashinada "
            f"yuzlab begona postgres bor, bitta ommaviy o'ldirish boshqa ishni "
            f"yo'q qilardi")
    #  Egalik uchun uchta shart KODDA bo'lishi shart.
    for shart in ("_cmdline_has", "cmdline", "_pid_from_pgdata", "_normalize"):
        assert shart in kod, shart


# ══ 3. QATLAM 2: `cleanup()` YIQILSA HAM server to'xtatiladi ════════════════

def test_PG_cleanup_YIQILSA_HAM_server_toxtatiladi(tmp_path):
    """⚠️  BU ENG MUHIM FUNKSIONAL TEST. `pgserver._cleanup` refcount yozuvini
        ISH BAJARILISHIDAN OLDIN o'chiradi (`get_and_remove` ni birinchi
        chaqiradi), shu bois u yerdagi HAR QANDAY istisno serverni to'xtatmasdan
        qoldiradi VA `atexit` qayta urinishini ham befoyda qiladi — chiqish kodi
        esa 0 bo'ladi, ya'ni oqish KO'RINMAYDI.
        O'lchangan: shu holatda himoyasiz yurish 1 yetim postmaster qoldiradi.
    """
    import subprocess

    import pgserver.postgres_server as ps

    yol = tmp_path / "boom" / "pgdata"
    yol.parent.mkdir(parents=True, exist_ok=True)
    srv = pgserver.get_server(str(yol))
    pid = pgown._pid_from_pgdata(yol)
    assert _tirik(pid)

    asl = ps.pg_ctl

    def _boom(*a, **kw):
        raise subprocess.TimeoutExpired(cmd="pg_ctl stop", timeout=0.1)

    ps.pg_ctl = _boom
    saqlangan = pgown._OWNED[:]
    mening = [r for r in saqlangan if str(r["pgdata"]) == str(yol)]
    assert mening, "ro'yxatga tushmagan"
    try:
        pgown._OWNED[:] = mening
        pgown.cleanup_all(verbose=True)
    finally:
        ps.pg_ctl = asl
        pgown._OWNED[:] = [r for r in saqlangan if r not in mening]

    assert not _tirik(pid), (
        "`cleanup()` istisno bergach server TIRIK qoldi — egalik-stop ishlamadi")


# ══ 4. QATLAM 3: KONSTRUKTOR yiqilsa klaster EGALLANADI ════════════════════

def test_PG_konstruktor_yiqilsa_klaster_EGALLANADI(tmp_path):
    """⚠️  `get_server` QAYTMASA tracker ishlamaydi: postmaster na job obyektiga,
        na tozalash ro'yxatiga tushadi, `pgserver` ning `atexit` handleri ham jim
        qaytadi (pid ro'yxatga ENG OXIRIDA qo'shiladi va unga yetib borilmagan).
        Shu bois `get_server` istisno bergan taqdirda ham klaster EGALLANADI.
    """
    import pgserver.postgres_server as ps

    yol = tmp_path / "ctor" / "pgdata"
    yol.parent.mkdir(parents=True, exist_ok=True)
    asl = ps.PostgresServer.ensure_postgres_running

    def _keyin_yiqil(self):
        asl(self)                       # server HAQIQATAN ko'tariladi
        raise RuntimeError("konstruktor server ko'tarilgandan KEYIN yiqildi")

    ps.PostgresServer.ensure_postgres_running = _keyin_yiqil
    oldin = len(pgown._OWNED)
    try:
        with pytest.raises(RuntimeError):
            pgserver.get_server(str(yol))
    finally:
        ps.PostgresServer.ensure_postgres_running = asl

    pid = pgown._pid_from_pgdata(yol)
    assert _tirik(pid), "holat yasalmadi: server ko'tarilmagan"
    assert len(pgown._OWNED) == oldin + 1, (
        "konstruktor yiqilgach klaster EGALLANMADI — u hech qayerda kuzatilmaydi")

    #  O'zimizdan keyin tozalaymiz.
    saqlangan = pgown._OWNED[:]
    mening = [r for r in saqlangan if str(r["pgdata"]) == str(yol)]
    try:
        pgown._OWNED[:] = mening
        pgown.cleanup_all(verbose=False)
    finally:
        pgown._OWNED[:] = [r for r in saqlangan if r not in mening]
    assert not _tirik(pid), "egallangan klaster to'xtatilmadi"


# ══ 5. QATLAM 1: postmaster HAQIQATAN job obyekti ICHIDAMI ═════════════════

@pytest.mark.skipif(os.name != "nt", reason="job obyekti faqat Windows'da")
def test_PG_postmaster_JOB_ichida_va_job_KILL_ON_CLOSE(tmp_path):
    """⚠️  QATTIQ O'LIMNI TESTDA QAYTA YASAB BO'LMAYDI: `os._exit` yoki
        `taskkill /F` butun pytest seansini o'ldirardi, ya'ni bunday test
        TO'PLAMGA QO'SHILSA har yurishni buzardi (o'lchangan: aynan shu
        sababdan reproduksiya probalari repoda SAQLANMADI).
        Shu bois bu yerda OS KAFOLATINING SHARTI tekshiriladi: postmaster
        `KILL_ON_JOB_CLOSE` bayrog'i o'rnatilgan job ichida bo'lsa, pytest
        processi QANDAY o'lsa ham OS job a'zolarini o'zi tugatadi.
    ⚠️  BOLALAR ALOHIDA QO'SHILADI: `AssignProcessToJobObject` MAVJUD bolalarni
        o'z-o'zidan olmaydi, postmaster esa yordamchi processlarini (checkpointer,
        walwriter, ...) ishga tushishida fork qiladi. Shu bois bu test
        BOLALARNI HAM tekshiradi — aks holda job faqat postmaster'ni o'ldirib,
        bolalari yetim qolardi.
    """
    import ctypes
    from ctypes import wintypes as w

    yol = tmp_path / "job" / "pgdata"
    yol.parent.mkdir(parents=True, exist_ok=True)
    srv = pgserver.get_server(str(yol))
    pid = pgown._pid_from_pgdata(yol)
    assert _tirik(pid)

    j = pgown._ensure_job()
    assert j is not None, "job obyekti yaratilmagan — qattiq o'lim himoyasi YO'Q"
    k32, job = j

    #  (a) `KILL_ON_JOB_CLOSE` bayrog'i O'RNATILGANMI (0x2000).
    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [(n, ctypes.c_ulonglong) for n in
                    ("r_op", "w_op", "o_op", "r_tx", "w_tx", "o_tx")]

    class BASIC(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong),
                    ("PerJobUserTimeLimit", ctypes.c_longlong),
                    ("LimitFlags", w.DWORD),
                    ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t),
                    ("ActiveProcessLimit", w.DWORD),
                    ("Affinity", ctypes.c_size_t),
                    ("PriorityClass", w.DWORD),
                    ("SchedulingClass", w.DWORD)]

    class EXT(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", BASIC), ("IoInfo", IO_COUNTERS),
                    ("ProcessMemoryLimit", ctypes.c_size_t),
                    ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t),
                    ("PeakJobMemoryUsed", ctypes.c_size_t)]

    info = EXT()
    qaytgan = w.DWORD(0)
    ok = k32.QueryInformationJobObject(job, 9, ctypes.byref(info),
                                       ctypes.sizeof(info), ctypes.byref(qaytgan))
    assert ok, "QueryInformationJobObject yiqildi"
    assert info.BasicLimitInformation.LimitFlags & 0x2000, (
        "KILL_ON_JOB_CLOSE o'rnatilmagan — process o'lsa job a'zolari TIRIK qoladi")

    #  (b) postmaster VA uning bolalari job ICHIDAMI.
    def _jobdami(p: int) -> bool:
        k32.OpenProcess.restype = w.HANDLE
        h = k32.OpenProcess(0x1000, False, int(p))      # PROCESS_QUERY_LIMITED_INFORMATION
        assert h, f"OpenProcess({p}) yiqildi"
        try:
            natija = w.BOOL(0)
            assert k32.IsProcessInJob(h, job, ctypes.byref(natija)), "IsProcessInJob"
            return bool(natija.value)
        finally:
            k32.CloseHandle(h)

    daraxt = pgown.owned_tree(yol)
    assert len(daraxt) >= 2, f"bolalar topilmadi: {daraxt}"
    tashqarida = [p for p in daraxt if not _jobdami(p)]
    assert not tashqarida, (
        f"job'dan TASHQARIDA qolgan processlar {tashqarida} — qattiq o'limda "
        f"ular YETIM qolardi")

    #  O'zimizdan keyin tozalaymiz.
    saqlangan = pgown._OWNED[:]
    mening = [r for r in saqlangan if str(r["pgdata"]) == str(yol)]
    try:
        pgown._OWNED[:] = mening
        pgown.cleanup_all(verbose=False)
    finally:
        pgown._OWNED[:] = [r for r in saqlangan if r not in mening]
    assert not _tirik(pid)
