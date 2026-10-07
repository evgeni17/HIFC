# SPDX-FileCopyrightText: 2026 EOK
# SPDX-License-Identifier: Apache-2.0
"""Замороженные версии ассетов: суммы, независимость от разрабатываемого кода, записи в VERSIONS.json.

    python3 tests/test_frozen.py
"""
import glob
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LIBS = os.path.join(ROOT, "python3.13libs")
sys.path.insert(0, LIBS)

import hifc  # noqa: E402

FAILS = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def const(path, name):
    for line in open(path):
        if line.startswith(name):
            return line.split("=", 1)[1].strip().strip('"')
    return ""


def version_key(v):
    return tuple(int(x) for x in v.split("."))


def main():
    versions = json.load(open(os.path.join(ROOT, "VERSIONS.json")))["assets"]
    frozen_pkgs = sorted(glob.glob(os.path.join(LIBS, "hifc_*")))
    print("1. Замороженные копии пакета")
    check(bool(frozen_pkgs), "есть хотя бы одна замороженная копия: %r" % [os.path.basename(p) for p in frozen_pkgs])
    frozen_versions = []
    for pkg in frozen_pkgs:
        name = os.path.basename(pkg)
        ver = name[len("hifc_"):].replace("_", ".")
        frozen_versions.append(ver)
        init = os.path.join(pkg, "__init__.py")
        check(const(init, "FROZEN") == "True", "%s: FROZEN = True" % name)
        check(const(init, "HDA_VERSION") == ver, "%s: HDA_VERSION = %s" % (name, const(init, "HDA_VERSION")))

        sums_file = os.path.join(pkg, "FROZEN.sha256")
        check(os.path.isfile(sums_file), "%s: есть FROZEN.sha256" % name)
        if os.path.isfile(sums_file):
            bad = []
            listed = set()
            for line in open(sums_file):
                want, rel = line.split("  ", 1)
                rel = rel.strip()
                listed.add(rel)
                p = os.path.join(LIBS, rel) if rel.startswith("hifc_") else os.path.join(ROOT, rel)
                if not os.path.isfile(p) or sha256(p) != want:
                    bad.append(rel)
            check(not bad, "%s: суммы совпадают (расходятся: %r)" % (name, bad))
            on_disk = {os.path.join(name, f) for f in os.listdir(pkg)
                       if f.endswith(".py")}
            check(on_disk <= listed, "%s: новых файлов в замороженной копии нет (%r)" % (name, sorted(on_disk - listed)))

        # замороженный код не должен звать изменяемый пакет
        leaks = []
        for f in glob.glob(os.path.join(pkg, "*.py")):
            txt = open(f).read()
            if re.search(r"(?m)^\s*(import|from)\s+hifc\b(?!_)", txt) or re.search(r"import hifc\.sop", txt):
                leaks.append(os.path.basename(f))
        check(not leaks, "%s: ссылок на изменяемый пакет нет (%r)" % (name, leaks))

        rec = versions.get(ver, {})
        check(rec.get("status") == "frozen", "VERSIONS.json: ::%s помечена frozen" % ver)
        check(rec.get("package") == name and rec.get("vendor") and rec.get("houdini") and rec.get("python"),
              "VERSIONS.json: ::%s описывает пакет и окружение" % ver)
        for asset in rec.get("assets", []):
            check(os.path.isfile(os.path.join(ROOT, "otls", asset)), "::%s: файл %s на месте" % (ver, asset))

    print("2. Разработка впереди всех замороженных")
    check(hifc.FROZEN is False, "разрабатываемый пакет не заморожен")
    newer = [v for v in frozen_versions if version_key(v) >= version_key(hifc.HDA_VERSION)]
    check(not newer, "версия разработки ::%s старше замороженных %r" % (hifc.HDA_VERSION, frozen_versions))
    dev = [v for v, r in versions.items() if r.get("status") == "development"]
    check(dev == [hifc.HDA_VERSION], "в VERSIONS.json ровно одна запись разработки и это ::%s (%r)"
          % (hifc.HDA_VERSION, dev))

    print("3. Набор библиотек у всех версий согласован")
    for ver, rec in versions.items():
        if rec.get("status") != "frozen":
            continue
        ok = rec.get("vendor") == hifc.VENDOR or hifc.VENDOR in [rec.get("vendor")] + list(rec.get("also_tested", []))
        check(ok, "::%s проверена с текущим набором библиотек (иначе внесите его в also_tested)" % ver)

    print("\n%s (%d failures)" % ("PASSED" if not FAILS else "FAILED", len(FAILS)))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
