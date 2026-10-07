# SPDX-FileCopyrightText: 2026 EOK
# SPDX-License-Identifier: Apache-2.0
"""Защиты freeze.py на временной копии репозитория (без Houdini).

    python3 tests/test_freeze.py

Проверяется, что процедуру выпуска нельзя обойти: заморозить дважды, запечатать дважды,
занять разработкой уже выпущенный или не больший номер.
"""
import importlib.util
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FAILS = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


def fake_repo(d):
    """Маленький репозиторий: разработка ::6.0 и уже замороженная ::1.0."""
    libs = os.path.join(d, "python3.13libs")
    os.makedirs(os.path.join(libs, "hifc"))
    open(os.path.join(libs, "hifc", "__init__.py"), "w").write(
        '__version__ = "0.6.0.dev3"\nHDA_VERSION = "6.0"\nFROZEN = False\n')
    open(os.path.join(libs, "hifc", "sop_import.py"), "w").write("import hifc.ifc_read\n")
    os.makedirs(os.path.join(libs, "hifc_1_0"))
    open(os.path.join(libs, "hifc_1_0", "__init__.py"), "w").write(
        '__version__ = "0.5.1"\nHDA_VERSION = "1.0"\nFROZEN = True\n')
    open(os.path.join(libs, "hifc_1_0", "FROZEN.sha256"), "w").write("deadbeef  hifc_1_0/__init__.py\n")
    os.makedirs(os.path.join(d, "otls"))
    for f in ("hifc_ifc_import_1.0.hda", "hifc_ifc_export_1.0.hda"):
        open(os.path.join(d, "otls", f), "w").write("x")
    json.dump({"assets": {"1.0": {"status": "frozen", "package": "hifc_1_0", "vendor": {"ifcopenshell": "0.8.5"},
                                  "houdini": "22.0.429", "python": "3.13", "sealed": "2026-10-07",
                                  "assets": ["hifc_ifc_import_1.0.hda"]},
                          "6.0": {"status": "development", "package": "hifc", "plugin": "0.6.0.dev3",
                                  "vendor": {"ifcopenshell": "0.8.5"}, "houdini": "22.0.429", "python": "3.13"}}},
              open(os.path.join(d, "VERSIONS.json"), "w"), indent=2)
    shutil.copy2(os.path.join(ROOT, "freeze.py"), os.path.join(d, "freeze.py"))


def load_freeze(d):
    spec = importlib.util.spec_from_file_location("freeze_tmp_%d" % id(d), os.path.join(d, "freeze.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m.HERE = d                      # скрипт работает со своей папкой; в тесте подменяем на временную
    m.LIBS = os.path.join(d, "python3.13libs")
    return m


def const(path, name):
    for line in open(path):
        if line.startswith(name):
            return line.split("=", 1)[1].strip().strip('"')
    return ""


def main():
    d = tempfile.mkdtemp(prefix="hifc_freeze_")
    fake_repo(d)
    f = load_freeze(d)
    init = os.path.join(d, "python3.13libs", "hifc", "__init__.py")

    print("1. Повторная заморозка и повторное запечатывание запрещены")
    check(f.seal("1.0") == 1, "запечатать уже запечатанную ::1.0 нельзя")
    check(f.freeze("1.0") == 1, "заморозить ::1.0 второй раз нельзя")
    check(const(os.path.join(d, "python3.13libs", "hifc_1_0", "__init__.py"), "__version__") == "0.5.1",
          "замороженная копия не тронута")

    print("2. Разработка не может занять выпущенный или не больший номер")
    for bad in ("1.0", "6.0", "5.0"):
        check(f.next_version(bad) == 1, "::%s как версия разработки отклонена" % bad)
    check(const(init, "HDA_VERSION") == "6.0" and const(init, "__version__") == "0.6.0.dev3",
          "после отказов версия разработки не изменилась")

    print("3. Нормальный ход: заморозить ::6.0, запечатать, перейти на ::7.0")
    check(f.freeze("6.0") == 0 and os.path.isdir(os.path.join(d, "python3.13libs", "hifc_6_0")), "::6.0 заморожена")
    frozen_init = os.path.join(d, "python3.13libs", "hifc_6_0", "__init__.py")
    check(const(frozen_init, "FROZEN") == "True" and const(frozen_init, "HDA_VERSION") == "6.0",
          "замороженная копия помечена и знает свою версию")
    check(f.seal("6.0") == 1, "запечатать без собранных HDA нельзя")
    for name in ("hifc_ifc_import_6.0.hda", "hifc_ifc_export_6.0.hda"):
        open(os.path.join(d, "otls", name), "w").write("y")
    check(f.seal("6.0") == 0 and os.path.isfile(os.path.join(d, "python3.13libs", "hifc_6_0", "FROZEN.sha256")),
          "после сборки HDA запечатывание проходит")
    check(f.seal("6.0") == 1, "и повторно уже не проходит")
    check(f.next_version("7.0") == 0, "разработка переходит на ::7.0")
    check(const(init, "HDA_VERSION") == "7.0" and const(init, "__version__") == "0.7.0.dev1",
          "версия плагина поднята скриптом: %s / %s" % (const(init, "HDA_VERSION"), const(init, "__version__")))
    recs = json.load(open(os.path.join(d, "VERSIONS.json")))["assets"]
    check(recs["6.0"]["status"] == "frozen" and recs["7.0"]["status"] == "development",
          "в VERSIONS.json ::6.0 заморожена, ::7.0 — разработка")

    shutil.rmtree(d, ignore_errors=True)
    print("\n%s (%d failures)" % ("PASSED" if not FAILS else "FAILED", len(FAILS)))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
