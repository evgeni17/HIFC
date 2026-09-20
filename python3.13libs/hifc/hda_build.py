# SPDX-FileCopyrightText: 2026 EOK
# SPDX-License-Identifier: Apache-2.0
"""Сборка HDA плагина (hifc::ifc_import, hifc::ifc_export) в $HIFC/otls.

Запуск: меню HIFC > Rebuild HDAs, либо в Python Shell:
    import hifc.hda_build as b; b.build_all()
HDA тонкие: вся логика в python-модуле hifc, поэтому пересборка нужна только при изменении интерфейса.
"""
import os

import hou

from . import ROOT, __version__

OTLS = os.path.join(ROOT, "otls")

IMPORT_TYPE = "hifc::ifc_import::1.0"
EXPORT_TYPE = "hifc::ifc_export::1.0"

IMPORT_CODE = """# HIFC: чтение IFC (логика в модуле hifc.sop_import)
import hifc.sop_import as m
m.cook(hou.pwd())
"""


def _menu(name, label, items, default=0, **kw):
    return hou.MenuParmTemplate(name, label, [i[0] for i in items], [i[1] for i in items], default_value=default, **kw)


def _import_ptg():
    g = hou.ParmTemplateGroup()
    g.append(hou.StringParmTemplate("file", "IFC File", 1, string_type=hou.stringParmType.FileReference,
                                    file_type=hou.fileType.Any, tags={"filechooser_pattern": "*.ifc"}))
    g.append(hou.ButtonParmTemplate("reload", "Reload", script_callback="import hifc.sop_import as m; m.clear_cache(kwargs)",
                                    script_callback_language=hou.scriptLanguage.Python, join_with_next=True))
    g.append(hou.ButtonParmTemplate("info", "File Info", script_callback="import hifc.sop_import as m; m.info_text(kwargs)",
                                    script_callback_language=hou.scriptLanguage.Python))
    g.append(_menu("output", "Output", [("packed", "Packed Primitive per Element"), ("polys", "Polygons"),
                                        ("auto", "Auto (instance repeated geometry)")], default=2))
    g.append(hou.IntParmTemplate("mincopies", "Instance From N Copies", 1, default_value=(2,), min=2, max=50,
                                 help="How many identical elements (same IFC geometry) are needed to store the "
                                      "geometry once and place copies with the IFC transform.",
                                 conditionals={hou.parmCondType.HideWhen: "{ output == 1 }"}))
    g.append(_menu("pathmode", "Path", [("elements", "From First Assembly (round-trip)"), ("full", "Full (Project/Site/...)")]))
    f = hou.FolderParmTemplate("filter", "Filter", folder_type=hou.folderType.Simple)
    f.addParmTemplate(hou.StringParmTemplate("include", "Include Classes", 1, default_value=("",),
                                             help="Space separated, e.g. IfcWall IfcSlab. Empty = all."))
    f.addParmTemplate(hou.StringParmTemplate("exclude", "Exclude Classes", 1,
                                             default_value=("IfcOpeningElement IfcSpace IfcVirtualElement",)))
    g.append(f)
    f = hou.FolderParmTemplate("conv", "Conversion", folder_type=hou.folderType.Simple)
    f.addParmTemplate(hou.ToggleParmTemplate("yup", "Z-Up to Y-Up", default_value=True))
    f.addParmTemplate(hou.FloatParmTemplate("scale", "Scale (units per meter)", 1, default_value=(1.0,), min=0.0001, max=1000))
    f.addParmTemplate(hou.ToggleParmTemplate("color", "Colors from IFC Styles", default_value=True))
    f.addParmTemplate(hou.ToggleParmTemplate("psets", "Read Property Sets", default_value=True))
    f.addParmTemplate(hou.StringParmTemplate("psetfilter", "Property Sets", 1, default_value=("*",),
                                             help="Globs of property/quantity set names to read, e.g. Pset_* Qto_*. "
                                                  "Fewer sets = faster import.",
                                             conditionals={hou.parmCondType.DisableWhen: "{ psets == 0 }"}))
    f.addParmTemplate(hou.ToggleParmTemplate("flatten", "Flatten Psets to Attributes", default_value=False,
                                             conditionals={hou.parmCondType.DisableWhen: "{ psets == 0 }"}))
    f.addParmTemplate(hou.IntParmTemplate("threads", "Threads (0 = auto)", 1, default_value=(0,), min=0, max=64))
    f.addParmTemplate(hou.ToggleParmTemplate("diskcache", "Disk Cache", default_value=True,
                                             help="Keep parsed elements in $HOUDINI_TEMP_DIR/hifc_cache: "
                                                  "re-opening the same unchanged file is almost instant."))
    f.addParmTemplate(hou.ButtonParmTemplate("cleardisk", "Clear Disk Cache",
                                             script_callback="import hifc.sop_import as m; m.clear_disk_cache(kwargs)",
                                             script_callback_language=hou.scriptLanguage.Python))
    g.append(f)
    return g


def _export_ptg():
    g = hou.ParmTemplateGroup()
    g.append(hou.StringParmTemplate("file", "Output IFC", 1, default_value=("$HIP/ifc/$HIPNAME.ifc",),
                                    string_type=hou.stringParmType.FileReference, file_type=hou.fileType.Any,
                                    tags={"filechooser_pattern": "*.ifc", "filechooser_mode": "write"}))
    g.append(hou.ButtonParmTemplate("export", "Export IFC", script_callback="import hifc.sop_export as m; m.export_node(kwargs)",
                                    script_callback_language=hou.scriptLanguage.Python, join_with_next=True))
    g.append(hou.ButtonParmTemplate("check", "Check Attributes", script_callback="import hifc.sop_export as m; m.check_node(kwargs)",
                                    script_callback_language=hou.scriptLanguage.Python, join_with_next=True))
    g.append(hou.ButtonParmTemplate("reveal", "Reveal File", script_callback="import hifc.sop_export as m; m.open_in_bonsai_hint(kwargs)",
                                    script_callback_language=hou.scriptLanguage.Python))
    g.append(_menu("schema", "Schema", [("IFC4", "IFC4"), ("IFC4X3", "IFC4X3"), ("IFC2X3", "IFC2X3")]))

    f = hou.FolderParmTemplate("project_f", "Project", folder_type=hou.folderType.Tabs)
    f.addParmTemplate(hou.StringParmTemplate("project", "Project", 1, default_value=("$HIPNAME",)))
    f.addParmTemplate(hou.StringParmTemplate("site", "Site", 1, default_value=("Site",)))
    f.addParmTemplate(hou.StringParmTemplate("building", "Building", 1, default_value=("Building",)))
    f.addParmTemplate(hou.StringParmTemplate("storey", "Default Storey", 1, default_value=("Level 0",)))
    f.addParmTemplate(_menu("lengthunit", "Length Unit", [("mm", "Millimeter"), ("cm", "Centimeter"), ("m", "Meter")]))
    f.addParmTemplate(hou.FloatParmTemplate("scale", "Scene Unit (meters)", 1, default_value=(1.0,), min=0.0001, max=1000))
    f.addParmTemplate(hou.ToggleParmTemplate("yup", "Y-Up to Z-Up", default_value=True))
    f.addParmTemplate(_menu("origin", "Element Origin", [("bbox_bottom", "BBox Bottom Center"), ("bbox_center", "BBox Center"), ("world", "World Origin")]))
    f.addParmTemplate(hou.StringParmTemplate("guidseed", "GUID Seed", 1, default_value=("",),
                                             help="Changes all generated GlobalIds. Keep constant for stable re-exports."))
    g.append(f)

    f = hou.FolderParmTemplate("struct_f", "Structure", folder_type=hou.folderType.Tabs)
    f.addParmTemplate(hou.StringParmTemplate("pathattrib", "Path Attribute", 1, default_value=("path",)))
    f.addParmTemplate(hou.IntParmTemplate("skipsegments", "Skip Leading Segments", 1, default_value=(0,), min=0, max=10))
    f.addParmTemplate(hou.StringParmTemplate("assemblyclass", "Assembly Class", 1, default_value=("IfcElementAssembly",)))
    f.addParmTemplate(hou.StringParmTemplate("assemblypredef", "Assembly Type", 1, default_value=("NOTDEFINED",)))
    f.addParmTemplate(hou.StringParmTemplate("defaultclass", "Default Class", 1, default_value=("IfcBuildingElementProxy",)))
    rules = hou.FolderParmTemplate("rules", "Class Rules", folder_type=hou.folderType.MultiparmBlock, default_value=0)
    rules.addParmTemplate(hou.StringParmTemplate("rule_pattern#", "Match", 1, default_value=("*",),
                                                 help="Glob on the leaf name or full path, e.g. Bracket_*"))
    rules.addParmTemplate(hou.StringParmTemplate("rule_class#", "IFC Class", 1, default_value=("IfcBuildingElementProxy",)))
    rules.addParmTemplate(hou.StringParmTemplate("rule_predefined#", "Predefined Type", 1, default_value=("",)))
    f.addParmTemplate(rules)
    g.append(f)

    f = hou.FolderParmTemplate("attr_f", "Attributes", folder_type=hou.folderType.Tabs)
    for name, label, dflt in (("classattrib", "Class Attribute", "ifc_class"),
                              ("predefattrib", "Predefined Type Attribute", "ifc_predefined"),
                              ("nameattrib", "Name Attribute", "ifc_name"),
                              ("guidattrib", "GUID Attribute", "ifc_guid"),
                              ("storeyattrib", "Storey Attribute", "ifc_storey"),
                              ("materialattrib", "Material Attribute", "ifc_material"),
                              ("styleattrib", "Style Name Attribute", "ifc_style"),
                              ("tagattrib", "Tag Attribute", "ifc_tag"),
                              ("objtypeattrib", "Object Type Attribute", "ifc_object_type"),
                              ("descattrib", "Description Attribute", "ifc_description"),
                              ("materialsattrib", "Materials Array Attribute", "ifc_materials"),
                              ("dictattrib", "Psets Dict Attribute", "ifc_psets"),
                              ("measuresattrib", "Measures Dict Attribute", "ifc_measures")):
        f.addParmTemplate(hou.StringParmTemplate(name, label, 1, default_value=(dflt,)))
    f.addParmTemplate(hou.SeparatorParmTemplate("sep1"))
    f.addParmTemplate(hou.StringParmTemplate("psetexport", "Property Sets to Export", 1, default_value=("*",),
                                             help="Globs of set names from the psets dictionary; ^glob excludes, "
                                                  "e.g. * ^ArchiCADProperties"))
    f.addParmTemplate(hou.StringParmTemplate("psetname", "Pset Name", 1, default_value=("HoudiniAttributes",)))
    f.addParmTemplate(hou.StringParmTemplate("psetattribs", "Attributes to Pset", 1, default_value=("",),
                                             help="Prim attribute globs, e.g. len_* N_*"))
    f.addParmTemplate(hou.ToggleParmTemplate("pathprop", "Add Houdini_Path Property", default_value=True))
    f.addParmTemplate(hou.ToggleParmTemplate("color", "Colors from Cd", default_value=True))
    f.addParmTemplate(_menu("packedcolor", "Packed Colors", [
        ("faces", "Per Face (inside packed)"), ("override", "Packed Primitive Cd Overrides")],
        help="Per Face keeps the colours stored inside packed primitives (import result). "
             "Override uses Cd/Alpha set on the packed primitive for the whole element.",
        conditionals={hou.parmCondType.DisableWhen: "{ color == 0 }"}))
    g.append(f)

    f = hou.FolderParmTemplate("out_f", "Report", folder_type=hou.folderType.Tabs)
    f.addParmTemplate(hou.ToggleParmTemplate("validate", "Validate After Export", default_value=False))
    f.addParmTemplate(hou.StringParmTemplate("report", "Report", 1, default_value=("",),
                                             tags={"editor": "1", "editorlines": "6-20"}))
    g.append(f)
    return g


def _parent_geo():
    obj = hou.node("/obj")
    tmp = obj.node("__hifc_build")
    if tmp is not None:
        tmp.destroy()
    return obj.createNode("geo", "__hifc_build")


def _finish(node, type_name, label, hda_path, ptg, min_in, max_in, icon, help_text):
    for existing in hou.hda.definitionsInFile(hda_path) if os.path.exists(hda_path) else []:
        if existing.nodeTypeName() == type_name:
            existing.destroy()
    node.setParmTemplateGroup(ptg)
    hda = node.createDigitalAsset(name=type_name, hda_file_name=hda_path, description=label,
                                  min_num_inputs=min_in, max_num_inputs=max_in, ignore_external_references=True)
    d = hda.type().definition()
    # updateFromNode не синхронизирует интерфейс — пишем его в определение явно
    d.setParmTemplateGroup(ptg)
    d.setDescription(label)
    d.setIcon(icon)
    d.setVersion(__version__)
    d.setExtraFileOption("UnlockOnCreate", False) if hasattr(d, "setExtraFileOption") else None
    tools = _tool_xml(type_name, label, icon)
    d.addSection("Tools.shelf", tools)
    d.addSection("Help", help_text.encode("utf-8").decode("utf-8"))
    d.save(hda_path, hda)
    return hda


def _tool_xml(type_name, label, icon):
    return """<?xml version="1.0" encoding="UTF-8"?>
<shelfDocument>
  <tool name="$HDA_DEFAULT_TOOL" label="$HDA_LABEL" icon="$HDA_ICON">
    <toolMenuContext name="viewer"><contextNetType>SOP</contextNetType></toolMenuContext>
    <toolMenuContext name="network"><contextOpType>$HDA_TABLE_AND_NAME</contextOpType></toolMenuContext>
    <toolSubmenu>HIFC</toolSubmenu>
    <script scriptType="python"><![CDATA[import soptoolutils
soptoolutils.genericTool(kwargs, '$HDA_NAME')]]></script>
  </tool>
</shelfDocument>
"""


def build_import(otls=None):
    geo = _parent_geo()
    sub = geo.createNode("subnet", "ifc_import")
    py = sub.createNode("python", "IFC_READ")
    py.parm("python").set(IMPORT_CODE)
    out = sub.createNode("output", "OUT")
    out.setInput(0, py)
    py.setDisplayFlag(True)
    help_text = HELP_IMPORT
    path = os.path.join(otls or OTLS, "hifc_ifc_import.hda")
    hda = _finish(sub, IMPORT_TYPE, "HIFC IFC Import", path, _import_ptg(), 0, 0, "SOP_file", help_text)
    return path


def build_export(otls=None):
    geo = _parent_geo()
    sub = geo.createNode("subnet", "ifc_export")
    unpack = sub.createNode("unpack", "UNPACK")
    unpack.setInput(0, sub.indirectInputs()[0])
    tp = unpack.parm("transfer_attributes")
    if tp is not None:
        # цвет/прозрачность с packed-примитива не должны затирать цвета граней внутри (режим Per Face)
        tp.setExpression('ifs(ch("../packedcolor"), "*", "* ^Cd ^Alpha ^ifc_style")', hou.exprLanguage.Hscript)
    # вершинные атрибуты для быстрого чтения полигонов при экспорте (см. sop_export.PREP_VEX)
    from .sop_export import PREP_VEX
    prep = sub.createNode("attribwrangle", "PREP")
    prep.setInput(0, unpack)
    prep.parm("class").set(3)  # Vertices
    prep.parm("snippet").set(PREP_VEX)
    out = sub.createNode("output", "OUT")
    out.setInput(0, sub.indirectInputs()[0])
    path = os.path.join(otls or OTLS, "hifc_ifc_export.hda")
    _finish(sub, EXPORT_TYPE, "HIFC IFC Export", path, _export_ptg(), 1, 1, "SOP_rop_geometry", HELP_EXPORT)
    return path


def build_all(kwargs=None, otls=None, install=True):
    """otls — папка назначения (по умолчанию $HIFC/otls); install=False — не подгружать в сессию."""
    otls = otls or OTLS
    if not os.path.isdir(otls):
        os.makedirs(otls)
    paths = [build_import(otls), build_export(otls)]
    tmp = hou.node("/obj/__hifc_build")
    if tmp is not None:
        tmp.destroy()
    for p in paths:
        if install:
            hou.hda.installFile(p)
            hou.hda.reloadFile(p)
        else:
            hou.hda.uninstallFile(p)
    msg = "HIFC HDAs built:\n" + "\n".join(paths)
    print("[HIFC] " + msg)
    if hou.isUIAvailable() and kwargs is not None:
        hou.ui.displayMessage(msg, title="HIFC")
    return paths


from .help_text import HELP_EXPORT, HELP_IMPORT  # noqa: E402
