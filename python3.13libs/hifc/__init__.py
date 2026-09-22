# SPDX-FileCopyrightText: 2026 EOK
# SPDX-License-Identifier: Apache-2.0
"""HIFC — импорт/экспорт IFC для Houdini на базе IfcOpenShell.

Пакет подключается через packages/HIFC.json (переменная $HIFC указывает на корень плагина).
Зависимость ifcopenshell лежит внутри плагина: $HIFC/vendor/<py-версия>-<платформа>/.
"""
import os
import platform
import sys

__version__ = "0.5.1"

# корень плагина: .../HIFC  (этот файл: .../HIFC/python3.13libs/hifc/__init__.py)
ROOT = os.environ.get("HIFC") or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def platform_tag():
    """Тег платформы для папки vendor, например 'py313-macos-arm64'."""
    py = "py%d%d" % sys.version_info[:2]
    sysname = {"darwin": "macos", "win32": "win", "linux": "linux"}.get(sys.platform, sys.platform)
    machine = platform.machine().lower()
    machine = {"x86_64": "x64", "amd64": "x64", "aarch64": "arm64"}.get(machine, machine)
    return "%s-%s-%s" % (py, sysname, machine)


def vendor_dir():
    return os.path.join(ROOT, "vendor", platform_tag())


def ensure_vendor_path():
    """Добавляет vendor-папку в sys.path (один раз)."""
    d = vendor_dir()
    if os.path.isdir(d) and d not in sys.path:
        sys.path.insert(0, d)
    return d


ensure_vendor_path()


def has_ifcopenshell():
    try:
        import ifcopenshell  # noqa: F401
        return True
    except Exception:
        return False
