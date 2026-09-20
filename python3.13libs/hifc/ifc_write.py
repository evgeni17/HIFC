# SPDX-FileCopyrightText: 2026 EOK
# SPDX-License-Identifier: Apache-2.0
"""Запись IFC из нейтрального описания элементов (без зависимости от hou).

Вход — список словарей-элементов:
    {
        "path":      "/Frame_1/Bracket_3",   # иерархия; промежуточные сегменты -> сборки
        "ifc_class": "IfcMember",          # класс листа (пусто -> default_class)
        "predefined": "MEMBER",            # PredefinedType (необязательно)
        "name":      "Bracket_3",           # по умолчанию — последний сегмент path
        "guid":      "...22 символа...",   # необязательно; иначе детерминированный из path
        "storey":    "Level 1",            # необязательно; иначе opts.storey
        "material":  "Steel",             # необязательно -> IfcMaterial
        "psets":     {"Pset_X": {"a": 1}}, # свойства (без measures — в единицах проекта)
        "measures":  {"Pset_X": {"a": "LENGTH"}},  # эти значения заданы в СИ (м, м², м³) и будут пересчитаны
        "materials": ["Glass", "Wood"],   # несколько материалов -> IfcMaterialConstituentSet
        "items": [                         # части геометрии (одна часть = один стиль)
            {"verts": ndarray(N,3) в МЕТРАХ, IFC-оси (Z вверх),
             "faces": [[i, j, k, ...], ...],   # CCW снаружи (правило IFC)
             "color": (r, g, b, a) или None,
             "style": "имя стиля" или None},
        ],
    }
"""
import time
import uuid

import numpy as np

import ifcopenshell
import ifcopenshell.api
import ifcopenshell.api.aggregate
import ifcopenshell.api.context
import ifcopenshell.api.geometry
import ifcopenshell.api.material
import ifcopenshell.api.owner
import ifcopenshell.api.owner.settings
import ifcopenshell.api.project
import ifcopenshell.api.pset
import ifcopenshell.api.root
import ifcopenshell.api.spatial
import ifcopenshell.api.style
import ifcopenshell.api.unit
import ifcopenshell.guid
import ifcopenshell.util.unit
from ifcopenshell.util.shape_builder import ShapeBuilder

# пространство имён для детерминированных GUID (не менять — иначе поплывут GlobalId)
GUID_NS = uuid.UUID("5b1d1f0e-8e1a-4c1e-9a57-4849464301a0")

LENGTH_PREFIX = {"mm": "MILLI", "cm": "CENTI", "m": None}

DEFAULT_OPTIONS = {
    "schema": "IFC4",
    "project": "Houdini Project",
    "site": "Site",
    "building": "Building",
    "storey": "Level 0",
    "length_unit": "mm",           # mm | cm | m
    "origin": "bbox_bottom",       # world | bbox_center | bbox_bottom
    "default_class": "IfcBuildingElementProxy",
    "assembly_class": "IfcElementAssembly",
    "assembly_predefined": "NOTDEFINED",
    "guid_seed": "",               # добавка к ключу GUID (например, имя проекта)
    "application": "HIFC for Houdini",
}


def stable_guid(key, seed=""):
    """Детерминированный IFC GlobalId из строки-ключа."""
    return ifcopenshell.guid.compress(uuid.uuid5(GUID_NS, seed + "|" + key).hex)


def _valid_guid(g):
    if not g or len(g) != 22:
        return False
    try:
        ifcopenshell.guid.expand(g)
        return True
    except Exception:
        return False


STATUS_TEXT = {
    "unknown": "not in the schema",
    "not_product": "not a physical product (IfcProduct subtype)",
    "abstract": "abstract",
    "spatial": "a spatial container, not an element",
}
_NOT_EXPORTABLE = ("IfcProject", "IfcSite", "IfcBuilding", "IfcBuildingStorey",
                   "IfcGrid", "IfcStructuralItem",
                   "IfcPort", "IfcVirtualElement")


def class_status(schema_identifier, cls):
    """'ok' | 'unknown' | 'not_product' | 'abstract' | 'spatial' — можно ли писать класс как элемент с геометрией."""
    import ifcopenshell.ifcopenshell_wrapper as w
    try:
        decl = w.schema_by_name(schema_identifier).declaration_by_name(cls)
    except Exception:
        return "unknown"
    if decl is None or not hasattr(decl, "is_abstract"):
        return "unknown"
    if decl.is_abstract():
        return "abstract"
    chain, d = [], decl
    while d is not None:
        chain.append(d.name())
        d = d.supertype()
    if "IfcProduct" not in chain:
        return "not_product"
    if any(n in chain for n in _NOT_EXPORTABLE):
        return "spatial"
    return "ok"


def _is_feature_element(schema_identifier, cls):
    """IfcFeatureElement (проёмы, поверхностные элементы) требует связи с хостом."""
    import ifcopenshell.ifcopenshell_wrapper as w
    try:
        decl = w.schema_by_name(schema_identifier).declaration_by_name(cls)
        while decl is not None:
            if decl.name() == "IfcFeatureElement":
                return True
            decl = decl.supertype()
    except Exception:
        pass
    return False


def downgrade_reason(schema_identifier, cls):
    """Почему класс не может быть записан как есть (для writer и тестов). '' — может."""
    st = class_status(schema_identifier, cls)
    if st != "ok":
        return STATUS_TEXT[st]
    if _is_feature_element(schema_identifier, cls):
        return "needs a host element"
    return ""


def _split_path(path):
    return [s for s in str(path or "").replace("\\", "/").split("/") if s]


class _Writer:
    def __init__(self, opts, log):
        self.o = dict(DEFAULT_OPTIONS)
        self.o.update({k: v for k, v in (opts or {}).items() if v is not None})
        self.log = log
        self.warnings = []
        self.used_guids = set()
        self.styles = {}
        self.materials = {}
        self.material_members = {}
        self.material_sets = {}
        self.storeys = {}
        self.container_members = {}
        self.assemblies = {}
        self.aggregate_members = {}
        self.class_cache = {}
        self._zero_axis = None
        self._tmpl_cache = {}
        self._templates = None
        self._oh_cache = None

    # ---------- проект ----------
    def create_project(self):
        o = self.o
        f = ifcopenshell.api.project.create_file(version=o["schema"])
        self.f = f
        if f.schema == "IFC2X3":
            self._setup_owner_history()
        self.project = ifcopenshell.api.root.create_entity(f, ifc_class="IfcProject", name=o["project"])
        self._set_guid(self.project, "project")
        length = ifcopenshell.api.unit.add_si_unit(f, unit_type="LENGTHUNIT", prefix=LENGTH_PREFIX.get(o["length_unit"]))
        area = ifcopenshell.api.unit.add_si_unit(f, unit_type="AREAUNIT")
        volume = ifcopenshell.api.unit.add_si_unit(f, unit_type="VOLUMEUNIT")
        angle = ifcopenshell.api.unit.add_si_unit(f, unit_type="PLANEANGLEUNIT")
        ifcopenshell.api.unit.assign_unit(f, units=[length, area, volume, angle])
        self.unit_scale = ifcopenshell.util.unit.calculate_unit_scale(f)  # метров в единице проекта
        self.kind_scale = {"LENGTH": self.unit_scale,
                           "AREA": ifcopenshell.util.unit.calculate_unit_scale(f, "AREAUNIT"),
                           "VOLUME": ifcopenshell.util.unit.calculate_unit_scale(f, "VOLUMEUNIT")}
        model = ifcopenshell.api.context.add_context(f, context_type="Model")
        self.body = ifcopenshell.api.context.add_context(
            f, context_type="Model", context_identifier="Body", target_view="MODEL_VIEW", parent=model
        )
        self.builder = ShapeBuilder(f)
        self.site = ifcopenshell.api.root.create_entity(f, ifc_class="IfcSite", name=o["site"])
        self._set_guid(self.site, "site")
        self.building = ifcopenshell.api.root.create_entity(f, ifc_class="IfcBuilding", name=o["building"])
        self._set_guid(self.building, "building")
        ifcopenshell.api.aggregate.assign_object(f, products=[self.site], relating_object=self.project)
        ifcopenshell.api.aggregate.assign_object(f, products=[self.building], relating_object=self.site)
        for e in (self.site, self.building):
            ifcopenshell.api.geometry.edit_object_placement(f, product=e)

    def _setup_owner_history(self):
        # IFC2X3 требует OwnerHistory у каждого IfcRoot
        f = self.f
        person = f.createIfcPerson(FamilyName="Houdini")
        org = f.createIfcOrganization(Name="HIFC")
        user = f.createIfcPersonAndOrganization(person, org)
        app = f.createIfcApplication(org, "0.1", self.o["application"], "HIFC")
        ifcopenshell.api.owner.settings.get_user = lambda ifc: user
        ifcopenshell.api.owner.settings.get_application = lambda ifc: app

    def _set_guid(self, entity, key, wanted=None):
        g = wanted if (_valid_guid(wanted) and wanted not in self.used_guids) else None
        if g is None:
            g = stable_guid(key, self.o["guid_seed"])
            n = 1
            while g in self.used_guids:
                g = stable_guid("%s#%d" % (key, n), self.o["guid_seed"])
                n += 1
        entity.GlobalId = g
        self.used_guids.add(g)

    def get_storey(self, name):
        name = name or self.o["storey"]
        s = self.storeys.get(name)
        if s is None:
            s = ifcopenshell.api.root.create_entity(self.f, ifc_class="IfcBuildingStorey", name=name)
            self._set_guid(s, "storey|" + name)
            ifcopenshell.api.aggregate.assign_object(self.f, products=[s], relating_object=self.building)
            ifcopenshell.api.geometry.edit_object_placement(self.f, product=s)
            self.storeys[name] = s
            self.container_members[name] = []
        return s

    # ---------- классы ----------
    def create_product(self, ifc_class, predefined, name, object_type=None):
        """Создаёт элемент. Недопустимый класс -> default_class (с предупреждением), неверный тип -> USERDEFINED."""
        f = self.f
        cls = ifc_class or self.o["default_class"]
        if cls not in self.class_cache:
            status = class_status(f.schema_identifier, cls)
            if status != "ok":
                self.warnings.append("Class '%s' is %s for schema %s -> %s" % (
                    cls, STATUS_TEXT[status], f.schema, self.o["default_class"]))
            self.class_cache[cls] = cls if status == "ok" else self.o["default_class"]
        cls = self.class_cache[cls]
        orig_cls = cls
        if self._needs_host(cls):
            # IfcFeatureElement (проёмы, поверхностные элементы) требует связи с хостом — пишем как Proxy
            self.warnings.append("%s needs a host element -> IfcBuildingElementProxy (ObjectType=%s)" % (cls, cls))
            cls = "IfcBuildingElementProxy"
        pt = (predefined or "").strip() or None
        e = ifcopenshell.api.root.create_entity(f, ifc_class=cls, name=name)
        if pt and hasattr(e, "PredefinedType"):
            try:
                e.PredefinedType = pt
            except Exception:
                # значения нет в перечислении класса -> USERDEFINED + текст в ObjectType
                try:
                    e.PredefinedType = "USERDEFINED"
                    if hasattr(e, "ObjectType") and not object_type:
                        object_type = pt
                except Exception:
                    pass
        if orig_cls != cls and hasattr(e, "ObjectType") and not object_type:
            # исходный класс сохраняем в ObjectType, только если своего у элемента нет —
            # данные пользователя важнее подсказки о замене класса
            object_type = orig_cls
        if object_type and hasattr(e, "ObjectType"):
            e.ObjectType = object_type
        self._fill_required_enums(e)
        return e

    def _needs_host(self, cls):
        return _is_feature_element(self.f.schema_identifier, cls)

    def _fill_required_enums(self, e):
        """Обязательные enum-атрибуты (напр. IfcRoadPart.UsageType) -> NOTDEFINED."""
        try:
            decl = ifcopenshell.ifcopenshell_wrapper.schema_by_name(self.f.schema_identifier).declaration_by_name(e.is_a())
            for i, a in enumerate(decl.all_attributes()):
                if a.optional() or e[i] is not None:
                    continue
                t = a.type_of_attribute()
                while hasattr(t, "declared_type") and not hasattr(t, "enumeration_items"):
                    t = t.declared_type()
                items = t.enumeration_items() if hasattr(t, "enumeration_items") else ()
                if "NOTDEFINED" in items:
                    e[i] = "NOTDEFINED"
        except Exception:
            pass

    # ---------- сборки ----------
    def get_parent(self, storey_name, segments):
        """Возвращает сборку для префикса пути (создаёт при необходимости) или None."""
        if not segments:
            return None
        key = (storey_name, tuple(segments))
        a = self.assemblies.get(key)
        if a is not None:
            return a
        a = self.create_product(self.o["assembly_class"], self.o["assembly_predefined"], segments[-1])
        self._set_guid(a, "asm|%s|/%s" % (storey_name, "/".join(segments)))
        self.assemblies[key] = a
        parent = self.get_parent(storey_name, segments[:-1])
        a.ObjectPlacement = self._placement(parent or self.storeys[storey_name], None)
        self._attach(a, parent, storey_name)
        return a

    def _attach(self, product, parent, storey_name):
        if parent is None:
            self.container_members[storey_name].append(product)
        else:
            self.aggregate_members.setdefault(parent.id(), (parent, []))[1].append(product)

    # ---------- стили / материалы ----------
    def get_style(self, color, name):
        r, g, b, a = [float(x) for x in (list(color) + [1.0] * 4)[:4]]
        key = (name or "", round(r, 4), round(g, 4), round(b, 4), round(a, 4))
        s = self.styles.get(key)
        if s is None:
            sname = name or "Color_%02X%02X%02X" % tuple(int(max(0, min(1, c)) * 255 + 0.5) for c in (r, g, b))
            s = ifcopenshell.api.style.add_style(self.f, name=sname)
            # в IFC2X3 у Shading нет Transparency -> используем Rendering
            ifcopenshell.api.style.add_surface_style(
                self.f, style=s,
                ifc_class="IfcSurfaceStyleRendering" if self.f.schema == "IFC2X3" else "IfcSurfaceStyleShading",
                attributes=dict(
                    {"SurfaceColour": {"Name": None, "Red": r, "Green": g, "Blue": b},
                     "Transparency": max(0.0, min(1.0, 1.0 - a))},
                    **({"ReflectanceMethod": "NOTDEFINED"} if self.f.schema == "IFC2X3" else {})),
            )
            self.styles[key] = s
        return s

    def use_material(self, names, product, style):
        """names: строка или список. Один материал -> IfcMaterial, несколько -> набор составляющих (IFC2X3: список)."""
        if isinstance(names, str):
            names = [names]
        names = [n for n in names if n]
        if not names:
            return
        mats = []
        for name in names:
            m = self.materials.get(name)
            if m is None:
                m = ifcopenshell.api.material.add_material(self.f, name=name)
                self.materials[name] = m
                if style is not None and len(names) == 1:
                    ifcopenshell.api.style.assign_material_style(self.f, material=m, style=style, context=self.body)
            mats.append(m)
        key = tuple(names)
        if key not in self.material_members:
            self.material_members[key] = []
            if len(mats) == 1:
                self.material_sets[key] = mats[0]
            elif self.f.schema == "IFC2X3":
                self.material_sets[key] = self.f.createIfcMaterialList(mats)
            else:
                ms = ifcopenshell.api.material.add_material_set(
                    self.f, name=" + ".join(names), set_type="IfcMaterialConstituentSet")
                for m in mats:
                    ifcopenshell.api.material.add_constituent(self.f, constituent_set=ms, material=m)
                self.material_sets[key] = ms
        self.material_members[key].append(product)

    def _face_set(self, local, faces):
        """Только треугольники -> IfcTriangulatedFaceSet (одна сущность вместо тысяч граней), иначе полигональный."""
        f = self.f
        if faces and all(len(fc) == 3 for fc in faces):
            pts = f.createIfcCartesianPointList3D([tuple(map(float, p)) for p in local])
            idx = (np.asarray(faces, dtype=np.int64) + 1).tolist()
            return f.create_entity("IfcTriangulatedFaceSet", Coordinates=pts, CoordIndex=idx, Closed=None)
        return self.builder.polygonal_face_set(local.tolist(), faces)

    # ---------- быстрые наборы свойств ----------
    _PY_MEASURE = ((bool, "IfcBoolean"), (int, "IfcInteger"), (float, "IfcReal"), (str, "IfcLabel"))

    def _template_types(self, pname):
        """{свойство: (TemplateType, PrimaryMeasureType)} из шаблонов buildingSMART, с кэшем."""
        c = self._tmpl_cache.get(pname)
        if c is None:
            c = {}
            if pname.startswith("Pset_"):
                try:
                    if self._templates is None:
                        import ifcopenshell.util.pset
                        self._templates = ifcopenshell.util.pset.get_template(self.f.schema_identifier)
                    t = self._templates.get_by_name(pname)
                    for pt in (t.HasPropertyTemplates if t is not None else ()):
                        c[pt.Name] = (pt.TemplateType, pt.PrimaryMeasureType)
                except Exception:
                    c = {}
            self._tmpl_cache[pname] = c
        return c

    def _nominal(self, value, measure):
        f = self.f
        if isinstance(value, ifcopenshell.entity_instance):
            return value
        if measure:
            try:
                return f.create_entity(measure, value)
            except Exception:
                try:
                    cast = float if isinstance(value, (int, float)) and not isinstance(value, bool) else str
                    return f.create_entity(measure, cast(value))
                except Exception:
                    pass
        for py, m in self._PY_MEASURE:
            if isinstance(value, py):
                if m == "IfcLabel" and len(value) > 255:
                    m = "IfcText"
                return f.create_entity(m, value)
        return f.create_entity("IfcLabel", str(value))

    def _fast_pset(self, product, pname, props):
        """IfcPropertySet без api (в разы быстрее на тысячах элементов). False -> нужен общий путь."""
        tmpl = self._template_types(pname)
        if any(tmpl.get(k, ("P_SINGLEVALUE",))[0] != "P_SINGLEVALUE" for k in props):
            return False  # перечисления/списки по шаблону — через ifcopenshell.api
        f = self.f
        items = []
        for k, v in props.items():
            items.append(f.create_entity("IfcPropertySingleValue", Name=str(k),
                                         NominalValue=self._nominal(v, tmpl.get(k, (None, None))[1])))
        oh = self._oh()
        ps = f.create_entity("IfcPropertySet", GlobalId=self._new_guid(), OwnerHistory=oh, Name=pname, HasProperties=items)
        f.create_entity("IfcRelDefinesByProperties", GlobalId=self._new_guid(), OwnerHistory=oh,
                        RelatedObjects=[product], RelatingPropertyDefinition=ps)
        return True

    def _oh(self):
        if self._oh_cache is None and self.f.schema == "IFC2X3":
            self._oh_cache = self._owner_history()
        return self._oh_cache

    def _measure(self, kind, value_si):
        """СИ -> единицы проекта, типизированное значение IFC (IfcLengthMeasure и т.п.)."""
        cls = {"LENGTH": "IfcLengthMeasure", "AREA": "IfcAreaMeasure", "VOLUME": "IfcVolumeMeasure"}[kind]
        return self.f.create_entity(cls, float(value_si) / self.kind_scale[kind])

    # ---------- элемент ----------
    def add_element(self, el):
        f = self.f
        segs = _split_path(el.get("path"))
        name = el.get("name") or (segs[-1] if segs else "Element")
        storey_name = el.get("storey") or self.o["storey"]
        self.get_storey(storey_name)
        product = self.create_product(el.get("ifc_class"), el.get("predefined"), name, el.get("objecttype"))
        self._set_guid(product, "el|%s|/%s" % (storey_name, "/".join(segs) or name), el.get("guid"))
        for attr in ("Description", "Tag"):
            v = el.get(attr.lower())
            if v and hasattr(product, attr):
                setattr(product, attr, v)

        items = [it for it in el.get("items", []) if len(it.get("faces", [])) and len(it.get("verts", []))]
        first_style = None
        if items:
            allv = np.concatenate([np.asarray(it["verts"], dtype=np.float64) for it in items])
            origin = self._origin(allv)
            rep_items = []
            for it in items:
                local = (np.asarray(it["verts"], dtype=np.float64) - origin) / self.unit_scale
                faces = [[int(i) for i in face] for face in it["faces"]]
                if f.schema == "IFC2X3":
                    item = self.builder.faceted_brep(local.tolist(), faces)
                else:
                    item = self._face_set(local, faces)
                rep_items.append(item)
                if it.get("color") is not None or it.get("style"):
                    st = self.get_style(it.get("color") if it.get("color") is not None else (0.8, 0.8, 0.8, 1), it.get("style"))
                    first_style = first_style or st
                    ifcopenshell.api.style.assign_item_style(f, item=item, style=st)
            rep = f.createIfcShapeRepresentation(
                self.body, self.body.ContextIdentifier,
                "Brep" if f.schema == "IFC2X3" else "Tessellation", rep_items,
            )
            ifcopenshell.api.geometry.assign_representation(f, product=product, representation=rep)
        else:
            origin = None

        all_measures = el.get("measures") or {}
        for pname, props in (el.get("psets") or {}).items():
            props = {k: v for k, v in (props or {}).items() if v is not None and k != "id"}
            if not props:
                continue
            # величины с известным видом (из d@ifc_measures) заданы в СИ -> пересчёт в единицы проекта
            kinds = all_measures.get(pname) or {}
            for k, kind in kinds.items():
                v = props.get(k)
                if kind in self.kind_scale and isinstance(v, (int, float)) and not isinstance(v, bool):
                    props[k] = self._measure(kind, v)
            # Qto_* -> IfcElementQuantity (только числа), остальное -> IfcPropertySet
            is_qto = str(pname).startswith("Qto_") and all(
                isinstance(v, ifcopenshell.entity_instance) or (isinstance(v, (int, float)) and not isinstance(v, bool))
                for v in props.values())
            try:
                if is_qto:
                    q = ifcopenshell.api.pset.add_qto(f, product=product, name=str(pname))
                    ifcopenshell.api.pset.edit_qto(f, qto=q, properties={
                        k: (v if isinstance(v, ifcopenshell.entity_instance) else float(v)) for k, v in props.items()})
                elif not self._fast_pset(product, str(pname), props):
                    p = ifcopenshell.api.pset.add_pset(f, product=product, name=str(pname))
                    ifcopenshell.api.pset.edit_pset(f, pset=p, properties=props)
            except Exception as ex:
                self.warnings.append("Pset %s on %s: %s" % (pname, name, ex))

        if el.get("materials") or el.get("material"):
            self.use_material(el.get("materials") or el["material"], product, first_style)

        parent = self.get_parent(storey_name, segs[:-1])
        # все родители (этаж, сборки) стоят в нуле -> локальная плейсмент = мировая
        product.ObjectPlacement = self._placement(parent or self.storeys[storey_name], origin)
        self._attach(product, parent, storey_name)
        return product

    def _placement(self, rel_obj, origin_si):
        """IfcLocalPlacement относительно плейсмента rel_obj (без api — api медленно перестраивает дерево)."""
        f = self.f
        if origin_si is None or not np.any(origin_si):
            if self._zero_axis is None:
                self._zero_axis = f.createIfcAxis2Placement3D(f.createIfcCartesianPoint((0.0, 0.0, 0.0)), None, None)
            ax = self._zero_axis
        else:
            p = [float(x) / self.unit_scale for x in origin_si]
            ax = f.createIfcAxis2Placement3D(f.createIfcCartesianPoint(p), None, None)
        return f.createIfcLocalPlacement(rel_obj.ObjectPlacement if rel_obj is not None else None, ax)

    def _owner_history(self):
        if self.f.schema != "IFC2X3":
            return None
        import ifcopenshell.api.owner
        return ifcopenshell.api.owner.create_owner_history(self.f)

    def _new_guid(self):
        g = ifcopenshell.guid.new()
        self.used_guids.add(g)
        return g

    def _origin(self, v):
        mode = self.o["origin"]
        if mode == "world":
            return np.zeros(3)
        lo, hi = v.min(axis=0), v.max(axis=0)
        c = (lo + hi) * 0.5
        if mode == "bbox_bottom":
            c[2] = lo[2]
        return c

    # ---------- финал ----------
    def finalize(self):
        f = self.f
        # связи создаём напрямую: api.aggregate/spatial пересчитывают плейсменты и очень медленные на 10k+
        oh = self._owner_history()
        for parent, children in self.aggregate_members.values():
            f.createIfcRelAggregates(self._new_guid(), oh, None, None, parent, children)
        for sname, members in self.container_members.items():
            if members:
                f.createIfcRelContainedInSpatialStructure(self._new_guid(), oh, None, None, members, self.storeys[sname])
        for key, members in self.material_members.items():
            if members:
                ifcopenshell.api.material.assign_material(
                    f, products=members, type=self.material_sets[key].is_a(), material=self.material_sets[key])


def write_ifc(elements, filepath, options=None, progress=None, log=print):
    """Пишет IFC-файл. progress(i, n) -> False прерывает. Возвращает статистику."""
    t0 = time.time()
    w = _Writer(options, log)
    # owner.settings — глобальные; сохраняем и восстанавливаем после записи
    saved = (ifcopenshell.api.owner.settings.get_user, ifcopenshell.api.owner.settings.get_application)
    try:
        return _write(w, elements, filepath, progress, t0)
    finally:
        ifcopenshell.api.owner.settings.get_user, ifcopenshell.api.owner.settings.get_application = saved


def _write(w, elements, filepath, progress, t0):
    w.create_project()
    n = len(elements)
    for i, el in enumerate(elements):
        w.add_element(el)
        if progress and (i % 50 == 0 or i == n - 1):
            if progress(i + 1, n) is False:
                raise RuntimeError("Export cancelled")
    w.finalize()
    if filepath:
        w.f.write(filepath)
    return {
        "file": filepath,
        "ifc": w.f,
        "elements": n,
        "assemblies": len(w.assemblies),
        "storeys": len(w.storeys),
        "styles": len(w.styles),
        "materials": len(w.materials),
        "warnings": w.warnings,
        "seconds": round(time.time() - t0, 2),
    }
