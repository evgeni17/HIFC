# SPDX-FileCopyrightText: 2026 EOK
# SPDX-License-Identifier: Apache-2.0
"""HIFC — импорт/экспорт IFC для Houdini на базе IfcOpenShell.

Пакет подключается через packages/HIFC.json (переменная $HIFC указывает на корень плагина).
Зависимость ifcopenshell лежит внутри плагина: $HIFC/vendor/<py-версия>-<платформа>/.
"""
import os
import platform
import sys

__version__ = "0.6.0.dev1"

# версия ассетов: сейчас hifc::*::1.0 (переход на правило «релиз 0.N -> ассеты ::N.0» — отдельным заходом)
HDA_VERSION = "1.0"
FROZEN = False
IMPORT_TYPE = "hifc::ifc_import::" + HDA_VERSION
EXPORT_TYPE = "hifc::ifc_export::" + HDA_VERSION

# закреплённые версии сторонних модулей в vendor/ и проверенное окружение.
# Единственное место в коде: установщик ставит ровно это, нода сверяет установленное с этим.
# numpy не ставим — берём из Houdini.
VENDOR = {
    "ifcopenshell": "0.8.5",
    "shapely": "2.1.2",
    "isodate": "0.7.2",
    "python-dateutil": "2.9.0.post0",
    "six": "1.17.0",
    "lark": "1.3.1",
    "typing-extensions": "4.16.0",
}
IFCOPENSHELL_TESTED = VENDOR["ifcopenshell"]
HOUDINI_TESTED = "22.0.429"
PYTHON_TESTED = "3.13"

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
