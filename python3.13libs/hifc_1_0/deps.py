# SPDX-FileCopyrightText: 2026 EOK
# SPDX-License-Identifier: Apache-2.0
"""Установка ifcopenshell внутрь плагина: $HIFC/vendor/<py>-<os>-<arch>/.

Используется, если в поставке нет готовой vendor-папки под эту платформу
(например, на Windows-машине или при новой версии Python в Houdini).
"""
import glob
import os
import subprocess
import sys

from . import ensure_vendor_path, vendor_dir, has_ifcopenshell, VENDOR


def houdini_python():
    """Путь к интерпретатору Python, встроенному в Houdini."""
    hfs = os.environ.get("HFS", "")
    ver = "%d.%d" % sys.version_info[:2]
    cands = [
        os.path.join(hfs, "Frameworks", "Python.framework", "Versions", ver, "bin", "python" + ver),   # macOS
        os.path.join(hfs, "Frameworks", "Python.framework", "Versions", "Current", "bin", "python3"),
        os.path.join(hfs, "python%s%s" % sys.version_info[:2], "python.exe"),                          # Windows
        os.path.join(hfs, "python", "bin", "python" + ver),                                              # Linux
        os.path.join(hfs, "python", "bin", "python3"),
    ]
    cands += glob.glob(os.path.join(hfs, "Frameworks", "Python.framework", "Versions", "*", "bin", "python3*"))
    for c in cands:
        if os.path.isfile(c):
            return c
    return None


def install(latest=False, log=print):
    """Ставит в vendor/ ровно закреплённые версии (VENDOR). latest=True — только по явной просьбе пользователя."""
    target = vendor_dir()
    os.makedirs(target, exist_ok=True)
    py = houdini_python()
    if not py:
        raise RuntimeError("Houdini Python not found (HFS=%s)" % os.environ.get("HFS"))
    # pip может отсутствовать во встроенном Python
    subprocess.call([py, "-m", "ensurepip", "--user"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    # --no-deps: состав и версии задаёт VENDOR, иначе pip притянет что угодно свежее
    pkgs = list(VENDOR) if latest else ["%s==%s" % kv for kv in VENDOR.items()]
    cmd = [py, "-m", "pip", "install", "--target", target, "--no-warn-script-location", "--no-deps", "--upgrade"] + pkgs
    log("[HIFC] " + " ".join(cmd))
    r = subprocess.run(cmd, capture_output=True, text=True)
    log(r.stdout[-3000:])
    if r.returncode != 0:
        raise RuntimeError(r.stderr[-3000:])
    # numpy берём из Houdini — свою копию убираем, чтобы не конфликтовала
    for p in glob.glob(os.path.join(target, "numpy*")):
        import shutil
        shutil.rmtree(p, ignore_errors=True)
    ensure_vendor_path()
    return target


def installed_versions():
    """Что реально лежит в vendor/: {модуль: версия или ""} по *.dist-info."""
    out = {}
    for name in VENDOR:
        stem = name.replace("-", "_")
        out[name] = ""
        for d in sorted(glob.glob(os.path.join(vendor_dir(), stem + "-*.dist-info"))):
            # имя папки: <модуль>-<версия>.dist-info
            out[name] = os.path.basename(d)[len(stem) + 1:-len(".dist-info")]
            break
    return out


def version_mismatches():
    """Список строк «модуль: закреплено X, установлено Y» — для предупреждения ноды и About."""
    found = installed_versions()
    bad = []
    for name, pinned in VENDOR.items():
        got = found.get(name) or ""
        if got and got != pinned:
            bad.append("%s %s (pinned %s)" % (name, got, pinned))
    return bad


def status():
    ok = has_ifcopenshell()
    ver = ""
    if ok:
        import ifcopenshell
        ver = ifcopenshell.version
    return {"ifcopenshell": ok, "version": ver, "vendor": vendor_dir(), "python": sys.version.split()[0],
            "installed": installed_versions(), "mismatches": version_mismatches()}
