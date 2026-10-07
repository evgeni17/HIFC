# SPDX-FileCopyrightText: 2026 EOK
# SPDX-License-Identifier: Apache-2.0
"""Проверки самого репозитория (без Houdini): версии зависимостей, баннер, имена типов.

    python3 tests/test_repo.py
"""
import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "python3.13libs"))

import hifc  # noqa: E402

FAILS = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


def main():
    print("1. Версии зависимостей закреплены в одном наборе")
    versions = json.load(open(os.path.join(ROOT, "VERSIONS.json")))
    dev = [v for v in versions["assets"].values() if v.get("status") == "development"]
    # сразу после выпуска записи разработки нет до freeze.py --next: тогда сверяемся с только что замороженной
    released = not dev and versions["assets"].get(hifc.HDA_VERSION, {}).get("status") == "frozen"
    check(len(dev) == 1 or released,
          "в VERSIONS.json одна запись разработки, либо это состояние сразу после выпуска ::%s" % hifc.HDA_VERSION)
    if dev or released:
        rec = dev[0] if dev else versions["assets"][hifc.HDA_VERSION]
        check(rec["vendor"] == hifc.VENDOR, "VERSIONS.json vendor == hifc.VENDOR")
        check(rec["plugin"] == hifc.__version__, "VERSIONS.json plugin == __version__ (%s)" % rec["plugin"])
        check(rec["houdini"] == hifc.HOUDINI_TESTED, "VERSIONS.json houdini == HOUDINI_TESTED")
        check(hifc.HDA_VERSION in versions["assets"], "версия ассетов %s есть в VERSIONS.json" % hifc.HDA_VERSION)
    readme = open(os.path.join(ROOT, "vendor", "README.md")).read()
    pinned_in_readme = dict(re.findall(r"([A-Za-z0-9_.-]+)==([A-Za-z0-9_.+-]+)", readme))
    check(pinned_in_readme == hifc.VENDOR, "vendor/README.md: те же версии (%r)" % (pinned_in_readme,))
    notices = open(os.path.join(ROOT, "THIRD_PARTY_NOTICES.md")).read()
    missing = [n for n, v in hifc.VENDOR.items() if v not in notices]
    check(not missing, "THIRD_PARTY_NOTICES.md упоминает версии всех модулей (нет: %r)" % missing)

    print("2. Имена типов нод — только через константы")
    bad = []
    for f in glob.glob(os.path.join(ROOT, "**", "*.py"), recursive=True):
        rel = os.path.relpath(f, ROOT)
        if rel.startswith("tests/out"):
            continue
        # запрещено только полное имя с номером версии; «hifc::ifc_import::» + HDA_VERSION — это и есть константа
        if re.search(r"hifc::ifc_(import|export)::\d", open(f).read()):
            bad.append(rel)
    check(not bad, "строковых имён типов нет (найдены в %r)" % bad)
    check(hifc.IMPORT_TYPE.endswith("::" + hifc.HDA_VERSION) and hifc.EXPORT_TYPE.endswith("::" + hifc.HDA_VERSION),
          "IMPORT_TYPE/EXPORT_TYPE собраны из HDA_VERSION (%s, %s)" % (hifc.IMPORT_TYPE, hifc.EXPORT_TYPE))

    print("3. Документация")
    banner = sorted(glob.glob(os.path.join(ROOT, "docs", "HIFC.*")))
    check(bool(banner), "баннер лежит в docs/ (%r)" % [os.path.basename(b) for b in banner])
    for name in ("README.md", "README.ru.md"):
        head = open(os.path.join(ROOT, name)).read().split("\n")[:4]
        check(any("docs/HIFC." in ln for ln in head), "%s: баннер сразу после заголовка" % name)
    check(os.path.isfile(os.path.join(ROOT, "deploy.py")), "deploy.py на месте")

    print("4. Справка двуязычная в одном тексте")
    from hifc import help_text
    for name, txt in (("import", help_text.HELP_IMPORT), ("export", help_text.HELP_EXPORT)):
        check("== Справка по-русски ==" in txt and "@parameters" in txt, "%s: английский текст + русский раздел" % name)

    print("\n%s (%d failures)" % ("PASSED" if not FAILS else "FAILED", len(FAILS)))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
