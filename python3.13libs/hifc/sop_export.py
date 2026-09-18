# SPDX-FileCopyrightText: 2026 EOK
# SPDX-License-Identifier: Apache-2.0
"""SOP-слой экспорта: геометрия Houdini -> IFC.

Кнопка Export на HDA hifc::ifc_export вызывает export_node(kwargs).
Группировка: один IFC-элемент на уникальное значение атрибута пути (по умолчанию s@path).
Промежуточные сегменты пути -> IfcElementAssembly, последний сегмент -> элемент.
"""
import fnmatch
import os
import re

import hou
import numpy as np

from . import ensure_vendor_path

ensure_vendor_path()


def _ev(node, name, default):
    p = node.parm(name)
    if p is None:
        return default
    try:
        return p.evalAsString() if isinstance(default, str) else type(default)(p.eval())
    except Exception:
        return default


def _source_geo(node):
    """Геометрия для экспорта: внутренний Unpack (раскрывает packed), иначе вход."""
    inner = node.node("UNPACK")
    if inner is not None:
        return inner.geometry()
    if node.inputs() and node.inputs()[0] is not None:
        return node.inputs()[0].geometry()
    return node.geometry()


def _prim_strings(geo, name):
    a = geo.findPrimAttrib(name) if name else None
    if a is None or a.dataType() != hou.attribData.String:
        return None
    return geo.primStringAttribValues(name)


def _prim_values(geo, name):
    """Значения prim-атрибута любого типа (кортежами для векторов)."""
    a = geo.findPrimAttrib(name)
    if a is None:
        return None
    dt, size = a.dataType(), a.size()
    if dt == hou.attribData.String:
        return list(geo.primStringAttribValues(name))
    if dt == hou.attribData.Float:
        v = geo.primFloatAttribValues(name)
    elif dt == hou.attribData.Int:
        v = geo.primIntAttribValues(name)
    elif dt == hou.attribData.Dict:
        getter = getattr(geo, "primDictAttribValues", None)
        return list(getter(name)) if getter else [p.attribValue(name) for p in geo.prims()]
    else:
        return None
    if size == 1:
        return list(v)
    return [tuple(v[i:i + size]) for i in range(0, len(v), size)]


def _class_rules(node):
    """Правила из мультипарма: (маска, класс, PredefinedType)."""
    rules = []
    n = _ev(node, "rules", 0)
    for i in range(1, n + 1):
        pat = _ev(node, "rule_pattern%d" % i, "").strip()
        cls = _ev(node, "rule_class%d" % i, "").strip()
        pt = _ev(node, "rule_predefined%d" % i, "").strip()
        if pat and cls:
            rules.append((pat, cls, pt))
    return rules


def _match_rule(rules, leaf, full):
    for pat, cls, pt in rules:
        if fnmatch.fnmatchcase(leaf, pat) or fnmatch.fnmatchcase(full, pat):
            return cls, pt
    return None, None


def _prim_point_lists(geo):
    """Списки номеров точек для каждого примитива (только полигоны)."""
    out = []
    for p in geo.iterPrims():
        if p.type() == hou.primType.Polygon:
            out.append([v.point().number() for v in p.vertices()])
        else:
            out.append(None)
    return out


def collect_elements(node, geo, log=None):
    """Собирает элементы для ifc_write.write_ifc из геометрии SOP."""
    path_attr = _ev(node, "pathattrib", "path")
    skip = _ev(node, "skipsegments", 0)
    y_up = bool(_ev(node, "yup", 1))
    scale = float(_ev(node, "scale", 1.0))  # метров в единице сцены
    rules = _class_rules(node)

    paths = _prim_strings(geo, path_attr)
    if paths is None:
        paths = _prim_strings(geo, "name")
    npr = geo.intrinsicValue("primitivecount")
    if paths is None:
        paths = ["/Element"] * npr

    def s_attr(parm, default_name):
        return _prim_strings(geo, _ev(node, parm, default_name))

    cls_v = s_attr("classattrib", "ifc_class")
    pt_v = s_attr("predefattrib", "ifc_predefined")
    guid_v = s_attr("guidattrib", "ifc_guid")
    storey_v = s_attr("storeyattrib", "ifc_storey")
    mat_v = s_attr("materialattrib", "ifc_material")
    name_v = s_attr("nameattrib", "ifc_name")
    style_v = s_attr("styleattrib", "ifc_style")
    tag_v = s_attr("tagattrib", "ifc_tag")
    desc_v = s_attr("descattrib", "ifc_description")
    otype_v = s_attr("objtypeattrib", "ifc_object_type")
    cd = geo.primFloatAttribValues("Cd") if (_ev(node, "color", 1) and geo.findPrimAttrib("Cd")) else None
    alpha = geo.primFloatAttribValues("Alpha") if (cd is not None and geo.findPrimAttrib("Alpha")) else None
    pcd = None
    if cd is None and _ev(node, "color", 1) and geo.findPointAttrib("Cd"):
        pcd = np.frombuffer(geo.pointFloatAttribValuesAsString("Cd"), dtype=np.float32).reshape(-1, 3)

    # psets
    pset_name = _ev(node, "psetname", "HoudiniAttributes")
    pat = _ev(node, "psetattribs", "").split()
    pset_attrs = []
    if pat:
        for a in geo.primAttribs():
            n = a.name()
            if any(fnmatch.fnmatchcase(n, p) for p in pat) and n not in (path_attr, "Cd", "Alpha"):
                pset_attrs.append(n)
    pset_vals = {n: _prim_values(geo, n) for n in pset_attrs}
    add_path_prop = bool(_ev(node, "pathprop", 1))
    dict_attr = _ev(node, "dictattrib", "ifc_psets")
    dict_vals = _prim_values(geo, dict_attr) if dict_attr and geo.findPrimAttrib(dict_attr) else None

    P = np.frombuffer(geo.pointFloatAttribValuesAsString("P"), dtype=np.float32).reshape(-1, 3).astype(np.float64)
    # Houdini -> IFC: Y вверх -> Z вверх, единицы сцены -> метры
    if y_up:
        P = np.column_stack((P[:, 0], -P[:, 2], P[:, 1]))
    P *= scale
    polys = _prim_point_lists(geo)

    groups = {}
    order = []
    for i in range(npr):
        key = paths[i] or "/Element"
        g = groups.get(key)
        if g is None:
            g = groups[key] = []
            order.append(key)
        g.append(i)

    skipped_prims = 0
    elements = []
    for key in order:
        prims = groups[key]
        i0 = prims[0]
        segs = [s for s in key.replace("\\", "/").split("/") if s]
        segs = segs[skip:] if skip < len(segs) else segs[-1:]
        leaf = segs[-1] if segs else "Element"
        cls = cls_v[i0] if cls_v and cls_v[i0] else None
        pt = pt_v[i0] if pt_v and pt_v[i0] else None
        if not cls:
            cls, rpt = _match_rule(rules, leaf, key)
            pt = pt or rpt

        # геометрия: делим по цвету/стилю на части (одна часть = один IfcStyledItem)
        parts = {}
        for i in prims:
            pl = polys[i]
            if not pl or len(pl) < 3:
                skipped_prims += 1
                continue
            if cd is not None:
                col = (cd[3 * i], cd[3 * i + 1], cd[3 * i + 2], alpha[i] if alpha is not None else 1.0)
            elif pcd is not None:
                c = pcd[pl].mean(axis=0)
                col = (float(c[0]), float(c[1]), float(c[2]), 1.0)
            else:
                col = None
            sname = style_v[i] if style_v else ""
            ck = (sname, None if col is None else tuple(round(x, 4) for x in col))
            parts.setdefault(ck, (col, sname, []))[2].append(pl)

        items = []
        for col, sname, plist in parts.values():
            used = sorted({p for pl in plist for p in pl})
            remap = {p: j for j, p in enumerate(used)}
            # Houdini — по часовой, IFC — против: разворачиваем
            faces = [[remap[p] for p in reversed(pl)] for pl in plist]
            items.append({"verts": P[used], "faces": faces, "color": col, "style": sname or None})

        psets = {}
        if dict_vals is not None and isinstance(dict_vals[i0], dict):
            for pn, props in dict_vals[i0].items():
                if isinstance(props, dict):
                    psets[pn] = dict(props)
        props = {}
        for n in pset_attrs:
            v = pset_vals[n][i0] if pset_vals[n] is not None else None
            if isinstance(v, tuple):
                v = ", ".join("%g" % x for x in v)
            if v is not None:
                props[n] = v
        if add_path_prop:
            props["Houdini_Path"] = key
        if props:
            psets.setdefault(pset_name, {}).update(props)

        elements.append({
            "path": "/" + "/".join(segs),
            "ifc_class": cls,
            "predefined": pt,
            "name": (name_v[i0] if name_v and name_v[i0] else leaf),
            "guid": guid_v[i0] if guid_v else None,
            "storey": storey_v[i0] if storey_v and storey_v[i0] else None,
            "material": mat_v[i0] if mat_v and mat_v[i0] else None,
            "tag": tag_v[i0] if tag_v and tag_v[i0] else None,
            "description": desc_v[i0] if desc_v and desc_v[i0] else None,
            "objecttype": otype_v[i0] if otype_v and otype_v[i0] else None,
            "psets": psets,
            "items": items,
        })
    if log and skipped_prims:
        log("Skipped %d non-polygon primitives (curves/points/volumes)" % skipped_prims)
    return elements


def export_node(kwargs):
    node = kwargs["node"]
    from . import ifc_write

    out = hou.text.expandString(_ev(node, "file", ""))
    if not out:
        raise hou.Error("Set the output IFC file first")
    d = os.path.dirname(out)
    if d and not os.path.isdir(d):
        os.makedirs(d)

    messages = []
    geo = _source_geo(node)
    elements = collect_elements(node, geo, log=messages.append)
    if not elements:
        raise hou.Error("Nothing to export: input has no polygons")

    schema = ["IFC4", "IFC4X3", "IFC2X3"][_ev(node, "schema", 0)]
    opts = {
        "schema": schema,
        "project": _ev(node, "project", "Houdini Project"),
        "site": _ev(node, "site", "Site"),
        "building": _ev(node, "building", "Building"),
        "storey": _ev(node, "storey", "Level 0"),
        "length_unit": ["mm", "cm", "m"][_ev(node, "lengthunit", 0)],
        "origin": ["bbox_bottom", "bbox_center", "world"][_ev(node, "origin", 0)],
        "default_class": _ev(node, "defaultclass", "IfcBuildingElementProxy") or "IfcBuildingElementProxy",
        "assembly_class": _ev(node, "assemblyclass", "IfcElementAssembly") or "IfcElementAssembly",
        "assembly_predefined": _ev(node, "assemblypredef", "NOTDEFINED") or None,
        "guid_seed": _ev(node, "guidseed", ""),
    }
    with hou.InterruptableOperation("HIFC: writing IFC", open_interrupt_dialog=True) as op:
        def progress(i, n):
            op.updateProgress(float(i) / max(1, n))
        st = ifc_write.write_ifc(elements, out, opts, progress=progress)

    report = ["Written: %s" % out,
              "Schema: %s   Elements: %d   Assemblies: %d   Storeys: %d   Styles: %d   Materials: %d   Time: %ss"
              % (schema, st["elements"], st["assemblies"], st["storeys"], st["styles"], st["materials"], st["seconds"])]
    if _ev(node, "validate", 0):
        report.append(_validate(st["ifc"]))
    msgs = messages + st["warnings"]
    if msgs:
        uniq = list(dict.fromkeys(msgs))
        report.append("Warnings (%d):\n  " % len(uniq) + "\n  ".join(uniq[:30]))
    text = "\n".join(report)
    p = node.parm("report")
    if p is not None:
        p.set(text)
    print("[HIFC] " + text)
    if hou.isUIAvailable() and not kwargs.get("silent"):
        hou.ui.setStatusMessage("HIFC: exported %d elements -> %s" % (st["elements"], os.path.basename(out)))
    return st


def _validate(f):
    try:
        import ifcopenshell.validate as v
        logger = v.json_logger()
        v.validate(f, logger)
        n = len(logger.statements)
        if not n:
            return "Validation: OK"
        first = "; ".join(str(s.get("message", ""))[:120] for s in logger.statements[:3])
        return "Validation: %d issue(s): %s" % (n, first)
    except Exception as ex:
        return "Validation skipped: %s" % ex


def open_in_bonsai_hint(kwargs):
    node = kwargs["node"]
    out = hou.text.expandString(_ev(node, "file", ""))
    if out and os.path.exists(out):
        hou.ui.showInFileBrowser(out)


# ---------------------------------------------------------------------------
# Проверка атрибутов перед экспортом (кнопка Check Attributes)
# ---------------------------------------------------------------------------
_SEG_OK = re.compile(r"^[A-Za-z0-9_.\- ]+$")


def check_attributes(node, geo=None):
    """Возвращает (текст отчёта, число проблем). Ничего не пишет на диск."""
    import ifcopenshell
    import ifcopenshell.ifcopenshell_wrapper as w

    geo = geo or _source_geo(node)
    schema_id = {0: "IFC4", 1: "IFC4X3_ADD2", 2: "IFC2X3"}[_ev(node, "schema", 0)]
    schema = w.schema_by_name(schema_id)
    path_attr = _ev(node, "pathattrib", "path")
    npr = geo.intrinsicValue("primitivecount")
    errors, warns, info = [], [], []

    paths = _prim_strings(geo, path_attr)
    if paths is None:
        errors.append("No string prim attribute '%s': every polygon becomes ONE element '/Element'." % path_attr)
        paths = ["/Element"] * npr

    def s(parm, dflt):
        return _prim_strings(geo, _ev(node, parm, dflt))

    cls_v, pt_v, st_v = s("classattrib", "ifc_class"), s("predefattrib", "ifc_predefined"), s("storeyattrib", "ifc_storey")
    guid_v, mat_v = s("guidattrib", "ifc_guid"), s("materialattrib", "ifc_material")
    rules = _class_rules(node)
    dict_attr = _ev(node, "dictattrib", "ifc_psets")
    dict_vals = _prim_values(geo, dict_attr) if dict_attr and geo.findPrimAttrib(dict_attr) else None

    groups = {}
    nonpoly = 0
    for i, p in enumerate(geo.iterPrims()):
        if p.type() != hou.primType.Polygon:
            nonpoly += 1
        groups.setdefault(paths[i] or "", []).append(i)

    if "" in groups:
        errors.append("%d primitives have an EMPTY path." % len(groups[""]))
    if nonpoly:
        a = geo.findPrimAttrib  # noqa
        warns.append("%d non-polygon primitives (packed/curves/volumes). Packed are unpacked by the node; curves are skipped." % nonpoly)

    class_count, bad_class, bad_pt, mixed, bad_seg, no_class = {}, set(), set(), [], set(), 0
    depth = {}
    for key, prims in groups.items():
        segs = [x for x in key.split("/") if x]
        depth[len(segs)] = depth.get(len(segs), 0) + 1
        for sg in segs:
            if not _SEG_OK.match(sg):
                bad_seg.add(sg)
        i0 = prims[0]
        cls = cls_v[i0] if cls_v else ""
        pt = pt_v[i0] if pt_v else ""
        if not cls:
            cls, rpt = _match_rule(rules, segs[-1] if segs else "", key)
            pt = pt or (rpt or "")
            if not cls:
                no_class += 1
                cls = _ev(node, "defaultclass", "IfcBuildingElementProxy")
        class_count[cls] = class_count.get(cls, 0) + 1
        try:
            decl = schema.declaration_by_name(cls) if cls else None
        except RuntimeError:
            decl = None  # класса нет в схеме
        if decl is None:
            bad_class.add(cls)
        elif pt:
            # PredefinedType должен быть из перечисления класса
            ok = False
            try:
                for a in decl.all_attributes():
                    if a.name() == "PredefinedType":
                        t = a.type_of_attribute()
                        while hasattr(t, "declared_type") and not hasattr(t, "enumeration_items"):
                            t = t.declared_type()
                        ok = pt in t.enumeration_items()
            except Exception:
                ok = True
            if not ok:
                bad_pt.add("%s.%s" % (cls, pt))
        # согласованность внутри элемента
        for name, vals in (("ifc_class", cls_v), ("ifc_storey", st_v), ("ifc_material", mat_v), ("ifc_guid", guid_v)):
            if vals and len({vals[i] for i in prims}) > 1:
                mixed.append("%s: different %s inside one element" % (key, name))
                break

    # сегменты-сборки не должны совпадать с элементами (путь не может быть и листом, и папкой)
    leaf_set = set(groups)
    clash = [k for k in groups if any(o != k and o.startswith(k.rstrip("/") + "/") for o in leaf_set)][:5]

    # guid
    if guid_v:
        gl = [guid_v[g[0]] for g in groups.values() if guid_v[g[0]]]
        if len(gl) != len(set(gl)):
            errors.append("Duplicate ifc_guid values on different elements.")
        badg = [g for g in gl if len(g) != 22]
        if badg:
            warns.append("%d ifc_guid values are not 22-char IFC GUIDs (will be regenerated)." % len(badg))

    # psets
    if dict_vals is not None:
        bad_d, own_pset = 0, set()
        for g in groups.values():
            d = dict_vals[g[0]]
            if not isinstance(d, dict) or any(not isinstance(v, dict) for v in d.values()):
                bad_d += 1
                continue
            for pn in d:
                if pn.startswith("Pset_") or pn.startswith("Qto_"):
                    continue
                own_pset.add(pn)
        if bad_d:
            errors.append("%d elements: %s must be {PsetName: {Prop: value}}." % (bad_d, dict_attr))
        if own_pset:
            info.append("Custom property sets: %s" % ", ".join(sorted(own_pset)[:10]))

    if bad_class:
        errors.append("Unknown classes for %s: %s -> will become %s" % (schema_id, ", ".join(sorted(bad_class)), _ev(node, "defaultclass", "IfcBuildingElementProxy")))
    if bad_pt:
        warns.append("PredefinedType not in enum (-> USERDEFINED): %s" % ", ".join(sorted(bad_pt)[:10]))
    if no_class:
        warns.append("%d elements have no class (no ifc_class, no matching rule) -> Default Class." % no_class)
    if mixed:
        warns.append("Inconsistent attributes (first prim wins):\n    " + "\n    ".join(mixed[:8]))
    if clash:
        errors.append("Path is both an element and an assembly: %s" % ", ".join(clash))
    if bad_seg:
        warns.append("Path segments with special chars (allowed: A-Z a-z 0-9 _ - . space): %s" % ", ".join(sorted(bad_seg)[:8]))
    if not st_v:
        info.append("No ifc_storey: all elements go to '%s'." % _ev(node, "storey", "Level 0"))

    info.insert(0, "Primitives: %d   Elements: %d   Path depth: %s" % (
        npr, len(groups), ", ".join("%d lvl x%d" % kv for kv in sorted(depth.items()))))
    info.insert(1, "Classes: " + ", ".join("%s x%d" % kv for kv in sorted(class_count.items(), key=lambda x: -x[1])))

    lines = ["== HIFC attribute check =="] + info
    if errors:
        lines += ["", "ERRORS:"] + ["  - " + e for e in errors]
    if warns:
        lines += ["", "WARNINGS:"] + ["  - " + w_ for w_ in warns]
    if not errors and not warns:
        lines += ["", "OK: ready to export."]
    return "\n".join(lines), len(errors)


def check_node(kwargs):
    node = kwargs["node"]
    text, nerr = check_attributes(node)
    p = node.parm("report")
    if p is not None:
        p.set(text)
    print("[HIFC] " + text)
    return text
