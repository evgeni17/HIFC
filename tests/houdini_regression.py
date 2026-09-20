# SPDX-FileCopyrightText: 2026 EOK
# SPDX-License-Identifier: Apache-2.0
"""Регрессионные тесты HDA в Houdini (packed/polygons x IFC4/IFC4X3/IFC2X3).

Запуск:  hython tests/houdini_regression.py
или в Python Shell Houdini:  exec(open("<HIFC>/tests/houdini_regression.py").read())
Все временные ноды создаются в /obj/__hifc_regression и удаляются в конце.
"""
import os
import sys
import tempfile

import hou

HERE = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.path.join(os.environ.get("HIFC", ""), "tests")
IMPORT = "hifc::ifc_import::1.0"
EXPORT = "hifc::ifc_export::1.0"
TMP = tempfile.mkdtemp(prefix="hifc_hou_")
FAILS = []

SRC_VEX = r'''
// два цвета в одном элементе, описание, два материала, Qto в метрах (СИ) с пометкой в ifc_measures
s@path = "/Frame/Wall_1";
s@ifc_class = "IfcWall";
s@ifc_description = "Description must survive";
v@Cd = @primnum < 3 ? {0,0,1} : {1,0,0};
f@Alpha = @primnum < 3 ? 1.0 : 0.4;
s[]@ifc_materials = array("Glass", "Wood, oak");
dict q; q["Length"] = 2.0; q["Height"] = 4.0;
dict ps; ps["Qto_WallBaseQuantities"] = q;
d@ifc_psets = ps;
dict k; k["Length"] = "LENGTH"; k["Height"] = "LENGTH";
dict m; m["Qto_WallBaseQuantities"] = k;
d@ifc_measures = m;
'''


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


def export(net, src, name, schema, extra=None):
    import hifc.sop_export as se
    e = net.createNode(EXPORT, "exp_" + name)
    e.setInput(0, src)
    e.parm("schema").set(["IFC4", "IFC4X3", "IFC2X3"].index(schema))
    f = os.path.join(TMP, name + ".ifc")
    e.parm("file").set(f)
    e.parm("validate").set(1)
    for k, v in (extra or {}).items():
        e.parm(k).set(v)
    se.export_node({"node": e, "silent": True})
    return f, e.parm("report").eval()


def load(net, f, name, mode):
    n = net.createNode(IMPORT, "imp_" + name)
    n.parm("file").set(f)
    n.parm("output").set(mode)
    return n


def faces_rgba(node):
    g = node.geometry()
    has_a = g.findPrimAttrib("Alpha") is not None
    return sorted({tuple(round(x, 3) for x in p.attribValue("Cd")) + ((round(p.attribValue("Alpha"), 3) if has_a else 1.0),)
                   for p in g.prims()})


def first(node, attr):
    g = node.geometry()
    return g.prims()[0].attribValue(attr) if g.findPrimAttrib(attr) else None


def main():
    import hifc.sop_export as se
    import hifc.sop_import as si
    si.clear_disk_cache()
    obj = hou.node("/obj")
    old = obj.node("__hifc_regression")
    if old:
        old.destroy()
    net = obj.createNode("geo", "__hifc_regression")
    try:
        box = net.createNode("box", "box")
        box.parmTuple("size").set((2, 4, 0.2))
        w = net.createNode("attribwrangle", "src")
        w.setInput(0, box)
        w.parm("class").set(1)
        w.parm("snippet").set(SRC_VEX)
        want = [(0.0, 0.0, 1.0, 1.0), (1.0, 0.0, 0.0, 0.4)]

        for schema in ("IFC4", "IFC4X3", "IFC2X3"):
            print("== %s" % schema)
            f1, rep = export(net, w, "src_" + schema, schema)
            check("Validation: OK" in rep, "%s first export valid" % schema)
            for mode, mname in ((0, "packed"), (1, "polys")):
                tag = "%s_%s" % (schema, mname)
                i1 = load(net, f1, tag, mode)
                g1 = i1.geometry()
                yes, no = ("ifc_packed", "ifc_polygons") if mode == 0 else ("ifc_polygons", "ifc_packed")
                check(g1.findPrimGroup(yes) is not None and g1.findPrimGroup(no) is None,
                      tag + " primitive group %s (and only it)" % yes)
                check(first(i1, "ifc_description") == "Description must survive", tag + " import keeps description")
                mats = first(i1, "ifc_materials")
                check(mats is not None and sorted(mats) == ["Glass", "Wood, oak"], tag + " import keeps materials list: %r" % (mats,))
                ps = first(i1, "ifc_psets") or {}
                ln = ps.get("Qto_WallBaseQuantities", {}).get("Length")
                check(ln is not None and abs(ln - 2.0) < 1e-6, tag + " Qto Length in SI after import: %r" % ln)
                # второй круг: экспорт в мм и обратно
                f2, rep2 = export(net, i1, "rt_" + tag, schema)
                check("Validation: OK" in rep2, tag + " re-export valid")
                i2 = load(net, f2, "rt_" + tag, 1)
                check(faces_rgba(i2) == want, tag + " colours/alpha after round trip: %r" % faces_rgba(i2))
                check(first(i2, "ifc_description") == "Description must survive", tag + " description after round trip")
                ps2 = first(i2, "ifc_psets") or {}
                ln2 = ps2.get("Qto_WallBaseQuantities", {}).get("Length")
                check(ln2 is not None and abs(ln2 - 2.0) < 1e-6, tag + " Qto Length after round trip (SI): %r" % ln2)
                m2 = first(i2, "ifc_materials")
                check(m2 is not None and sorted(m2) == ["Glass", "Wood, oak"], tag + " materials after round trip: %r" % (m2,))

        print("== packed colour override")
        f1, _ = export(net, w, "ovr_src", "IFC4")
        i1 = load(net, f1, "ovr", 0)
        cw = net.createNode("attribwrangle", "recolor")
        cw.setInput(0, i1)
        cw.parm("class").set(1)
        cw.parm("snippet").set("v@Cd = {0,1,0}; f@Alpha = 1;")
        f_keep, _ = export(net, cw, "ovr_keep", "IFC4")
        f_ovr, _ = export(net, cw, "ovr_on", "IFC4", {"packedcolor": 1})
        check(faces_rgba(load(net, f_keep, "ovr_keep", 1)) == want, "Per Face mode ignores packed Cd")
        check(faces_rgba(load(net, f_ovr, "ovr_on", 1)) == [(0.0, 1.0, 0.0, 1.0)], "Override mode recolours the element")

        ds = os.path.join(os.path.dirname(HERE), "tests", "datasets", "4.3.2.0", "Simple-Scene", "Building-Architecture.ifc")
        if os.path.exists(ds):
            print("== real model: opaque elements stay opaque (packed)")
            ref = load(net, ds, "arch_ref", 1)
            imp = load(net, ds, "arch_packed", 0)
            f2, _ = export(net, imp, "arch_rt", "IFC4X3")
            back = load(net, f2, "arch_back", 1)

            def alpha_by_guid(n):
                g = n.geometry()
                has_a = g.findPrimAttrib("Alpha") is not None
                d = {}
                for p in g.prims():
                    d.setdefault(p.attribValue("ifc_guid"), set()).add(round(p.attribValue("Alpha"), 3) if has_a else 1.0)
                return d
            a0, a1 = alpha_by_guid(ref), alpha_by_guid(back)
            bad = [gid for gid in a0 if a0[gid] != a1.get(gid)]
            check(not bad, "alpha per element identical (%d elements, %d differ)" % (len(a0), len(bad)))

        big = os.path.join(os.path.dirname(HERE), "tests", "big", "schependomlaan.ifc")
        if os.path.exists(big):
            print("== instancing of repeated geometry (Auto)")
            a = load(net, big, "big_auto", 2)
            p = load(net, big, "big_polys", 1)
            ga, gp = a.geometry(), p.geometry()
            packed = [pr for pr in ga.prims() if pr.type() == hou.primType.PackedGeometry]
            bb = lambda g: [round(x, 3) for x in list(g.boundingBox().minvec()) + list(g.boundingBox().maxvec())]
            check(len(packed) > 0, "auto mode produced %d packed instances of %d prims" % (len(packed), len(ga.prims())))
            grp_p, grp_g = ga.findPrimGroup("ifc_packed"), ga.findPrimGroup("ifc_polygons")
            check(grp_p is not None and grp_g is not None, "auto mode has both primitive groups")
            if grp_p is not None and grp_g is not None:
                np_, ng = len(grp_p.prims()), len(grp_g.prims())
                check(np_ == len(packed) and np_ + ng == len(ga.prims()),
                      "groups split the geometry: ifc_packed=%d, ifc_polygons=%d, total=%d" % (np_, ng, len(ga.prims())))
                check(all(pr.type() == hou.primType.PackedGeometry for pr in grp_p.prims()),
                      "ifc_packed holds only packed primitives")
            check(bb(ga) == bb(gp), "auto vs polygons bounding box: %s / %s" % (bb(ga), bb(gp)))
            guids_a = {pr.attribValue("ifc_guid") for pr in ga.prims()}
            guids_p = {pr.attribValue("ifc_guid") for pr in gp.prims()}
            check(guids_a == guids_p, "same elements in both modes (%d / %d)" % (len(guids_a), len(guids_p)))
            f3, rep3 = export(net, a, "big_auto_export", "IFC4")
            check("Validation: OK" in rep3, "export of instanced import is valid")
            back3 = load(net, f3, "big_back", 1)
            check(bb(back3.geometry()) == bb(gp), "bounding box after export of instances: %s" % bb(back3.geometry()))

        print("== Check Attributes rejects non-element classes")
        bw = net.createNode("attribwrangle", "badclass")
        bw.setInput(0, box)
        bw.parm("class").set(1)
        bw.parm("snippet").set('s@path = "/X"; s@ifc_class = "IfcMaterial";')
        e = net.createNode(EXPORT, "exp_bad")
        e.setInput(0, bw)
        text, nerr = se.check_attributes(e)
        check(nerr > 0 and "IfcMaterial" in text, "IfcMaterial reported as error")
    finally:
        net.destroy()
    print("\n%s (%d failures). Files: %s" % ("PASSED" if not FAILS else "FAILED", len(FAILS), TMP))
    return 1 if FAILS else 0


if __name__ == "__main__":
    rc = main()
    if hou.isUIAvailable():
        print("exit code", rc)
    else:
        sys.exit(rc)
