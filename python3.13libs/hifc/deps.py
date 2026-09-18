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

from . import ensure_vendor_path, vendor_dir, has_ifcopenshell


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


def install(upgrade=False, log=print):
    target = vendor_dir()
    os.makedirs(target, exist_ok=True)
    py = houdini_python()
    if not py:
        raise RuntimeError("Houdini Python not found (HFS=%s)" % os.environ.get("HFS"))
    # pip может отсутствовать во встроенном Python
    subprocess.call([py, "-m", "ensurepip", "--user"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    cmd = [py, "-m", "pip", "install", "--target", target, "--no-warn-script-location", "ifcopenshell"]
    if upgrade:
        cmd.insert(4, "--upgrade")
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


def status():
    ok = has_ifcopenshell()
    ver = ""
    if ok:
        import ifcopenshell
        ver = ifcopenshell.version
    return {"ifcopenshell": ok, "version": ver, "vendor": vendor_dir(), "python": sys.version.split()[0]}
