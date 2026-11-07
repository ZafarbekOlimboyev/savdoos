"""RELIZ MUHRINI YOZADI — `app/_build_info.py` (generatsiya, qo'lda tahrirlanmaydi).

Nega kerak: Railway git o'zgaruvchilarini `rollback` deploymentida BERMAYDI
(nazoratli tajriba, 2026-11-07), shu bois commit SHA muhit o'zgaruvchisidan
olinganda rollback'dan keyin YO'QOLADI. Muhr ARTEFAKT ICHIDA yashaydi va
kod bilan birga ko'chadi. Batafsil: `app/core/build_identity.py`.

ISHLATISH (reliz nomzodi tayyor bo'lgach, operator mashinasida):

    python scripts/seal_build_identity.py              # QURUQ YURISH
    python scripts/seal_build_identity.py --apply      # muhrni YOZADI
    python scripts/seal_build_identity.py --apply --source-only   # commit DA'VOSIZ
    python scripts/seal_build_identity.py --verify     # mavjud muhr izchilmi

⚠️  IFLOS ISHCHI DARAXT RAD ETILADI. Sabab: muhr `COMMIT=C` deb da'vo
    qiladi, lekin fayllar `C` dan FARQ qilsa bu YOLG'ON da'vo bo'ladi —
    aynan `null` dan battar holat (`build_info()` darsi). Ataylab
    muhrlanmagan kodni chiqarish kerak bo'lsa `--source-only` ishlating:
    u faqat manba digestini yozadi, commitni DA'VO QILMAYDI.

⚠️  MUHRNI REPOGA COMMIT QILISH SHART EMAS. Railway build kontekstiga
    fayl yetib borishi kifoya. Agar commit qilinsa, keyingi commit SHA
    o'zgaradi va muhr «bir qadam orqada» commitni ko'rsatadi — shu bois
    `BRANCH_REF` va `SEALED_AT` ham yoziladi, provenance manifesti esa
    `source_digest` bo'yicha bog'lanadi (commit bo'yicha EMAS).
"""
from __future__ import annotations

import argparse
import datetime
import getpass
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
SERVER = HERE.parent
sys.path.insert(0, str(SERVER))

from app.core import build_identity as B  # noqa: E402

STAMP = SERVER / "app" / "_build_info.py"

TEMPLATE = '''# -*- coding: utf-8 -*-
"""AVTOMATIK GENERATSIYA — QO'LDA TAHRIRLAMANG.

Yozdi: `scripts/seal_build_identity.py`. Mazmuni `app/core/build_identity.py`
tomonidan o'qiladi va `SOURCE_DIGEST` runtime'da QAYTA hisoblanib
solishtiriladi: mos kelmasa `commit` E'LON QILINMAYDI (fail-closed).
"""
STAMP_VERSION = {stamp_version!r}
COMMIT = {commit!r}
SOURCE_DIGEST = {digest!r}
BRANCH_REF = {branch!r}
SEALED_AT = {at!r}
SEALED_BY = {by!r}
'''


def git(*args: str) -> str:
    r = subprocess.run(["git", *args], cwd=str(SERVER), capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} yiqildi: "
                         f"{(r.stderr or '').strip()[:200]}")
    return (r.stdout or "").strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--source-only", action="store_true",
                    help="commitni DA'VO QILMA — faqat manba digesti")
    ap.add_argument("--verify", action="store_true",
                    help="mavjud muhr kod bilan izchilmi (yozuv YO'Q)")
    ap.add_argument("--from-env", action="store_true",
                    help="commitni `git` dan EMAS, muhit o'zgaruvchisidan ol "
                         "(build konteksti: `.git` yo'q, lekin platforma "
                         "SHA beradi)")
    a = ap.parse_args()

    #  ⚠️  Digest muhrning O'ZINI qamramaydi (`EXCLUDE_NAMES`), shu bois
    #      muhr bor-yo'qligidan QAT'I NAZAR bir xil chiqadi.
    fayllar = B.iter_source_files()
    digest = B.compute_source_digest(files=fayllar)
    print(f"manba fayllari : {len(fayllar)}")
    print(f"manba digesti  : {digest}")

    if a.verify:
        muhr = B.read_stamp()
        if muhr is None:
            print("MUHR: YO'Q")
            return 2
        mos = str(muhr.get("SOURCE_DIGEST") or "") == digest
        print(f"MUHR commit    : {muhr.get('COMMIT')}")
        print(f"MUHR digesti   : {muhr.get('SOURCE_DIGEST')}")
        print(f"MUHRLANGAN     : {muhr.get('SEALED_AT')} ({muhr.get('BRANCH_REF')})")
        print(f"IZCHILMI       : {'HA' if mos else 'YO`Q — artefakt muhrlangandan KEYIN o`zgargan'}")
        return 0 if mos else 1

    commit = None
    branch = None
    if a.from_env and not a.source_only:
        #  ⚠️  BUILD KONTEKSTI REJIMI. Railway git-manbali servisni
        #      klonlab build qiladi, lekin `.git` build kontekstiga
        #      KIRMAYDI — ya'ni `git rev-parse` ISHLAMAYDI. Agar platforma
        #      SHA'ni BUILD muhitida bersa, muhr shu yerda yoziladi va
        #      artefakt ichida QOLADI (runtime'da o'zgaruvchi yo'qolsa
        #      ham). Bu `rollback` muammosini MANBADA yopadi.
        #
        #  ⚠️  O'LCHANMAGAN TAXMIN QILINMAYDI: `savdoos` servisining BUILD
        #      muhitida `RAILWAY_GIT_COMMIT_SHA` bor-yo'qligi O'LCHANMAGAN
        #      (runtime'da YO'Q ekani o'lchangan). Shu bois qiymat
        #      topilmasa skript RAD etadi — jim `source-only` ga TUSHMAYDI.
        import os
        for key in B.ENV_KEYS:
            val = (os.getenv(key) or "").strip()
            if val:
                commit = val
                branch = (os.getenv("RAILWAY_GIT_BRANCH") or "").strip() or None
                print(f"commit         : {commit}  (manba: env:{key})")
                break
        if commit is None:
            print()
            print("TO'XTADI: --from-env berildi, lekin commit o'zgaruvchisi YO'Q.")
            print(f"   izlandi: {', '.join(B.ENV_KEYS)}")
            print("   Yo'llar: (a) build muhitida o'zgaruvchini ta'minlang; "
                  "(b) commit DA'VOSIZ muhr uchun `--source-only`.")
            return 7
    elif not a.source_only:
        iflos = git("status", "--porcelain")
        if iflos:
            qatorlar = iflos.splitlines()
            print()
            print("TO'XTADI: ISHCHI DARAXT IFLOS — muhr YOLG'ON commit da'vo "
                  f"qilardi ({len(qatorlar)} fayl).")
            for q in qatorlar[:10]:
                print(f"   {q}")
            if len(qatorlar) > 10:
                print(f"   … va {len(qatorlar) - 10} ta boshqa")
            print()
            print("Yo'llar: (a) o'zgarishlarni commit qiling; "
                  "(b) commit DA'VOSIZ muhr uchun `--source-only`.")
            return 3
        commit = git("rev-parse", "HEAD")
        try:
            branch = git("rev-parse", "--abbrev-ref", "HEAD")
        except SystemExit:
            branch = None
        print(f"commit         : {commit}")
        print(f"branch         : {branch}")
    else:
        print("commit         : <DA'VO QILINMAYDI (--source-only)>")

    matn = TEMPLATE.format(
        stamp_version="bs1", commit=commit, digest=digest, branch=branch,
        at=datetime.datetime.now(datetime.timezone.utc)
        .replace(microsecond=0).isoformat(),
        by=(getpass.getuser() or "unknown"))

    if not a.apply:
        print()
        print("[QURUQ YURISH] fayl yozilmadi. Bajarish: --apply")
        print("-" * 60)
        print(matn)
        return 0

    STAMP.write_text(matn, encoding="utf-8")
    print()
    print(f"YOZILDI: {STAMP}")

    #  ── POST-SHART: muhr HAQIQATAN izchilmi (ko'r ishonch YO'Q) ────────
    #  ⚠️  Yozgandan keyin modul keshini tozalab QAYTA o'qiymiz: aks holda
    #      «yozdim» degan da'vo tekshirilmagan bo'lib qolardi.
    for nom in ("app._build_info",):
        sys.modules.pop(nom, None)
    muhr = B.read_stamp()
    hozirgi = B.compute_source_digest()
    if muhr is None:
        print("XATO: muhr o'qilmadi")
        return 4
    if str(muhr.get("SOURCE_DIGEST")) != hozirgi:
        print(f"XATO: muhr digesti kod bilan mos emas "
              f"({muhr.get('SOURCE_DIGEST')} != {hozirgi})")
        return 5
    if commit is not None and str(muhr.get("COMMIT")) != commit:
        print("XATO: muhr commiti yozilmadi")
        return 6
    print("TASDIQ: muhr kod bilan IZCHIL "
          f"(commit={'bor' if commit else 'yo`q'}, digest mos)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
