# SPDX-FileCopyrightText: 2026 EOK
# SPDX-License-Identifier: Apache-2.0
"""Шаблоны VEX для подготовки атрибутов перед HIFC IFC Export."""

# Primitive Wrangle: полный шаблон со всеми атрибутами, которые понимает экспорт
PRIM_WRANGLE = r'''// ============================================================
// HIFC: подготовка атрибутов для IFC Export (Run Over: Primitives)
// Один IFC-элемент = одно уникальное значение s@path.
// Все примитивы с одинаковым path склеиваются в один элемент.
// ============================================================

// --- исходные данные (заменить на свои атрибуты) ---
int    sys_id   = prim(0, "sys_id", @primnum);      // номер системы / сборки
string category = prim(0, "category", @primnum);    // тип детали: Profile, Rod, Tube...
int    part_id  = prim(0, "part_id", @primnum);     // номер детали внутри системы

// --- 1. ИЕРАРХИЯ: /Система/Группа/Элемент ---
// промежуточные сегменты -> IfcElementAssembly, последний -> сам элемент
// имена: латиница, цифры, _ ; без "/" ; стабильные между пересчётами (от них зависит GUID)
string sys_name  = sprintf("Frame_%03d", sys_id);
string grp_name  = sprintf("%s_%s", sys_name, category);
string leaf_name = sprintf("%s_%04d", category, part_id);
s@path = sprintf("/%s/%s/%s", sys_name, grp_name, leaf_name);

// --- 2. КЛАСС IFC и PredefinedType ---
// (можно не задавать тут, а использовать Class Rules на ноде экспорта)
if (category == "Profile")      { s@ifc_class = "IfcMember";            s@ifc_predefined = "MEMBER"; }
else if (category == "Rod")     { s@ifc_class = "IfcDiscreteAccessory"; s@ifc_predefined = "NOTDEFINED"; }
else if (category == "Tube")    { s@ifc_class = "IfcLightFixture";      s@ifc_predefined = "NOTDEFINED"; }
else                            { s@ifc_class = "IfcBuildingElementProxy"; s@ifc_predefined = "NOTDEFINED"; }

// --- 3. ЭТАЖ (пространственный контейнер) ---
s@ifc_storey = "Level 01";

// --- 4. ИМЕНА И МАРКИРОВКА ---
s@ifc_name        = leaf_name;                      // IfcRoot.Name — видно в дереве BIM
s@ifc_tag         = sprintf("%d-%d", sys_id, part_id); // IfcElement.Tag — марка/позиция
s@ifc_object_type = category;                       // ObjectType — тип по вашей классификации
// s@ifc_description = "";

// --- 5. МАТЕРИАЛ и ЦВЕТ ---
s@ifc_material = (category == "Tube") ? "Polycarbonate" : "Aluminium";
// v@Cd = {0.2, 0.2, 0.2};   // цвет -> IfcSurfaceStyle
// f@Alpha = 1.0;           // прозрачность

// --- 6. СВОЙСТВА (Property Sets) ---
// длины/площади — в ЕДИНИЦАХ ПРОЕКТА IFC (по умолчанию мм), а не в единицах Houdini
float len_mm = prim(0, "length", @primnum) * 1000.0;
dict data;
data["Length_mm"] = len_mm;
data["SystemID"]  = sys_id;
dict psets;
psets["ACME_Data"] = data;                            // свой набор: НЕ начинать с Pset_
dict common;
common["IsExternal"]  = 0;
common["LoadBearing"] = 0;
psets["Pset_MemberCommon"] = common;                 // стандартный набор buildingSMART
dict qto;
qto["Length"] = len_mm;
psets["Qto_MemberBaseQuantities"] = qto;             // Qto_* -> IfcElementQuantity (только числа)
d@ifc_psets = psets;

// --- 7. GUID (необязательно) ---
// если не задан — генерируется стабильно из path + storey + GUID Seed
// s@ifc_guid = prim(0, "ifc_guid", @primnum);
'''


def create_wrangle(kwargs=None):
    """Создать Primitive Wrangle с шаблоном после выбранной SOP-ноды."""
    import hou
    sel = [n for n in hou.selectedNodes() if n.type().category() == hou.sopNodeTypeCategory()]
    if not sel:
        hou.ui.displayMessage("Select a SOP node first.", title="HIFC")
        return None
    src = sel[0]
    w = src.parent().createNode("attribwrangle", "ifc_attributes")
    w.setInput(0, src)
    w.parm("class").set(1)  # 1 = Primitives
    w.parm("snippet").set(PRIM_WRANGLE)
    w.setSelected(True, clear_all_selected=True)
    return w
