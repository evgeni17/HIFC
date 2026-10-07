# SPDX-FileCopyrightText: 2026 EOK
# SPDX-License-Identifier: Apache-2.0
"""Проверки deploy.py на временных папках (без Houdini).

    python3 tests/test_deploy.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FAILS = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


def fake_source(d):
    """Минимальная копия раскладки плагина: deploy.py читает версию из python3.13libs/hifc/__init__.py."""
    os.makedirs(os.path.join(d, "python3.13libs", "hifc"))
    open(os.path.join(d, "python3.13libs", "hifc", "__init__.py"), "w").write(
        '__version__ = "9.9.9"\nHDA_VERSION = "1.0"\n')
    os.makedirs(os.path.join(d, "otls"))
    open(os.path.join(d, "otls", "a.hda"), "w").write("a")
    open(os.path.join(d, "otls", "b.hda"), "w").write("b")
    shutil.copy2(os.path.join(ROOT, "deploy.py"), os.path.join(d, "deploy.py"))


def run(src, target, *args):
    r = subprocess.run([sys.executable, os.path.join(src, "deploy.py"), target] + list(args),
                       capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def install_json(target):
    return json.load(open(os.path.join(target, "INSTALL.json")))


def main():
    base = tempfile.mkdtemp(prefix="hifc_deploy_")
    src, dst = os.path.join(base, "dev"), os.path.join(base, "install")
    os.makedirs(src)
    fake_source(src)

    print("1. Первая установка")
    rc, out = run(src, dst)
    check(rc == 0 and os.path.isfile(os.path.join(dst, "otls", "a.hda")), "файлы скопированы (rc=%d)" % rc)
    check("deploy.py" not in install_json(dst)["files"], "сам deploy.py не ставится")
    check(install_json(dst)["__version__"] == "9.9.9", "версия записана в INSTALL.json")

    print("2. Повторная установка без изменений")
    rc, out = run(src, dst)
    check("copied 0" in out, "ничего не копируется второй раз: %s" % out.strip().splitlines()[-1])

    print("3. Файл исчез из разработки: становится устаревшим и не забывается")
    os.remove(os.path.join(src, "otls", "b.hda"))
    rc, out = run(src, dst)                       # без --clean
    check(os.path.isfile(os.path.join(dst, "otls", "b.hda")), "без --clean файл остаётся на месте")
    check(install_json(dst).get("pending_removal") == ["otls/b.hda"],
          "устаревший файл записан в pending_removal: %r" % install_json(dst).get("pending_removal"))
    rc, out = run(src, dst)                       # ещё раз без --clean: не должен потеряться
    check(install_json(dst).get("pending_removal") == ["otls/b.hda"],
          "и после второго запуска он всё ещё помнится: %r" % install_json(dst).get("pending_removal"))
    rc, out = run(src, dst, "--clean")
    check(not os.path.exists(os.path.join(dst, "otls", "b.hda")), "--clean его удаляет")
    check(install_json(dst).get("pending_removal") == [], "после удаления список пуст")

    print("4. Чужие файлы в установке не трогаем")
    open(os.path.join(dst, "mine.txt"), "w").write("x")
    rc, out = run(src, dst, "--clean")
    check(os.path.isfile(os.path.join(dst, "mine.txt")), "файл, который ставил не deploy.py, остался")

    print("5. --dry-run ничего не меняет")
    open(os.path.join(src, "otls", "c.hda"), "w").write("c")
    rc, out = run(src, dst, "--dry-run")
    check(not os.path.exists(os.path.join(dst, "otls", "c.hda")) and "dry run" in out, "--dry-run только показывает")

    shutil.rmtree(base, ignore_errors=True)
    print("\n%s (%d failures)" % ("PASSED" if not FAILS else "FAILED", len(FAILS)))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
