# -*- coding: utf-8 -*-
"""1C Discovery to'plami — operator CLI.

    python -m app.tools.discovery_1c validate --dir ./binos-fayzan-1c-discovery-20260928-0921
    python -m app.tools.discovery_1c summary  --dir ./binos-fayzan-1c-discovery-20260928-0921
    python -m app.tools.discovery_1c synth    --out ./namuna         # sintetik to'plam yozadi

Bu buyruqlar **1C ga ulanmaydi** va bazaga tegmaydi — ular faqat faylni o'qiydi. Shu bois
ularni internetsiz mashinada, mijoz nusxasi yonida ishlatish xavfsiz.

`validate` fail-closed: sxema, ishonch qoidasi, holat mantiqi yoki sir tekshiruvi buzilsa,
chiqish kodi 1 bo'ladi va sabab ko'rsatiladi. Sir topilgan hollarda qiymatning O'ZI chop
etilmaydi — faqat yo'li.
"""
from __future__ import annotations

import argparse
import json
import sys

from app.services.discovery_1c import STATUS_BLOCKED, STATUS_COMPLETE
from app.services.discovery_1c.bundle import DiscoveryError, load_dir, write_dir


def _validate(a) -> int:
    b = load_dir(a.dir, allow_live_source=a.allow_live_source)
    by_conf: dict[str, int] = {}
    for m in b.mappings:
        by_conf[m["confidence"]] = by_conf.get(m["confidence"], 0) + 1
    print(json.dumps({
        "ok": True,
        "schema_version": b.discovery["schema_version"],
        "content_sha256": b.content_sha256,
        "status": b.overall_status,
        "source_kind": b.discovery["source"]["kind"],
        "mappings": len(b.mappings),
        "by_confidence": dict(sorted(by_conf.items())),
        "objects_swept": len(b.sweep["objects"]),
        "counts": len(b.counts["counts"]),
        "samples": sorted(b.samples),
    }, ensure_ascii=False, indent=1))
    return 0 if b.overall_status != STATUS_BLOCKED else 2


def _summary(a) -> int:
    b = load_dir(a.dir, allow_live_source=a.allow_live_source)
    src = b.discovery["source"]
    print(f"manba      : {src['kind']} · platforma {src['platform_version'] or '—'} · "
          f"konfiguratsiya {src['configuration_name'] or '—'} {src['configuration_version'] or ''}")
    print(f"holat      : {b.overall_status}")
    for s in b.status["sections"]:
        mark = "ok " if s["status"] == "ok" else "XX "
        print(f"  {mark}{s['name']}" + (f" — {s['error']}" if s["error"] else ""))
    print(f"xesh       : {b.content_sha256}")
    print("")
    print(f"{'NISHON':<34} {'DARAJA':<10} MANBA")
    for m in sorted(b.mappings, key=lambda x: x["target"]):
        where = " / ".join(x for x in (m["source_object"], m["source_field"]) if x) or "—"
        print(f"{m['target']:<34} {m['confidence']:<10} {where}")
        for e in m["errors"]:
            print(f"{'':<34} {'':<10} ⚠ {e}")
    if b.overall_status != STATUS_COMPLETE:
        print("\n⚠ To'plam to'liq emas — yuqoridagi bo'limlarga qarang.")
    return 0


def _synth(a) -> int:
    sys.path.insert(0, "")                     # tests/ paketini topish uchun
    from tests.discovery_1c_synth import members            # noqa: PLC0415
    written = write_dir(a.out, members())
    print(json.dumps({"out": a.out, "files": written}, ensure_ascii=False, indent=1))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="discovery_1c")
    sub = ap.add_subparsers(dest="cmd", required=True)

    for name, fn in (("validate", _validate), ("summary", _summary)):
        p = sub.add_parser(name)
        p.add_argument("--dir", required=True, help="to'plam papkasi")
        p.add_argument("--allow-live-source", action="store_true",
                       help="jonli bazadan yig'ilgan to'plamni qabul qilish (ATAYLAB)")
        p.set_defaults(fn=fn)

    p = sub.add_parser("synth")
    p.add_argument("--out", required=True)
    p.set_defaults(fn=_synth)

    a = ap.parse_args(argv)
    try:
        return a.fn(a)
    except DiscoveryError as e:
        print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False, indent=1))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
