# SPDX-FileCopyrightText: 2026 EOK
# SPDX-License-Identifier: Apache-2.0
"""Регрессионные тесты ядра (без Houdini): единицы Qto, описание, материалы, проверка классов.

    python tests/test_core.py        # код возврата 0 = всё прошло
"""
import os
import sys
import tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "python3.13libs"))

from hifc import ifc_read, ifc_write  # noqa: E402

import ifcopenshell  # noqa: E402
import ifcopenshell.util.element as ue  # noqa: E402
import ifcopenshell.util.unit as uu  # noqa: E402

TMP = tempfile.mkdtemp(prefix="hifc_core_")
FAILS = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


def box(w=2.0, d=0.2, h=4.0):
    v = np.array([[x, y, z] for x in (0, w) for y in (0, d) for z in (0, h)], float)
    f = [[0, 2, 3, 1], [4, 5, 7, 6], [0, 1, 5, 4], [2, 6, 7, 3], [0, 4, 6, 2], [1, 3, 7, 5]]
    return v, f


def wall(**kw):
    v, f = box()
    el = {"path": "/W1", "ifc_class": "IfcWall", "items": [{"verts": v, "faces": f}]}
    el.update(kw)
    return el


def main():
    print("1. Qto: source in metres -> export in mm keeps physical values")
    for schema in ("IFC4", "IFC4X3", "IFC2X3"):
        src = os.path.join(TMP, "m_%s.ifc" % schema)
        ifc_write.write_ifc([wall(psets={"Qto_WallBaseQuantities": {"Length": 2.0, "NetSideArea": 8.0, "NetVolume": 1.6}})],
                            src, {"schema": schema, "length_unit": "m"})
        recs, _ = ifc_read.read_ifc(src)
        # писатель без measures пишет «как есть» в метрах; ридер сообщает виды величин
        els = [{"path": r["path"], "ifc_class": r["ifc_class"], "psets": r["psets"], "measures": r["measures"],
                "items": [{"verts": r["verts"], "faces": r["faces"].tolist()}]} for r in recs]
        dst = os.path.join(TMP, "mm_%s.ifc" % schema)
        ifc_write.write_ifc(els, dst, {"schema": schema, "length_unit": "mm"})
        g = ifcopenshell.open(dst)
        q = ue.get_psets(g.by_type("IfcWall")[0])["Qto_WallBaseQuantities"]
        ls = uu.calculate_unit_scale(g)
        check(abs(q["Length"] * ls - 2.0) < 1e-9, "%s Length = %s mm -> %.3f m" % (schema, q["Length"], q["Length"] * ls))
        check(abs(q["NetSideArea"] - 8.0) < 1e-9 and abs(q["NetVolume"] - 1.6) < 1e-9, "%s area/volume stay in m2/m3" % schema)
        back, _ = ifc_read.read_ifc(dst)
        check(abs(back[0]["psets"]["Qto_WallBaseQuantities"]["Length"] - 2.0) < 1e-9, "%s re-read in SI = 2 m" % schema)

    print("2. Description, Tag, ObjectType, USERDEFINED")
    dst = os.path.join(TMP, "attrs.ifc")
    ifc_write.write_ifc([wall(description="keep me", tag="W-01", objecttype="Brick 250", predefined="FOO")], dst)
    r = ifc_read.read_ifc(dst)[0][0]
    check(r["description"] == "keep me", "description kept")
    check(r["tag"] == "W-01", "tag kept")
    check(r["predefined"] == "USERDEFINED" and r["object_type"] == "Brick 250",
          "unknown PredefinedType -> USERDEFINED, user ObjectType kept (%s / %s)" % (r["predefined"], r["object_type"]))

    print("3. Several materials -> one material set, not a merged name")
    for schema in ("IFC4", "IFC2X3"):
        dst = os.path.join(TMP, "mats_%s.ifc" % schema)
        ifc_write.write_ifc([wall(materials=["Glass", "Wood, oak"])], dst, {"schema": schema})
        r = ifc_read.read_ifc(dst)[0][0]
        check(sorted(r["materials"]) == ["Glass", "Wood, oak"], "%s materials = %r" % (schema, r["materials"]))

    print("4. Classes that are not elements")
    for cls, st in (("IfcMaterial", "not_product"), ("IfcWallType", "not_product"), ("IfcBuildingElement", "abstract"),
                    ("IfcBuildingStorey", "spatial"), ("IfcNoSuchThing", "unknown"), ("IfcWall", "ok")):
        got = ifc_write.class_status("IFC4", cls)
        check(got == st, "class_status(%s) = %s" % (cls, got))
    dst = os.path.join(TMP, "badclass.ifc")
    stt = ifc_write.write_ifc([wall(ifc_class="IfcMaterial")], dst)
    r = ifc_read.read_ifc(dst)[0][0]
    check(r["ifc_class"] == "IfcBuildingElementProxy" and stt["warnings"], "IfcMaterial -> proxy with a warning, no crash")

    print("5. Face colours and transparency")
    v, f = box()
    items = [{"verts": v, "faces": f[:3], "color": (0, 0, 1, 1)}, {"verts": v, "faces": f[3:], "color": (1, 0, 0, 0.4)}]
    dst = os.path.join(TMP, "colors.ifc")
    ifc_write.write_ifc([wall(items=items)], dst)
    r = ifc_read.read_ifc(dst)[0][0]
    cols = sorted(tuple(round(x, 3) for x in c) for _, c in r["styles"])
    check(cols == [(0.0, 0.0, 1.0, 1.0), (1.0, 0.0, 0.0, 0.4)], "two styles kept: %r" % cols)

    print("\n%s (%d failures). Files: %s" % ("PASSED" if not FAILS else "FAILED", len(FAILS), TMP))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
