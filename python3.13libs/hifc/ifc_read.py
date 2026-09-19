# SPDX-FileCopyrightText: 2026 EOK
# SPDX-License-Identifier: Apache-2.0
"""Чтение IFC в нейтральное описание элементов (без зависимости от hou).

Каждый элемент:
    {
        "id": step id, "guid", "ifc_class", "predefined", "name", "object_type", "tag",
        "type_name":  имя IfcTypeObject (если есть),
        "path":       "/Assembly/Element" или "/Project/Site/.../Element",
        "storey":     имя ближайшего пространственного контейнера,
        "psets":      {"Pset": {"prop": value}},   # длины/площади/объёмы — в СИ (м, м², м³)
        "measures":   {"Pset": {"prop": "LENGTH"|"AREA"|"VOLUME"}},  # какие значения пересчитаны в СИ
        "materials":  [имена IfcMaterial],
        "verts":      ndarray(N,3) — метры, мировые координаты IFC (Z вверх),
        "faces":      ndarray(M,3) — треугольники (CCW),
        "face_style": ndarray(M)   — индекс в styles (-1 = без стиля),
        "styles":     [(name, (r, g, b, a))],
    }
"""
import multiprocessing
import os
import re
import time

import numpy as np

import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.util.element as ue
import ifcopenshell.util.shape as us
import ifcopenshell.util.unit

SPATIAL_ROOTS = ("IfcProject", "IfcSpatialStructureElement", "IfcSpatialElement", "IfcFacility", "IfcFacilityPart")
DEFAULT_EXCLUDE = ("IfcOpeningElement", "IfcSpace", "IfcVirtualElement")

_bad = re.compile(r"[/\\]+")


def _seg(e):
    n = (getattr(e, "Name", None) or "").strip()
    return _bad.sub("_", n) if n else "%s_%d" % (e.is_a(), e.id())


def _is_spatial(e):
    return any(e.is_a(c) for c in SPATIAL_ROOTS if _schema_has(e, c))


def _schema_has(e, cls):
    try:
        return e.wrapped_data.declaration().schema().declaration_by_name(cls) is not None
    except Exception:
        return cls in ("IfcProject", "IfcSpatialStructureElement")


def _parent(e):
    """Родитель в дереве декомпозиции: агрегат, вложение (nest) или контейнер."""
    p = ue.get_aggregate(e)
    if p is None:
        p = ue.get_nest(e)
    if p is None and not _is_spatial(e):
        p = ue.get_container(e)
    if p is None and e.is_a("IfcFeatureElementSubtraction"):
        try:
            p = e.VoidsElements[0].RelatingBuildingElement
        except Exception:
            p = None
    return p


class _Chain:
    def __init__(self):
        self.cache = {}

    def chain(self, e):
        """Список предков от корня до e включительно."""
        k = e.id()
        c = self.cache.get(k)
        if c is None:
            p = _parent(e)
            c = (self.chain(p) if p is not None else []) + [e]
            self.cache[k] = c
        return c


MEASURE_KIND = {
    "IfcLengthMeasure": "LENGTH", "IfcPositiveLengthMeasure": "LENGTH", "IfcNonNegativeLengthMeasure": "LENGTH",
    "IfcAreaMeasure": "AREA", "IfcVolumeMeasure": "VOLUME",
}
QUANTITY_KIND = {"IfcQuantityLength": "LENGTH", "IfcQuantityArea": "AREA", "IfcQuantityVolume": "VOLUME"}
UNIT_TYPE = {"LENGTH": "LENGTHUNIT", "AREA": "AREAUNIT", "VOLUME": "VOLUMEUNIT"}
_PREFIX = {"EXA": 1e18, "PETA": 1e15, "TERA": 1e12, "GIGA": 1e9, "MEGA": 1e6, "KILO": 1e3, "HECTO": 1e2,
           "DECA": 1e1, "DECI": 1e-1, "CENTI": 1e-2, "MILLI": 1e-3, "MICRO": 1e-6, "NANO": 1e-9,
           "PICO": 1e-12, "FEMTO": 1e-15, "ATTO": 1e-18}


def unit_si_scale(u):
    """Множитель перевода единицы IfcNamedUnit в СИ (м, м², м³)."""
    try:
        if u.is_a("IfcSIUnit"):
            m = _PREFIX.get(u.Prefix, 1.0) if u.Prefix else 1.0
            dim = 2 if u.Name == "SQUARE_METRE" else 3 if u.Name == "CUBIC_METRE" else 1
            return m ** dim
        if u.is_a("IfcConversionBasedUnit"):
            cf = u.ConversionFactor
            return float(cf.ValueComponent.wrappedValue) * unit_si_scale(cf.UnitComponent)
    except Exception:
        pass
    return 1.0


def _project_scales(f):
    out = {}
    for kind, ut in UNIT_TYPE.items():
        try:
            out[kind] = ifcopenshell.util.unit.calculate_unit_scale(f, ut)
        except Exception:
            out[kind] = 1.0
    return out


def _element_psets(f, e, scales):
    """Наборы свойств + пересчёт измеряемых величин в СИ. Возвращает (psets, measures)."""
    psets, measures = {}, {}
    raw = ue.get_psets(e, verbose=True)
    for pname, props in raw.items():
        clean, kinds = {}, {}
        for k, pv in props.items():
            if k == "id" or not isinstance(pv, dict):
                continue
            v = pv.get("value")
            kind = None
            try:
                ent = f.by_id(pv["id"])
            except Exception:
                ent = None
            if ent is not None and isinstance(v, (int, float)) and not isinstance(v, bool):
                unit = None
                if ent.is_a() in QUANTITY_KIND:
                    kind = QUANTITY_KIND[ent.is_a()]
                    unit = getattr(ent, "Unit", None)
                elif ent.is_a("IfcPropertySingleValue") and ent.NominalValue is not None:
                    kind = MEASURE_KIND.get(ent.NominalValue.is_a())
                    unit = ent.Unit
                if kind:
                    # явная единица свойства важнее единицы проекта
                    sc = unit_si_scale(unit) if unit is not None else scales.get(kind, 1.0)
                    v = float(v) * sc
                    kinds[k] = kind
            if isinstance(v, (list, tuple)):
                v = ", ".join(str(x) for x in v)
            elif v is not None and not isinstance(v, (int, float, str, bool)):
                v = str(v)
            clean[k] = v
        psets[pname] = clean
        if kinds:
            measures[pname] = kinds
    return psets, measures


def _clean_psets(d):
    out = {}
    for pname, props in (d or {}).items():
        clean = {}
        for k, v in props.items():
            if k == "id":
                continue
            if isinstance(v, (list, tuple)):
                v = ", ".join(str(x) for x in v)
            elif v is not None and not isinstance(v, (int, float, str, bool)):
                v = str(v)
            clean[k] = v
        out[pname] = clean
    return out


def iter_ifc(filepath, include=None, exclude=DEFAULT_EXCLUDE, path_mode="elements",
             psets=True, threads=0, progress=None):
    """Генератор элементов. include/exclude — списки имён классов IFC.

    path_mode: "elements" — путь от первой непространственной сборки (для экспорта обратно);
               "full"     — полный путь от IfcProject.
    """
    f = ifcopenshell.open(filepath)
    settings = ifcopenshell.geom.settings()
    settings.set("use-world-coords", True)
    settings.set("weld-vertices", True)
    settings.set("apply-default-materials", True)
    try:
        settings.set("no-normals", True)
    except Exception:
        pass

    kw = {}
    if include:
        kw["include"] = [e for c in include for e in _by_type(f, c)]
    elif exclude:
        kw["exclude"] = [e for c in exclude for e in _by_type(f, c)]
    threads = threads or max(1, multiprocessing.cpu_count() - 1)
    it = ifcopenshell.geom.iterator(settings, f, threads, **kw)
    chainer = _Chain()
    scales = _project_scales(f)
    total = len(f.by_type("IfcProduct"))
    n = 0
    if not it.initialize():
        return
    while True:
        shape = it.get()
        e = f.by_id(shape.id)
        g = shape.geometry
        chain = chainer.chain(e)
        storey, storey_class = None, ""
        for a in reversed(chain[:-1]):
            if _is_spatial(a):
                storey, storey_class = _seg(a), a.is_a()
                break
        if path_mode == "full":
            segs = [_seg(a) for a in chain]
        else:
            # сам элемент — всегда последний сегмент, даже если он пространственный (IfcRoadPart с геометрией)
            segs = [_seg(a) for a in chain[:-1] if not _is_spatial(a)] + [_seg(e)]
        styles = []
        for i, m in enumerate(g.materials):
            # имя берём у исходного IfcSurfaceStyle (m.name — служебное)
            nm = ""
            try:
                sid = m.instance_id()
                nm = (f.by_id(sid).Name or "") if sid else ""
            except Exception:
                pass
            styles.append((nm, None))
        cols = us.get_material_colors(g)
        styles = [(styles[i][0], tuple(float(x) for x in cols[i])) if i < len(cols) else (styles[i][0], (0.8, 0.8, 0.8, 1.0))
                  for i in range(len(styles))]
        rec = {
            "id": e.id(),
            "guid": getattr(e, "GlobalId", "") or "",
            "ifc_class": e.is_a(),
            # только собственный PredefinedType элемента (тип из IfcTypeObject сюда не подмешиваем)
            "predefined": (getattr(e, "PredefinedType", None) or "") if hasattr(e, "PredefinedType") else "",
            "name": getattr(e, "Name", "") or "",
            "object_type": getattr(e, "ObjectType", "") or "",
            "tag": getattr(e, "Tag", "") or "",
            "description": getattr(e, "Description", "") or "",
            "type_name": "",
            "path": "/" + "/".join(segs),
            "storey": storey or "",
            "storey_class": storey_class,
            "psets": {},
            "measures": {},
            "materials": [],
            "verts": us.get_vertices(g).copy(),
            "faces": us.get_faces(g).copy(),
            "face_style": us.get_faces_material_style_ids(g).copy(),
            "styles": styles,
        }
        t = ue.get_type(e)
        if t is not None:
            rec["type_name"] = t.Name or ""
        if psets:
            rec["psets"], rec["measures"] = _element_psets(f, e, scales)
            try:
                mats = ue.get_materials(e)
                rec["materials"] = [m.Name for m in mats if getattr(m, "Name", None)]
            except Exception:
                pass
        n += 1
        if progress and n % 50 == 0:
            if progress(n, total) is False:
                return
        yield rec
        if not it.next():
            break


def _by_type(f, cls):
    try:
        return f.by_type(cls)
    except Exception:
        return []


def uniquify_paths(records):
    """Делает path уникальным: дубли имён получают суффикс из GUID (стабилен между экспортами)."""
    seen = {}
    for r in records:
        seen.setdefault(r["path"], []).append(r)
    for p, rs in seen.items():
        if len(rs) > 1:
            for r in rs:
                sfx = re.sub(r"[^A-Za-z0-9]", "_", r["guid"][-8:]) if r["guid"] else str(r["id"])
                r["path"] = "%s_%s" % (p, sfx)
    return records


def file_info(filepath):
    f = ifcopenshell.open(filepath)
    proj = f.by_type("IfcProject")
    return {
        "schema": f.schema,
        "project": (proj[0].Name if proj else "") or "",
        "unit_scale": ifcopenshell.util.unit.calculate_unit_scale(f),
        "products": len(f.by_type("IfcProduct")),
        "storeys": [s.Name for s in f.by_type("IfcBuildingStorey")],
        "size_mb": round(os.path.getsize(filepath) / 1e6, 2),
    }


def read_ifc(filepath, **kw):
    t0 = time.time()
    recs = uniquify_paths(list(iter_ifc(filepath, **kw)))
    return recs, round(time.time() - t0, 2)
