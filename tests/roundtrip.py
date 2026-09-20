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
COLOR_TOL = 1e-3


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


def _psets_diff(a, b):
    diffs = []
    for pn, props in a.items():
        pb = b.get(pn)
        if pb is None:
            diffs.append("missing set %s" % pn)
            continue
        for k, v in props.items():
            if k not in pb:
                diffs.append("%s.%s missing" % (pn, k))
            elif not _num_equal(v, pb[k]):
                diffs.append("%s.%s: %r -> %r" % (pn, k, v, pb[k]))
    return diffs


def _colors(r):
    return sorted(tuple(round(float(x), 3) for x in c) for _, c in r["styles"] if c is not None)


def _bbox(r):
    v = ifc_read.world_verts(r)
    return np.concatenate([v.min(0), v.max(0)]) if len(v) else np.zeros(6)


def expected(field, a, b, schema_out):
    """Известные преобразования HIFC 0.2 (задокументированы в README)."""
    cls_a = a["ifc_class"]
    downgraded = b["ifc_class"] == "IfcBuildingElementProxy" and cls_a != "IfcBuildingElementProxy"
    if downgraded and field in ("ifc_class", "predefined", "object_type"):
        return "class downgraded (%s)" % cls_a
    if field == "name" and not a["name"]:
        return "empty name -> path leaf"
    if field == "storey" and a["storey_class"] != "IfcBuildingStorey":
        return "container %s -> IfcBuildingStorey" % (a["storey_class"] or "none")
    return None


def compare(recs_a, recs_b, schema_out):
    ib = {r["guid"]: r for r in recs_b}
    unexpected, known = [], {}
    for a in recs_a:
        if not len(a["faces"]):
            continue
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
        for d in _psets_diff(a["psets"], b["psets"]):
            unexpected.append((a["guid"], "psets " + d))
        ca, cb = _colors(a), _colors(b)
        if len(ca) != len(cb) or any(max(abs(x - y) for x, y in zip(p, q)) > COLOR_TOL for p, q in zip(ca, cb)):
            unexpected.append((a["guid"], "colors: %r -> %r" % (ca, cb)))
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
        # классы, которых нет в целевой схеме, — ожидаемая замена (предупреждение писателя)
        if schema != src_schema:
            rest = []
            for g, msg in unexpected:
                if msg.startswith(("ifc_class:", "predefined:", "object_type:")):
                    known["class/type not in %s" % schema] = known.get("class/type not in %s" % schema, 0) + 1
                else:
                    rest.append((g, msg))
            unexpected = rest
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
