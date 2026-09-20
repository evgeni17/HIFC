# SPDX-FileCopyrightText: 2026 EOK
# SPDX-License-Identifier: Apache-2.0
"""Round-trip тест ядра HIFC без Houdini: IFC -> элементы -> IFC -> сравнение по полям.

    python roundtrip.py [папка_с_ifc] [--schema IFC4|IFC4X3|IFC2X3|auto] [--unit mm|cm|m] [--json отчёт.json]

Сравнивает: GUID, path, класс, PredefinedType, ObjectType, имя, описание, марку, этаж, материалы,
наборы свойств (длины/площади/объёмы — в СИ), цвета граней и габариты элемента.
Известные и задокументированные преобразования (см. EXPECTED) считаются отдельно и тест не валят.
Код возврата: 0 — нет неожиданных расхождений, 1 — есть.
"""
import argparse
import glob
import json
import os
import sys
import tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "python3.13libs"))

from hifc import ifc_read, ifc_write  # noqa: E402

import ifcopenshell  # noqa: E402
import ifcopenshell.validate  # noqa: E402

BBOX_TOL = 1e-5      # м
VALUE_RTOL = 1e-6    # относительная точность чисел в свойствах
AREA_RTOL = 1e-3     # относительная точность площадей при сравнении раскладки цветов


def to_elements(recs):
    """Адаптер «как в Houdini»: передаём всё, что сохраняет нода импорта."""
    els = []
    for r in recs:
        if not len(r["faces"]):
            continue
        # части геометрии по стилям граней: сохраняем распределение цветов, а не только первый
        items = []
        fs = r["face_style"]
        wv = ifc_read.world_verts(r)
        for sid in sorted(set(fs.tolist())):
            faces = r["faces"][fs == sid]
            used = np.unique(faces)
            remap = {int(p): i for i, p in enumerate(used)}
            col = r["styles"][sid][1] if 0 <= sid < len(r["styles"]) else None
            name = r["styles"][sid][0] if 0 <= sid < len(r["styles"]) else None
            items.append({"verts": wv[used], "faces": [[remap[int(i)] for i in f] for f in faces],
                          "color": col, "style": name or None})
        els.append({
            "path": r["path"], "ifc_class": r["ifc_class"], "predefined": r["predefined"],
            "name": r["name"], "guid": r["guid"], "storey": r["storey"], "psets": r["psets"],
            "measures": r["measures"], "tag": r["tag"], "objecttype": r["object_type"],
            "description": r["description"], "materials": r["materials"], "items": items,
        })
    return els


def _num_equal(a, b):
    if isinstance(a, bool) or isinstance(b, bool):
        return a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) <= VALUE_RTOL * max(1.0, abs(a), abs(b))
    return str(a) == str(b)


def _psets_diff(a, b, ma, mb):
    """Расхождения свойств в обе стороны, включая пометки измеряемых величин."""
    diffs = []
    for pn, props in a.items():
        pb = b.get(pn)
        if pb is None:
            diffs.append("missing set %s" % pn)
            continue
        for k, v in props.items():
            if k not in pb:
                diffs.append("%s.%s missing" % (pn, k))
                continue
            if not _num_equal(v, pb[k]):
                diffs.append("%s.%s: %r -> %r" % (pn, k, v, pb[k]))
            ka = (ma.get(pn) or {}).get(k)
            kb = (mb.get(pn) or {}).get(k)
            if ka != kb:
                diffs.append("%s.%s measure %s -> %s" % (pn, k, ka, kb))
    for pn, props in b.items():
        if pn not in a:
            diffs.append("extra set %s" % pn)
            continue
        for k in props:
            if k not in a[pn]:
                diffs.append("%s.%s extra" % (pn, k))
    return diffs


def _tri_areas(v, faces):
    p0, p1, p2 = v[faces[:, 0]], v[faces[:, 1]], v[faces[:, 2]]
    return 0.5 * np.linalg.norm(np.cross(p1 - p0, p2 - p0), axis=1)


def _color_areas(r):
    """Площадь граней по цветам. В отличие от палитры ловит перестановку цветов между гранями."""
    v = ifc_read.world_verts(r)
    faces = r["faces"]
    if not len(faces) or not len(v):
        return {}
    areas = _tri_areas(v, faces)
    fs = r["face_style"]
    rv = np.round(v, 6)
    seen, out = set(), {}
    for i, t in enumerate(faces.tolist()):
        key = tuple(sorted(tuple(rv[j]) for j in t))
        if key in seen:
            continue       # повторяющиеся грани (двусторонние поверхности) считаем один раз
        seen.add(key)
        sid = int(fs[i])
        col = r["styles"][sid][1] if 0 <= sid < len(r["styles"]) else None
        ck = tuple(round(float(x), 3) for x in col) if col is not None else None
        out[ck] = out.get(ck, 0.0) + float(areas[i])
    return out


def _colors_diff(a, b):
    ca, cb = _color_areas(a), _color_areas(b)
    total = sum(ca.values()) or 1.0
    tol = AREA_RTOL * total
    if set(ca) != set(cb):
        return "colors: %r -> %r" % (sorted(ca), sorted(cb))
    for k, v in ca.items():
        if abs(v - cb[k]) > tol:
            return "colour %r covers %.4g m2 instead of %.4g m2" % (k, cb[k], v)
    return None


def _bbox(r):
    v = ifc_read.world_verts(r)
    return np.concatenate([v.min(0), v.max(0)]) if len(v) else np.zeros(6)


def _pdt_required(schema, cls):
    """PredefinedType обязателен для класса в этой схеме (в IFC2X3 их много)."""
    import ifcopenshell.ifcopenshell_wrapper as w
    try:
        decl = w.schema_by_name(schema).declaration_by_name(cls)
        for i, at in enumerate(decl.all_attributes()):
            if at.name() == "PredefinedType":
                return not decl.attribute_by_index(i).optional()
    except Exception:
        pass
    return False


def _pdt_values(schema, cls):
    """Допустимые значения PredefinedType класса в схеме (пусто, если у класса его нет)."""
    import ifcopenshell.ifcopenshell_wrapper as w
    try:
        decl = w.schema_by_name(schema).declaration_by_name(cls)
    except Exception:
        return ()
    while decl is not None:
        for at in getattr(decl, "attributes", lambda: [])():
            if at.name() != "PredefinedType":
                continue
            t = at.type_of_attribute()
            for _ in range(4):
                t = getattr(t, "declared_type", lambda: None)() or t
                if hasattr(t, "enumeration_items"):
                    return tuple(t.enumeration_items())
        decl = getattr(decl, "supertype", lambda: None)()
    return ()


def expected(field, a, b, schema_out):
    """Известные преобразования HIFC. Разрешается только то, что подтверждается целевой схемой."""
    cls_a = a["ifc_class"]
    if field in ("ifc_class", "predefined", "object_type"):
        reason = ifc_write.downgrade_reason(schema_out, cls_a)
        proxy = b["ifc_class"] == "IfcBuildingElementProxy" and cls_a != "IfcBuildingElementProxy"
        if proxy and reason:
            # причину берём у самого writer: любая другая замена класса — ошибка
            return "class %s -> proxy (%s)" % (cls_a, reason)
        if field == "predefined" and not a["predefined"] and b["predefined"] == "NOTDEFINED" \
                and _pdt_required(schema_out, b["ifc_class"]):
            return "PredefinedType required in %s -> NOTDEFINED" % schema_out
        if field == "predefined" and a["predefined"] and a["predefined"] not in _pdt_values(schema_out, b["ifc_class"]):
            return "PredefinedType %s not in %s" % (a["predefined"], schema_out)
        return None
    if field == "name" and not a["name"]:
        return "empty name -> path leaf"
    if field == "storey" and a["storey_class"] != "IfcBuildingStorey":
        return "container %s -> IfcBuildingStorey" % (a["storey_class"] or "none")
    return None


def compare(recs_a, recs_b, schema_out):
    """Расхождения между входом и выходом. Сравнение симметричное: лишние элементы тоже ошибка."""
    src = [r for r in recs_a if len(r["faces"])]
    unexpected, known = [], {}
    ib = {}
    for r in recs_b:
        if not len(r["faces"]):
            continue
        if r["guid"] in ib:
            unexpected.append((r["guid"], "duplicate element in output"))
        ib[r["guid"]] = r
    for g in sorted(set(ib) - {r["guid"] for r in src}):
        unexpected.append((g, "extra element in output (%s)" % ib[g]["ifc_class"]))
    for a in src:
        b = ib.get(a["guid"])
        if b is None:
            unexpected.append((a["guid"], "element missing"))
            continue
        for field in ("path", "ifc_class", "predefined", "object_type", "name", "description", "tag", "storey"):
            if (a[field] or "") != (b[field] or ""):
                why = expected(field, a, b, schema_out)
                if why:
                    known[why] = known.get(why, 0) + 1
                else:
                    unexpected.append((a["guid"], "%s: %r -> %r" % (field, a[field], b[field])))
        if sorted(a["materials"]) != sorted(b["materials"]):
            unexpected.append((a["guid"], "materials: %r -> %r" % (a["materials"], b["materials"])))
        for d in _psets_diff(a["psets"], b["psets"], a["measures"], b["measures"]):
            unexpected.append((a["guid"], "psets " + d))
        cd = _colors_diff(a, b)
        if cd:
            unexpected.append((a["guid"], cd))
        if np.max(np.abs(_bbox(a) - _bbox(b))) > BBOX_TOL:
            unexpected.append((a["guid"], "bbox differs by %.2e m" % np.max(np.abs(_bbox(a) - _bbox(b)))))
    return unexpected, known


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("root", nargs="?", default=os.path.join(HERE, "datasets"))
    ap.add_argument("--schema", default="auto")
    ap.add_argument("--unit", default="mm")
    ap.add_argument("--json")
    args = ap.parse_args()
    files = sorted(glob.glob(os.path.join(args.root, "**", "*.ifc"), recursive=True))
    if not files:
        print("No .ifc files in %s. Run fetch_datasets.py first." % args.root)
        return 1
    out = tempfile.mkdtemp(prefix="hifc_rt_")
    report, bad_files = [], 0
    for f in files:
        name = os.path.relpath(f, args.root)
        src_schema = ifcopenshell.open(f).schema
        schema = args.schema
        if schema == "auto":
            schema = "IFC4X3" if src_schema.startswith("IFC4X3") else "IFC4"
        recs, _ = ifc_read.read_ifc(f)
        dst = os.path.join(out, name.replace(os.sep, "__"))
        st = ifc_write.write_ifc(to_elements(recs), dst, {"schema": schema, "length_unit": args.unit})
        recs2, _ = ifc_read.read_ifc(dst)
        log = ifcopenshell.validate.json_logger()
        ifcopenshell.validate.validate(ifcopenshell.open(dst), log)
        unexpected, known = compare(recs, recs2, schema)
        good = not unexpected and not log.statements
        bad_files += not good
        print("%-4s %-66s el=%-4d issues=%d unexpected=%d known=%s" % (
            "OK" if good else "FAIL", name[:66], len(recs), len(log.statements), len(unexpected),
            ", ".join("%s x%d" % kv for kv in known.items()) or "-"))
        for g, msg in unexpected[:5]:
            print("       %s %s" % (g, msg))
        report.append({"file": name, "schema_out": schema, "ok": good, "validation": len(log.statements),
                       "unexpected": unexpected, "known": known, "warnings": st["warnings"]})
    print("\n%d/%d files without unexpected differences (schema=%s, unit=%s). Output: %s"
          % (len(files) - bad_files, len(files), args.schema, args.unit, out))
    if args.json:
        with open(args.json, "w") as fh:
            json.dump(report, fh, indent=1, default=str)
    return 1 if bad_files else 0


if __name__ == "__main__":
    sys.exit(main())
