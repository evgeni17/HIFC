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
        "verts":      ndarray(N,3) — метры, ЛОКАЛЬНЫЕ координаты элемента (IFC, Z вверх),
        "matrix":     ndarray(4,4) — размещение элемента в мире (метры),
        "geom_id":    идентификатор геометрии IfcOpenShell: одинаковый у повторяющихся элементов
                      (окна, двери, мебель) — по нему делается инстансинг,
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


_SPATIAL_CACHE = {}


def _is_spatial(e):
    # кэш по классу: проверка через схему дорогая, а классов в файле немного
    k = (e.is_a(), id(e.wrapped_data.declaration().schema()) if hasattr(e, "wrapped_data") else 0)
    v = _SPATIAL_CACHE.get(k)
    if v is None:
        v = _SPATIAL_CACHE[k] = any(e.is_a(c) for c in SPATIAL_ROOTS if _schema_has(e, c))
    return v


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


def _simple_value(v):
    if v is None:
        return None
    if isinstance(v, (list, tuple)):
        return ", ".join(str(_simple_value(x)) for x in v)
    if hasattr(v, "wrappedValue"):
        return v.wrappedValue
    return v


def _read_props(props_list, scales, props, kinds, prefix="", skipped=None, depth=0):
    """Список IfcProperty -> props/kinds. Вложенные IfcComplexProperty разворачиваются в «Родитель.Свойство».

    Доступ к атрибутам по индексам (быстрее, чем по имени): это самая горячая функция импорта.
    IfcPropertySingleValue: 0 Name, 2 NominalValue, 3 Unit; IfcComplexProperty: 0 Name, 2 UsageName, 3 HasProperties.
    """
    for p in props_list or ():
        pcls = p.is_a()
        kind = None
        if pcls == "IfcPropertySingleValue":
            nv = p[2]
            if nv is None:
                v = None
            else:
                v = nv.wrappedValue
                kind = MEASURE_KIND.get(nv.is_a())
        elif pcls == "IfcPropertyEnumeratedValue":
            v = _simple_value(p[2])
        elif pcls == "IfcPropertyListValue":
            v = _simple_value(p[2])
        elif pcls == "IfcPropertyBoundedValue":
            v = "%s..%s" % (_simple_value(p[3]), _simple_value(p[2]))
        elif pcls == "IfcComplexProperty":
            if depth < MAX_PROP_DEPTH:
                _read_props(p[3], scales, props, kinds, prefix + (p[0] or "") + ".", skipped, depth + 1)
            elif skipped is not None:
                skipped[pcls] = skipped.get(pcls, 0) + 1
            continue
        else:
            # IfcPropertyTableValue, IfcPropertyReferenceValue и прочие структурные типы:
            # значения у них не одно число, поэтому в атрибуты Houdini они не переносятся
            if skipped is not None:
                skipped[pcls] = skipped.get(pcls, 0) + 1
            continue
        pname = prefix + (p[0] or "")
        if kind and isinstance(v, (int, float)) and not isinstance(v, bool):
            unit = p[3]
            v = float(v) * (unit_si_scale(unit) if unit is not None else scales.get(kind, 1.0))
            kinds[pname] = kind
        elif kinds:
            kinds.pop(pname, None)
        props[pname] = v


def _read_propdef(d, scales, out, kinds_out, skipped=None):
    """Одно определение свойств (IfcPropertySet / IfcElementQuantity) -> out[name], kinds_out[name]."""
    dcls = d.is_a()
    name = d[2] or dcls
    props, kinds = out.setdefault(name, {}), kinds_out.setdefault(name, {})
    if dcls == "IfcPropertySet":
        _read_props(d[4], scales, props, kinds, "", skipped)
    else:  # IfcElementQuantity: 0 Name, 2 Unit, 3 значение у IfcPhysicalSimpleQuantity
        for q in d[5] or ():
            qcls = q.is_a()
            kind = QUANTITY_KIND.get(qcls)
            if kind is None and not q.is_a("IfcPhysicalSimpleQuantity"):
                if skipped is not None:
                    skipped[qcls] = skipped.get(qcls, 0) + 1
                continue
            v = q[3]
            if kind and isinstance(v, (int, float)):
                u = q[2]
                v = float(v) * (unit_si_scale(u) if u is not None else scales.get(kind, 1.0))
                kinds[q[0]] = kind
            props[q[0]] = v
    if not kinds:
        kinds_out.pop(name, None)


def _defs_of(obj):
    """Определения свойств объекта (occurrence) или типа."""
    if obj.is_a("IfcTypeObject"):
        return list(obj.HasPropertySets or ())
    out = []
    for rel in getattr(obj, "IsDefinedBy", None) or ():
        if rel.is_a("IfcRelDefinesByProperties"):
            d = rel.RelatingPropertyDefinition
            out.extend(d if isinstance(d, (list, tuple)) else [d])
    return out


_PSET_CLASSES = ("IfcPropertySet", "IfcElementQuantity")
MAX_PROP_DEPTH = 4   # глубина разворачивания IfcComplexProperty


class _PsetReader:
    """Быстрое чтение наборов свойств с кэшем по типам (у многих элементов один тип)."""

    def __init__(self, scales, names=None):
        self.scales = scales
        self.type_cache = {}
        self.skipped = {}          # тип свойства IFC -> сколько раз пропущен
        self.names = [n for n in (names or ()) if n]  # маски имён наборов; пусто = все
        self._name_ok = {}

    def _wanted(self, name):
        if not self.names:
            return True
        ok = self._name_ok.get(name)
        if ok is None:
            import fnmatch
            inc = [p for p in self.names if not p.startswith("^")] or ["*"]
            exc = [p[1:] for p in self.names if p.startswith("^")]
            ok = self._name_ok[name] = (any(fnmatch.fnmatchcase(name, p) for p in inc)
                                        and not any(fnmatch.fnmatchcase(name, p) for p in exc))
        return ok

    def _read(self, obj):
        out, kinds = {}, {}
        for d in _defs_of(obj):
            if d is not None and d.is_a() in _PSET_CLASSES and self._wanted(d[2] or ""):
                _read_propdef(d, self.scales, out, kinds, self.skipped)
        return out, kinds

    def read(self, e):
        psets, measures = {}, {}
        t = ue.get_type(e)
        if t is not None:
            c = self.type_cache.get(t.id())
            if c is None:
                c = self.type_cache[t.id()] = self._read(t)
            for k, v in c[0].items():
                psets[k] = dict(v)
            for k, v in c[1].items():
                measures[k] = dict(v)
        o_ps, o_ms = self._read(e)
        for k, v in o_ps.items():
            psets.setdefault(k, {}).update(v)
            own = o_ms.get(k) or {}
            inherited = measures.get(k)
            if inherited:
                # всё, что экземпляр перекрыл своим значением, теряет унаследованную пометку единиц:
                # у типа свойство могло быть длиной, а у экземпляра — обычным числом
                for pk in v:
                    if pk not in own:
                        inherited.pop(pk, None)
            if own:
                measures.setdefault(k, {}).update(own)
            if k in measures and not measures[k]:
                measures.pop(k)
        return {k: v for k, v in psets.items() if v}, measures


def _element_psets_slow(f, e, scales):
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
             psets=True, threads=0, progress=None, pset_names=None, stats=None):
    """Генератор элементов. include/exclude — списки имён классов IFC.

    stats: словарь вызывающего; по ходу чтения в него кладётся "skipped_properties"
    (тип свойства IFC -> сколько раз пропущен), чтобы нода могла показать предупреждение.

    path_mode: "elements" — путь от первой непространственной сборки (для экспорта обратно);
               "full"     — полный путь от IfcProject.
    """
    f = ifcopenshell.open(filepath)
    settings = ifcopenshell.geom.settings()
    # локальные координаты + матрица: так у повторяющейся геометрии совпадает geometry.id
    # и её можно один раз положить в память, а элементы расставить копиями
    settings.set("use-world-coords", False)
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
    pset_reader = _PsetReader(scales, pset_names)
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
            "matrix": us.get_shape_matrix(shape),
            "geom_id": g.id,
            "faces": us.get_faces(g).copy(),
            "face_style": us.get_faces_material_style_ids(g).copy(),
            "styles": styles,
        }
        t = ue.get_type(e)
        if t is not None:
            rec["type_name"] = t.Name or ""
        if psets:
            rec["psets"], rec["measures"] = pset_reader.read(e)
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
        if stats is not None and pset_reader.skipped:
            stats["skipped_properties"] = dict(pset_reader.skipped)
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


def world_verts(rec):
    """Мировые координаты элемента (метры, IFC-оси).

    einsum, а не `v @ m.T`: на macOS/arm64 путь через BLAS поднимает ложные флаги
    divide-by-zero/overflow на совершенно нормальных матрицах поворота. Результат совпадает побитово.
    """
    m = rec.get("matrix")
    v = rec["verts"]
    if m is None or not len(v):
        return v
    return np.einsum("ij,kj->ik", v, np.asarray(m[:3, :3])) + np.asarray(m[:3, 3])


def read_ifc(filepath, **kw):
    t0 = time.time()
    recs = uniquify_paths(list(iter_ifc(filepath, **kw)))
    return recs, round(time.time() - t0, 2)
