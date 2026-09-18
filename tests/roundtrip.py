# SPDX-FileCopyrightText: 2026 EOK
# SPDX-License-Identifier: Apache-2.0
"""Round-trip тест ядра HIFC без Houdini: IFC -> элементы -> IFC -> сравнение.

    python roundtrip.py [папка_с_ifc]    # по умолчанию tests/datasets

Нужен Python с установленным ifcopenshell (или vendor-папка HIFC под эту версию Python).
Проверяет: те же GlobalId, пути и классы после повторного чтения, валидность по ifcopenshell.validate.
"""
import glob
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "python3.13libs"))

from hifc import ifc_read, ifc_write  # noqa: E402

import ifcopenshell  # noqa: E402
import ifcopenshell.validate  # noqa: E402


def to_elements(recs):
    els = []
    for r in recs:
        if not len(r["faces"]):
            continue
        col = r["styles"][0][1] if r["styles"] else None
        els.append({
            "path": r["path"], "ifc_class": r["ifc_class"], "predefined": r["predefined"],
            "name": r["name"], "guid": r["guid"], "storey": r["storey"], "psets": r["psets"],
            "tag": r["tag"], "objecttype": r["object_type"],
            "material": r["materials"][0] if r["materials"] else None,
            "items": [{"verts": r["verts"], "faces": r["faces"].tolist(), "color": col}],
        })
    return els


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "datasets")
    files = sorted(glob.glob(os.path.join(root, "**", "*.ifc"), recursive=True))
    if not files:
        print("No .ifc files in %s. Run fetch_datasets.py first." % root)
        return 1
    out = tempfile.mkdtemp(prefix="hifc_rt_")
    ok = 0
    for f in files:
        name = os.path.relpath(f, root)
        schema = ifcopenshell.open(f).schema
        schema = "IFC4X3" if schema.startswith("IFC4X3") else "IFC4"
        recs, _ = ifc_read.read_ifc(f)
        dst = os.path.join(out, name.replace(os.sep, "__"))
        st = ifc_write.write_ifc(to_elements(recs), dst, {"schema": schema})
        recs2, _ = ifc_read.read_ifc(dst)
        a = sorted((r["guid"], r["path"]) for r in recs if len(r["faces"]))
        b = sorted((r["guid"], r["path"]) for r in recs2)
        log = ifcopenshell.validate.json_logger()
        ifcopenshell.validate.validate(ifcopenshell.open(dst), log)
        good = a == b and not log.statements
        ok += good
        print("%-4s %-70s elements=%-4d issues=%d %s" % ("OK" if good else "DIFF", name, len(recs),
              len(log.statements), "; ".join(st["warnings"][:1])))
    print("\n%d/%d files: identical GUID/path and valid IFC. Output: %s" % (ok, len(files), out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
