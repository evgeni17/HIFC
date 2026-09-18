# -*- coding: utf-8 -*-
# SPDX-FileCopyrightText: 2026 EOK
# SPDX-License-Identifier: Apache-2.0
"""Тексты справки HDA (Houdini wiki markup). Показываются по F1 / кнопке "?" на ноде."""

HELP_EXPORT_RU = u"""= HIFC IFC Export =

#type: node
#context: sop
#internal: hifc::ifc_export
#icon: SOP/rop_geometry

\"\"\"Записывает входную геометрию в IFC (IfcOpenShell, без Blender). Структуру BIM задают атрибуты примитивов.\"\"\"

Перед экспортом нажмите __Check Attributes__ — нода проверит атрибуты и напишет отчёт во вкладке Report, ничего не записывая на диск.
Готовый шаблон атрибутов: меню __HIFC > Create Attribute Template__ (Primitive Wrangle после выбранной ноды).

== Как устроена модель BIM ==

IFC — это не сцена, а дерево «кто в чём находится»:

{{{
IfcProject            <- параметр Project
 └ IfcSite            <- параметр Site
    └ IfcBuilding     <- параметр Building
       └ IfcBuildingStorey          <- s@ifc_storey
          └ IfcElementAssembly      <- промежуточные сегменты s@path
             └ IfcElementAssembly
                └ IfcMember / IfcLightFixture / ...   <- последний сегмент s@path
}}}

*Проект, участок и здание* задаются параметрами ноды (вкладка Project).
*Этаж* — атрибутом `s@ifc_storey`. *Всё, что ниже этажа,* — атрибутом `s@path`.

== Главное правило: один path = один физический элемент ==

Все примитивы с одинаковым значением `s@path` склеиваются в *один* IFC-элемент.

* Элемент — это то, что в реальности считают, заказывают и монтируют по отдельности: профиль, подвес, лампа, кронштейн, панель.
* Нельзя класть два физических предмета под один path — в спецификации они станут одной позицией.
* Нельзя делить один предмет на несколько path — он станет несколькими позициями.
* Нужны разные цвета внутри одного элемента? Задайте разный `Cd` на примитивах одного path — получится один элемент с несколькими стилями.

== s@path — иерархия ==

{{{
/Frame_001/Frame_001_Profile/Profile_0007
 │          │                 └ элемент (IfcMember)
 │          └ группа  -> IfcElementAssembly
 └ система            -> IfcElementAssembly
}}}

* Разделитель — `/`. Первый `/` необязателен.
* Каждый промежуточный сегмент — сборка (`Assembly Class` на вкладке Structure, по умолчанию IfcElementAssembly). Одинаковые префиксы — одна и та же сборка.
* Путь не может быть одновременно элементом и папкой: `/A/B` и `/A/B/C` — ошибка.
* Имена сегментов: латиница, цифры, `_`, `-`, `.`, пробел. Имя сегмента должно быть уникальным среди «соседей».
* *Имена должны быть стабильными.* Если GUID не задан, он вычисляется из path + storey: тот же путь — тот же GlobalId при каждом экспорте. Не используйте `@primnum` или случайные числа в path — иначе BIM-менеджер получит «новые» элементы при каждой выгрузке.
* Глубина 2–4 уровня — нормально. Не делайте сборку из одного элемента без необходимости.
* __Skip Leading Segments__ отрезает начало пути (например, служебный `/obj/geo1`).

== Класс элемента ==

Порядок определения класса:
# `s@ifc_class` на примитиве;
# первое совпавшее правило __Class Rules__ (маска по имени элемента или полному пути, например `Bracket_*`);
# __Default Class__ (IfcBuildingElementProxy).

`s@ifc_predefined` — уточнение класса (PredefinedType), значение из перечисления этого класса.
Неизвестное значение станет USERDEFINED, а текст уйдёт в ObjectType. Не знаете — пишите `NOTDEFINED`.

Частые классы:

`IfcMember` / `MEMBER`, `STRUT`, `BRACE`, `MULLION`:
    Профили, стержни, рейки, тяги.
`IfcBeam` / `BEAM`, `JOIST`, `LINTEL`:
    Балки, прогоны.
`IfcColumn` / `COLUMN`, `PILASTER`:
    Колонны, стойки.
`IfcPlate` / `SHEET`, `CURTAIN_PANEL`:
    Листы, панели.
`IfcSlab` / `FLOOR`, `ROOF`, `LANDING`:
    Плиты.
`IfcWall` / `STANDARD`, `PARTITIONING`:
    Стены, перегородки.
`IfcCovering` / `CEILING`, `CLADDING`, `FLOORING`:
    Отделка, подвесной потолок.
`IfcRailing` / `HANDRAIL`, `GUARDRAIL`:
    Ограждения.
`IfcDiscreteAccessory` / `BRACKET`, `SHOE`, `NOTDEFINED`:
    Подвесы, кронштейны, закладные.
`IfcFastener` / `WELD`, `GLUE`; `IfcMechanicalFastener` / `BOLT`, `ANCHORBOLT`:
    Крепёж.
`IfcLightFixture` / `POINTSOURCE`, `DIRECTIONSOURCE`, `NOTDEFINED`:
    Светильники, светящиеся трубки.
`IfcCableCarrierSegment` / `CABLETRAYSEGMENT`, `CONDUITSEGMENT`:
    Кабельные лотки, короба.
`IfcPipeSegment` / `RIGIDSEGMENT`:
    Трубы (инженерные системы, не декоративные).
`IfcFurniture` / `TABLE`, `CHAIR`, `SHELF`:
    Мебель.
`IfcAnnotation`:
    Метки, бирки без физического объёма.
`IfcBuildingElementProxy`:
    Всё, чему нет подходящего класса. Лучше честный Proxy, чем неверный класс.

Схемы: IFC4 — по умолчанию (Revit, Archicad, Bonsai, Navisworks). IFC4X3 — для инфраструктуры (IfcCourse, IfcTrackElement...). IFC2X3 — только для старого ПО, часть классов недоступна (IfcPipeSegment станет Proxy).

== Имена и маркировка ==

`s@ifc_name`:
    Name — подпись в дереве BIM. Если не задан — последний сегмент path.
`s@ifc_tag`:
    Tag — марка/позиция на чертеже (например `F-01.P-007`).
`s@ifc_object_type`:
    ObjectType — ваш тип/артикул (Profile_40x40, Tube_1500).
`s@ifc_description`:
    Description — свободный текст.

== Этаж ==

`s@ifc_storey` — имя этажа (`Level 01`, `+3.600`). Все элементы с одинаковым значением попадут в один IfcBuildingStorey.
Пусто — берётся __Default Storey__. Сборки строятся внутри этажа: одинаковый префикс path на разных этажах даст разные сборки.

== Материал и цвет ==

`s@ifc_material`:
    Имя материала (IfcMaterial). Одинаковые имена — один материал на весь проект. Пишите реальный материал: `Aluminium`, `Steel S235`, `Polycarbonate`.
`Cd` (prim или point), `f@Alpha`:
    Цвет и прозрачность -> IfcSurfaceStyle. Одинаковый цвет = один стиль.
`s@ifc_style`:
    Имя стиля (иначе генерируется `Color_RRGGBB`).

== Свойства (Property Sets) ==

Основной способ — словарь `d@ifc_psets` вида `{ИмяНабора: {Свойство: значение}}`:

{{{
#!vex
dict data;   data["Length_mm"] = 1500;  data["SystemID"] = 1;
dict common; common["IsExternal"] = 0;  common["LoadBearing"] = 0;
dict qto;    qto["Length"] = 1500;
dict ps;
ps["ACME_Data"]                 = data;    // свой набор
ps["Pset_MemberCommon"]        = common;  // стандартный набор buildingSMART
ps["Qto_MemberBaseQuantities"] = qto;     // количества
d@ifc_psets = ps;
}}}

* Наборы с именем `Pset_...` — стандартные, их свойства проверяются по шаблонам buildingSMART (типы значений приводятся автоматически: 0/1 -> Boolean). *Свои наборы не называйте на `Pset_`* — используйте префикс проекта (`ACME_Data`, `ACME_Common`).
* Наборы `Qto_...` с числовыми значениями пишутся как IfcElementQuantity (количества для смет).
* *Единицы:* длины, площади и объёмы в свойствах — в единицах проекта IFC (параметр Length Unit, по умолчанию *мм*), а не в метрах Houdini. Умножайте на 1000.
* Быстрый способ без словаря: перечислите атрибуты в __Attributes to Pset__ (маски, например `len_* N_*`) — они попадут в набор __Pset Name__ (HoudiniAttributes).
* __Add Houdini_Path Property__ добавляет исходный path в этот же набор — удобно для обратной связи.

== GUID ==

`s@ifc_guid` — 22-символьный IFC GlobalId (например, сохранённый после импорта). Если задан и корректен — используется как есть.
Иначе GUID вычисляется из path + storey + __GUID Seed__: стабилен между экспортами. Меняйте GUID Seed, только если нужно намеренно «перевыпустить» все элементы.

== Геометрия ==

* Только полигоны. Packed-примитивы раскрываются автоматически; кривые, точки и объёмы пропускаются.
* Замкнутые оболочки с нормалями наружу (стандарт Houdini). Не оставляйте вырожденных полигонов.
* Единицы сцены — метры (параметр Scene Unit), ось Y вверх (переворачивается в Z-up).
* Держите полигонаж разумным: IFC — не рендер. Цилиндр из 12–16 сегментов достаточен.
* Точка вставки элемента — низ центра габарита (__Element Origin__).

== Чек-лист перед выгрузкой ==

# `s@path` есть на каждом примитиве; один path = один предмет.
# Класс: `s@ifc_class` или Class Rules; нет «лишних» Proxy.
# `s@ifc_storey` задан (или устраивает Default Storey).
# `s@ifc_material` и `Cd` заданы по категориям.
# Свойства в `d@ifc_psets`, свои наборы не на `Pset_`, длины в мм.
# __Check Attributes__ без ошибок -> __Export IFC__ -> включите __Validate After Export__.
# Откройте файл в Bonsai / BIMvision и проверьте дерево.

@parameters

== Buttons ==

Export IFC:
    Записать файл.
Check Attributes:
    Проверить атрибуты и показать отчёт (файл не пишется).

== Project ==

Schema:
    IFC4 (рекомендуется), IFC4X3, IFC2X3.
Length Unit:
    Единица длины в файле (мм по умолчанию). В ней же задаются длины в свойствах.
Scene Unit:
    Сколько метров в единице Houdini (1 = метры).
GUID Seed:
    Добавка к ключу генерации GUID.

== Structure ==

Path Attribute:
    Строковый prim-атрибут иерархии.
Skip Leading Segments:
    Отбросить первые N сегментов пути.
Class Rules:
    Маска -> класс -> PredefinedType, если нет `s@ifc_class`.

== Attributes ==

Имена атрибутов, из которых берутся класс, тип, имя, марка, GUID, этаж, материал, стиль и словарь свойств.
"""

HELP_IMPORT_RU = u"""= HIFC IFC Import =

#type: node
#context: sop
#internal: hifc::ifc_import
#icon: SOP/file

\"\"\"Читает IFC через IfcOpenShell. Один элемент — один packed-примитив (или набор треугольников).\"\"\"

Результат несёт те же атрибуты, которые понимает HIFC IFC Export, поэтому импорт -> правка -> экспорт сохраняет структуру и GlobalId.

@parameters

IFC File:
    Файл IFC2X3 / IFC4 / IFC4X3.
Output:
    Packed Primitive per Element — как объекты в Bonsai; Polygons — плоская сетка.
Path:
    "From First Assembly" — путь от первой сборки (для обратного экспорта); "Full" — от IfcProject.
Include / Exclude Classes:
    Фильтр по классам через пробел.

@attributes

`path`, `ifc_guid`, `ifc_class`, `ifc_predefined`, `ifc_name`, `ifc_tag`, `ifc_object_type`, `ifc_storey`, `ifc_type`,
`ifc_material`, `ifc_style`, `ifc_id`, `d@ifc_psets`, `Cd`, `Alpha`.
"""


HELP_EXPORT_EN = u"""= HIFC IFC Export =

#type: node
#context: sop
#internal: hifc::ifc_export
#icon: SOP/rop_geometry

\"\"\"Writes the input geometry to IFC (IfcOpenShell, no Blender needed). The BIM structure is driven by primitive attributes.\"\"\"

Press __Check Attributes__ before exporting: the node validates the attributes and writes a report to the Report tab without writing any file.
Ready-made attribute template: __HIFC > Create Attribute Template__ (a Primitive Wrangle appended to the selected node).

== How a BIM model is organised ==

IFC is not a scene graph but a "what is inside what" tree:

{{{
IfcProject            <- Project parameter
 └ IfcSite            <- Site parameter
    └ IfcBuilding     <- Building parameter
       └ IfcBuildingStorey          <- s@ifc_storey
          └ IfcElementAssembly      <- intermediate segments of s@path
             └ IfcElementAssembly
                └ IfcMember / IfcLightFixture / ...   <- last segment of s@path
}}}

*Project, site and building* come from node parameters (Project tab).
*Storey* comes from `s@ifc_storey`. *Everything below the storey* comes from `s@path`.

== Main rule: one path = one physical element ==

All primitives sharing the same `s@path` value are merged into *one* IFC element.

* An element is something that is counted, ordered and installed as a separate piece: a profile, a hanger, a lamp, a bracket, a panel.
* Do not put two physical pieces under one path: they become one line in the schedule.
* Do not split one piece across several paths: it becomes several lines.
* Need several colours inside one element? Give the primitives of one path different `Cd` values: you get one element with several styles.

== s@path: hierarchy ==

{{{
/Frame_001/Frame_001_Profile/Profile_0007
 │          │                 └ element (IfcMember)
 │          └ group   -> IfcElementAssembly
 └ system             -> IfcElementAssembly
}}}

* Separator is `/`. The leading `/` is optional.
* Every intermediate segment is an assembly (`Assembly Class` on the Structure tab, IfcElementAssembly by default). Equal prefixes are the same assembly.
* A path cannot be both an element and a folder: `/A/B` together with `/A/B/C` is an error.
* Segment names: Latin letters, digits, `_`, `-`, `.`, space. Names must be unique among siblings.
* *Names must be stable.* When no GUID is given, it is derived from path + storey: the same path gives the same GlobalId on every export. Do not use `@primnum` or random numbers in the path, or the BIM coordinator receives "new" elements on every export.
* 2 to 4 levels deep is normal. Avoid single-element assemblies unless they mean something.
* __Skip Leading Segments__ strips the beginning of the path (for example a technical `/obj/geo1`).

== Element class ==

The class is resolved in this order:
# `s@ifc_class` on the primitive;
# the first matching __Class Rules__ entry (glob on the element name or the full path, for example `Bracket_*`);
# __Default Class__ (IfcBuildingElementProxy).

`s@ifc_predefined` refines the class (PredefinedType) and must be a value of that class's enumeration.
An unknown value becomes USERDEFINED and the text goes to ObjectType. If unsure, use `NOTDEFINED`.

Common classes:

`IfcMember` / `MEMBER`, `STRUT`, `BRACE`, `MULLION`:
    Profiles, rods, battens, ties.
`IfcBeam` / `BEAM`, `JOIST`, `LINTEL`:
    Beams, purlins.
`IfcColumn` / `COLUMN`, `PILASTER`:
    Columns, posts.
`IfcPlate` / `SHEET`, `CURTAIN_PANEL`:
    Sheets, panels.
`IfcSlab` / `FLOOR`, `ROOF`, `LANDING`:
    Slabs.
`IfcWall` / `STANDARD`, `PARTITIONING`:
    Walls, partitions.
`IfcCovering` / `CEILING`, `CLADDING`, `FLOORING`:
    Finishes, suspended ceilings.
`IfcRailing` / `HANDRAIL`, `GUARDRAIL`:
    Railings.
`IfcDiscreteAccessory` / `BRACKET`, `SHOE`, `NOTDEFINED`:
    Hangers, brackets, embeds.
`IfcFastener` / `WELD`, `GLUE`; `IfcMechanicalFastener` / `BOLT`, `ANCHORBOLT`:
    Fasteners.
`IfcLightFixture` / `POINTSOURCE`, `DIRECTIONSOURCE`, `NOTDEFINED`:
    Luminaires, light tubes.
`IfcCableCarrierSegment` / `CABLETRAYSEGMENT`, `CONDUITSEGMENT`:
    Cable trays, conduits.
`IfcPipeSegment` / `RIGIDSEGMENT`:
    Pipes (building services, not decorative tubes).
`IfcFurniture` / `TABLE`, `CHAIR`, `SHELF`:
    Furniture.
`IfcAnnotation`:
    Labels and tags without physical volume.
`IfcBuildingElementProxy`:
    Anything without a fitting class. An honest proxy is better than a wrong class.

Schemas: IFC4 is the default (Revit, Archicad, Bonsai, Navisworks). IFC4X3 is for infrastructure (IfcCourse, IfcTrackElement...). IFC2X3 only for legacy software; some classes are missing there (IfcPipeSegment becomes a proxy).

== Names and marks ==

`s@ifc_name`:
    Name, shown in the BIM tree. Defaults to the last path segment.
`s@ifc_tag`:
    Tag, the drawing mark / position (for example `F-01.P-007`).
`s@ifc_object_type`:
    ObjectType, your type / article code (Profile_40x40, Lamp_1500).
`s@ifc_description`:
    Description, free text.

== Storey ==

`s@ifc_storey` is the storey name (`Level 01`, `+3.600`). All elements with the same value go into one IfcBuildingStorey.
Empty means __Default Storey__. Assemblies are built per storey: the same path prefix on different storeys gives different assemblies.

== Material and colour ==

`s@ifc_material`:
    Material name (IfcMaterial). Equal names share one material in the project. Use real materials: `Aluminium`, `Steel S235`, `Polycarbonate`.
`Cd` (prim or point), `f@Alpha`:
    Colour and transparency -> IfcSurfaceStyle. Equal colours share one style.
`s@ifc_style`:
    Style name (otherwise `Color_RRGGBB` is generated).

== Properties (property sets) ==

The main way is the `d@ifc_psets` dictionary `{SetName: {Property: value}}`:

{{{
#!vex
dict data;   data["Length_mm"] = 1500;  data["SystemID"] = 1;
dict common; common["IsExternal"] = 0;  common["LoadBearing"] = 0;
dict qto;    qto["Length"] = 1500;
dict ps;
ps["ACME_Data"]                = data;    // your own set
ps["Pset_MemberCommon"]        = common;  // standard buildingSMART set
ps["Qto_MemberBaseQuantities"] = qto;     // quantities
d@ifc_psets = ps;
}}}

* `Pset_...` sets are standard: their properties are typed from the buildingSMART templates (0/1 becomes Boolean automatically). *Do not name your own sets `Pset_...`*: use a project prefix (`ACME_Data`, `ACME_Common`).
* `Qto_...` sets with numeric values are written as IfcElementQuantity (quantities for cost estimates).
* *Units:* lengths, areas and volumes in properties are in IFC project units (Length Unit parameter, *millimetres* by default), not Houdini metres. Multiply by 1000.
* Quick way without a dictionary: list attributes in __Attributes to Pset__ (globs such as `len_* N_*`); they go to the __Pset Name__ set (HoudiniAttributes).
* __Add Houdini_Path Property__ adds the source path to that set, handy for tracing back.

== GUID ==

`s@ifc_guid` is a 22-character IFC GlobalId (for example kept from an import). If present and valid it is used as is.
Otherwise the GUID is derived from path + storey + __GUID Seed__ and stays stable between exports. Change the GUID Seed only to deliberately re-issue all elements.

== Geometry ==

* Polygons only. Packed primitives are unpacked automatically; curves, points and volumes are skipped.
* Closed shells with outward normals (Houdini default). Avoid degenerate polygons.
* Scene units are metres (Scene Unit parameter), Y up (converted to Z up).
* Keep polygon counts sensible: IFC is not a render. 12 to 16 segments are enough for a cylinder.
* The element insertion point is the bottom centre of its bounding box (__Element Origin__).

== Checklist before export ==

# `s@path` on every primitive; one path = one piece.
# Class from `s@ifc_class` or Class Rules; no unnecessary proxies.
# `s@ifc_storey` set (or Default Storey is fine).
# `s@ifc_material` and `Cd` set per category.
# Properties in `d@ifc_psets`, own sets not named `Pset_`, lengths in mm.
# __Check Attributes__ without errors -> __Export IFC__ -> turn on __Validate After Export__.
# Open the file in Bonsai / BIMvision and review the tree.

@parameters

== Buttons ==

Export IFC:
    Write the file.
Check Attributes:
    Validate attributes and show a report (no file is written).

== Project ==

Schema:
    IFC4 (recommended), IFC4X3, IFC2X3.
Length Unit:
    Length unit of the file (mm by default). Property lengths use it too.
Scene Unit:
    Metres per Houdini unit (1 = metres).
GUID Seed:
    Extra key for GUID generation.

== Structure ==

Path Attribute:
    String prim attribute with the hierarchy.
Skip Leading Segments:
    Drop the first N path segments.
Class Rules:
    Glob -> class -> PredefinedType, used when `s@ifc_class` is missing.

== Attributes ==

Names of the attributes that provide class, type, name, tag, GUID, storey, material, style and the property dictionary.
"""

HELP_IMPORT_EN = u"""= HIFC IFC Import =

#type: node
#context: sop
#internal: hifc::ifc_import
#icon: SOP/file

\"\"\"Reads IFC with IfcOpenShell. One element = one packed primitive (or a set of triangles).\"\"\"

The output carries the same attributes that HIFC IFC Export understands, so import -> edit -> export keeps the structure and the GlobalIds.

@parameters

IFC File:
    IFC2X3 / IFC4 / IFC4X3 file.
Output:
    Packed Primitive per Element (like objects in Bonsai) or Polygons (flat mesh).
Path:
    "From First Assembly" gives paths from the first assembly (for re-export); "Full" starts at IfcProject.
Include / Exclude Classes:
    Space-separated class filter.

@attributes

`path`, `ifc_guid`, `ifc_class`, `ifc_predefined`, `ifc_name`, `ifc_tag`, `ifc_object_type`, `ifc_storey`, `ifc_type`,
`ifc_material`, `ifc_style`, `ifc_id`, `d@ifc_psets`, `Cd`, `Alpha`.
"""


def _lang():
    import os
    return (os.environ.get("HIFC_HELP_LANG") or "en").lower()[:2]


# язык справки: переменная HIFC_HELP_LANG в packages/HIFC.json ("en" по умолчанию, "ru")
HELP_EXPORT = HELP_EXPORT_RU if _lang() == "ru" else HELP_EXPORT_EN
HELP_IMPORT = HELP_IMPORT_RU if _lang() == "ru" else HELP_IMPORT_EN
