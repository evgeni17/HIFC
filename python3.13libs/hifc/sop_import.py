# SPDX-FileCopyrightText: 2026 EOK
# SPDX-License-Identifier: Apache-2.0
"""SOP-слой импорта: IFC -> геометрия Houdini.

Вызывается из Python SOP внутри HDA hifc::ifc_import:
    import hifc.sop_import as m; m.cook(hou.pwd())
Параметры читаются с HDA (родителя Python SOP) или с самого узла, если он используется напрямую.
"""
import json
import os
import re

import hou
import numpy as np

from . import ensure_vendor_path

ensure_vendor_path()

# кэш прочитанных файлов: ключ -> список записей (переживает перекуки)
_CACHE = {}
_CACHE_MAX = 3


def _owner(node):
    """Узел, на котором висят параметры (HDA или сам Python SOP)."""
    p = node.parent()
    if p is not None and p.type().name().startswith("hifc::ifc_import"):
        return p
    return node


def _ev(owner, name, default):
    p = owner.parm(name)
    if p is None:
        return default
    try:
        return p.evalAsString() if isinstance(default, str) else type(default)(p.eval())
    except Exception:
        return default


def _classes(s):
    return [c for c in re.split(r"[\s,;]+", s or "") if c]


def clear_cache(kwargs=None):
    _CACHE.clear()
    if kwargs and kwargs.get("node") is not None:
        n = kwargs["node"]
        inner = n.node("IFC_READ") or n
        inner.cook(force=True)


def _cache_file(key):
    import hashlib
    d = os.path.join(hou.text.expandString("$HOUDINI_TEMP_DIR"), "hifc_cache")
    return os.path.join(d, hashlib.sha1(repr(key).encode("utf-8")).hexdigest() + ".pkl")


def _load(path, include, exclude, path_mode, psets, threads, pset_names=None, disk_cache=True):
    """Записи элементов: кэш в памяти -> дисковый кэш ($HOUDINI_TEMP_DIR/hifc_cache) -> чтение IFC."""
    import pickle
    from . import __version__, ifc_read

    st = os.stat(path)
    key = (__version__, path, st.st_mtime, st.st_size, tuple(include), tuple(exclude), path_mode, psets,
           tuple(pset_names or ()))
    recs = _CACHE.get(key)
    if recs is None and disk_cache:
        cf = _cache_file(key)
        if os.path.exists(cf):
            try:
                with open(cf, "rb") as fh:
                    recs = pickle.load(fh)
            except Exception:
                recs = None
    if recs is None:
        with hou.InterruptableOperation("HIFC: reading IFC", open_interrupt_dialog=True) as op:
            def progress(i, n):
                op.updateProgress(min(1.0, float(i) / max(1, n)))
            recs = ifc_read.uniquify_paths(list(ifc_read.iter_ifc(
                path, include=include or None, exclude=exclude, path_mode=path_mode,
                psets=psets, threads=threads, progress=progress, pset_names=pset_names)))
        if disk_cache:
            try:
                cf = _cache_file(key)
                os.makedirs(os.path.dirname(cf), exist_ok=True)
                with open(cf + ".tmp", "wb") as fh:
                    pickle.dump(recs, fh, protocol=pickle.HIGHEST_PROTOCOL)
                os.replace(cf + ".tmp", cf)
            except Exception:
                pass
    if len(_CACHE) >= _CACHE_MAX and key not in _CACHE:
        _CACHE.pop(next(iter(_CACHE)))
    _CACHE[key] = recs
    return recs


def clear_disk_cache(kwargs=None):
    import shutil
    d = os.path.join(hou.text.expandString("$HOUDINI_TEMP_DIR"), "hifc_cache")
    shutil.rmtree(d, ignore_errors=True)
    _CACHE.clear()
    if kwargs and kwargs.get("node") is not None:
        inner = kwargs["node"].node("IFC_READ") or kwargs["node"]
        inner.cook(force=True)


def _to_houdini(v, y_up, scale):
    """IFC (Z вверх, метры) -> Houdini (Y вверх, единицы сцены)."""
    v = np.asarray(v, dtype=np.float64)
    if y_up:
        v = np.column_stack((v[:, 0], v[:, 2], -v[:, 1]))
    return v * scale


def _face_colors(rec):
    """Цвет (RGBA) каждого треугольника."""
    fs = rec["face_style"]
    styles = rec["styles"]
    pal = np.array([s[1] for s in styles] + [(0.8, 0.8, 0.8, 1.0)], dtype=np.float32)
    idx = np.where((fs >= 0) & (fs < len(styles)), fs, len(styles))
    return pal[idx]


def _face_style_names(rec):
    names = [s[0] for s in rec["styles"]] + [""]
    fs = rec["face_style"]
    return [names[i] if 0 <= i < len(rec["styles"]) else "" for i in fs]


def _build_mesh(geo, verts, faces):
    """Быстрое создание треугольников: точки + P одним буфером, затем полигоны."""
    n = len(verts)
    if n == 0 or len(faces) == 0:
        return 0
    base = geo.intrinsicValue("pointcount")
    pts = geo.createPoints([(0.0, 0.0, 0.0)] * n)
    if base == 0:
        geo.setPointFloatAttribValuesFromString("P", np.ascontiguousarray(verts, dtype=np.float32).tobytes())
    else:
        for p, xyz in zip(pts, verts.tolist()):
            p.setPosition(xyz)
    # Houdini: лицевая сторона — по часовой, IFC — против: разворачиваем порядок
    polys = (faces[:, ::-1] + base).tolist()
    geo.createPolygons(polys)
    return len(faces)


def _prim_string_attr(geo, name, values):
    if geo.findPrimAttrib(name) is None:
        geo.addAttrib(hou.attribType.Prim, name, "")
    geo.setPrimStringAttribValues(name, values)


def _prim_int_attr(geo, name, values):
    if geo.findPrimAttrib(name) is None:
        geo.addAttrib(hou.attribType.Prim, name, 0)
    geo.setPrimIntAttribValuesFromString(name, np.asarray(values, dtype=np.int32).tobytes())


def _prim_float_attr(geo, name, values, size=1, default=0.0):
    if geo.findPrimAttrib(name) is None:
        geo.addAttrib(hou.attribType.Prim, name, (default,) * size if size > 1 else default)
    geo.setPrimFloatAttribValuesFromString(name, np.asarray(values, dtype=np.float32).tobytes())


def _prim_dict_attr(geo, name, values):
    if geo.findPrimAttrib(name) is None:
        geo.addAttrib(hou.attribType.Prim, name, {})
    setter = getattr(geo, "setPrimDictAttribValues", None)
    if setter is not None:
        try:
            setter(name, values)
            return
        except Exception:
            pass
    for prim, v in zip(geo.prims(), values):
        prim.setAttribValue(name, v)


def _flat_name(pset, prop):
    s = re.sub(r"[^A-Za-z0-9_]", "_", "%s_%s" % (pset, prop))
    return ("_" + s) if s[:1].isdigit() else s


REC_STR_ATTRS = (
    ("path", "path"), ("ifc_guid", "guid"), ("ifc_class", "ifc_class"), ("ifc_predefined", "predefined"),
    ("ifc_name", "name"), ("ifc_storey", "storey"), ("ifc_type", "type_name"),
    ("ifc_object_type", "object_type"), ("ifc_tag", "tag"), ("ifc_description", "description"),
)


def _prim_string_array_attr(geo, name, values):
    """Строковый массив на примитив (s[]@...)."""
    if geo.findPrimAttrib(name) is None:
        geo.addArrayAttrib(hou.attribType.Prim, name, hou.attribData.String)
    for prim, v in zip(geo.iterPrims(), values):
        prim.setAttribValue(name, tuple(v))


def cook(node):
    owner = _owner(node)
    geo = node.geometry()
    geo.clear()
    path = _ev(owner, "file", "")
    if not path:
        return
    path = hou.text.expandString(path)
    if not os.path.isfile(path):
        raise hou.NodeError("IFC file not found: %s" % path)

    include = _classes(_ev(owner, "include", ""))
    exclude = _classes(_ev(owner, "exclude", "IfcOpeningElement IfcSpace IfcVirtualElement"))
    path_mode = "full" if _ev(owner, "pathmode", 0) == 1 else "elements"
    packed = _ev(owner, "output", 0) == 0
    y_up = bool(_ev(owner, "yup", 1))
    scale = float(_ev(owner, "scale", 1.0))
    want_psets = bool(_ev(owner, "psets", 1))
    flatten = bool(_ev(owner, "flatten", 0))
    want_color = bool(_ev(owner, "color", 1))
    threads = int(_ev(owner, "threads", 0))

    pset_names = [p for p in re.split(r"[\s,;]+", _ev(owner, "psetfilter", "*")) if p]
    if pset_names == ["*"]:
        pset_names = None
    disk_cache = bool(_ev(owner, "diskcache", 1))
    recs = _load(path, include, exclude, path_mode, want_psets, threads, pset_names, disk_cache)

    # элементы и их атрибуты пишем один раз на packed-примитив; режим Polygons — это Unpack,
    # который копирует атрибуты в C++ (раньше словари писались по одному на каждый треугольник)
    pk = geo if packed else hou.Geometry()
    _cook_packed(pk, recs, y_up, scale, want_color)

    for attr, key in REC_STR_ATTRS:
        _prim_string_attr(pk, attr, [r[key] for r in recs])
    _prim_int_attr(pk, "ifc_id", [r["id"] for r in recs])
    # один материал -> s@ifc_material; полный список (наборы материалов) -> s[]@ifc_materials
    _prim_string_attr(pk, "ifc_material", [r["materials"][0] if len(r["materials"]) == 1 else "" for r in recs])
    if any(len(r["materials"]) > 1 for r in recs):
        _prim_string_array_attr(pk, "ifc_materials", [r["materials"] for r in recs])
    if want_psets:
        _prim_dict_attr(pk, "ifc_psets", [r["psets"] for r in recs])
        # какие свойства — длины/площади/объёмы в СИ (нужно экспорту для пересчёта единиц)
        _prim_dict_attr(pk, "ifc_measures", [r.get("measures") or {} for r in recs])
        if flatten:
            _flatten_psets(pk, recs, lambda v: v)

    if not packed:
        verb = hou.sopNodeTypeCategory().nodeVerbs()["unpack"]
        # цвет packed-примитива (первая грань) не должен затирать цвета граней внутри
        verb.setParms({"transfer_attributes": "* ^Cd ^Alpha ^ifc_style"})
        verb.execute(geo, [pk])

    # сводка в detail-атрибутах
    geo.addAttrib(hou.attribType.Global, "ifc_file", "")
    geo.setGlobalAttribValue("ifc_file", path)
    geo.addAttrib(hou.attribType.Global, "ifc_elements", 0)
    geo.setGlobalAttribValue("ifc_elements", len(recs))


def _flatten_psets(geo, recs, rep):
    cols = {}
    for i, r in enumerate(recs):
        for pn, props in r["psets"].items():
            for k, v in props.items():
                cols.setdefault(_flat_name(pn, k), {})[i] = v
    for name, vals in cols.items():
        sample = next(iter(vals.values()))
        if isinstance(sample, (int, float, bool)) and all(isinstance(v, (int, float, bool)) or v is None for v in vals.values()):
            _prim_float_attr(geo, name, rep([float(vals.get(i) or 0.0) for i in range(len(recs))]))
        else:
            _prim_string_attr(geo, name, rep(["" if vals.get(i) is None else str(vals.get(i)) for i in range(len(recs))]))


def _cook_packed(geo, recs, y_up, scale, want_color):
    """Один packed-примитив на элемент (как объект Blender у Bonsai); pivot — центр bbox."""
    first_colors = []
    for r in recs:
        v = _to_houdini(r["verts"], y_up, scale)
        sub = hou.Geometry()
        center = (v.min(axis=0) + v.max(axis=0)) * 0.5 if len(v) else np.zeros(3)
        _build_mesh(sub, v - center, r["faces"])
        if want_color and len(r["faces"]):
            c = _face_colors(r)
            _prim_float_attr(sub, "Cd", c[:, :3], 3)
            # Alpha пишем всегда (по умолчанию 1): иначе при Unpack/Merge непрозрачные элементы получают 0
            _prim_float_attr(sub, "Alpha", c[:, 3], default=1.0)
            _prim_string_attr(sub, "ifc_style", _face_style_names(r))
            first_colors.append(c[0, :3])
        else:
            first_colors.append(np.array([0.8, 0.8, 0.8], dtype=np.float32))
        pt = geo.createPoint()
        pt.setPosition(center.tolist())
        geo.createPackedGeometry(sub.freeze(True), pt)
    if want_color and first_colors:
        _prim_float_attr(geo, "Cd", np.array(first_colors), 3)


def info_text(kwargs):
    """Кнопка Info: сводка по файлу."""
    from . import ifc_read
    node = kwargs["node"]
    path = hou.text.expandString(node.parm("file").evalAsString())
    try:
        i = ifc_read.file_info(path)
        msg = json.dumps(i, indent=2, ensure_ascii=False)
    except Exception as ex:
        msg = "Error: %s" % ex
    hou.ui.displayMessage(msg, title="HIFC: IFC info")
