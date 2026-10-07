# SPDX-FileCopyrightText: 2026 EOK
# SPDX-License-Identifier: Apache-2.0
"""Команды для шелфа и главного меню HIFC."""
import os

import hou

from . import __version__, ROOT


def _sop_parent():
    """Текущая SOP-сеть в Network Editor или новый geo-узел."""
    try:
        pane = hou.ui.paneTabOfType(hou.paneTabType.NetworkEditor)
        net = pane.pwd() if pane else None
    except Exception:
        net = None
    if net is not None and net.childTypeCategory() == hou.sopNodeTypeCategory():
        return net
    return None


def import_ifc(kwargs=None):
    """Выбрать IFC-файл и создать для него узел HIFC IFC Import."""
    path = hou.ui.selectFile(title="HIFC: Import IFC", pattern="*.ifc", chooser_mode=hou.fileChooserMode.Read)
    if not path:
        return None
    parent = _sop_parent()
    if parent is None:
        name = os.path.splitext(os.path.basename(hou.text.expandString(path)))[0]
        parent = hou.node("/obj").createNode("geo", hou.text.variableName(name) if hasattr(hou.text, "variableName") else "ifc")
    node = parent.createNode("hifc::ifc_import", "ifc_import")
    node.parm("file").set(path)
    node.setDisplayFlag(True)
    node.setRenderFlag(True)
    node.setSelected(True, clear_all_selected=True)
    return node


def export_selected(kwargs=None):
    """Повесить HIFC IFC Export на выбранный SOP."""
    sel = [n for n in hou.selectedNodes() if n.type().category() == hou.sopNodeTypeCategory()]
    if not sel:
        hou.ui.displayMessage("Select a SOP node to export.", title="HIFC")
        return None
    src = sel[0]
    node = src.parent().createNode("hifc::ifc_export", "ifc_export")
    node.setInput(0, src)
    node.setSelected(True, clear_all_selected=True)
    return node


def install_deps(kwargs=None):
    from . import deps
    try:
        with hou.InterruptableOperation("HIFC: installing ifcopenshell", open_interrupt_dialog=True):
            target = deps.install()
        hou.ui.displayMessage("ifcopenshell installed to:\n%s\n\nRestart Houdini if import still fails." % target, title="HIFC")
    except Exception as ex:
        hou.ui.displayMessage("Install failed:\n%s" % ex, title="HIFC", severity=hou.severityType.Error)


def rebuild_hdas(kwargs=None):
    from . import hda_build
    hda_build.build_all(kwargs or {})


def about(kwargs=None):
    from . import deps, HDA_VERSION, HOUDINI_TESTED, VENDOR
    st = deps.status()
    mods = "\n".join("  %-18s pinned %-12s installed %s" % (n, v, st["installed"].get(n) or "-")
                      for n, v in VENDOR.items())
    msg = ("HIFC %s — IFC import/export for Houdini\nAssets: ::%s\nRoot: %s\n\n"
           "ifcopenshell: %s %s\nvendor: %s\nPython: %s (tested Houdini %s)\n\nModules:\n%s%s"
           % (__version__, HDA_VERSION, ROOT, "OK" if st["ifcopenshell"] else "NOT FOUND", st["version"],
              st["vendor"], st["python"], HOUDINI_TESTED, mods,
              ("\n\nMismatch: " + ", ".join(st["mismatches"])) if st["mismatches"] else ""))
    hou.ui.displayMessage(msg, title="HIFC")


def attribute_template(kwargs=None):
    """Primitive Wrangle с шаблоном IFC-атрибутов после выбранной ноды."""
    from . import templates
    return templates.create_wrangle(kwargs)


def attribute_guide(kwargs=None):
    """Открыть справку HIFC IFC Export (правила атрибутов)."""
    from . import EXPORT_TYPE
    nt = hou.nodeType(hou.sopNodeTypeCategory(), EXPORT_TYPE)
    if nt is None:
        hou.ui.displayMessage("hifc::ifc_export not installed. Run HIFC > Rebuild HDAs.", title="HIFC")
        return
    hou.ui.displayNodeHelp(nt)
