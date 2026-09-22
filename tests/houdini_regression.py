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

        print("== unsupported properties are reported, not dropped silently")
        import hifc
        hifc.ensure_vendor_path()
        import ifcopenshell
        import hifc.ifc_write as iw
        src = os.path.join(TMP, "table.ifc")
        import numpy as np
        bv = np.array([[x, y, z] for x in (0, 2.0) for y in (0, 0.2) for z in (0, 4.0)], float)
        bf = [[0, 2, 3, 1], [4, 5, 7, 6], [0, 1, 5, 4], [2, 6, 7, 3], [0, 4, 6, 2], [1, 3, 7, 5]]
        iw.write_ifc([{"path": "/W1", "ifc_class": "IfcWall", "items": [{"verts": bv, "faces": bf}]}], src)
        fh = ifcopenshell.open(src)
        props = [fh.create_entity("IfcPropertyTableValue", Name="Table",
                                  DefiningValues=[fh.create_entity("IfcReal", 1.0)],
                                  DefinedValues=[fh.create_entity("IfcReal", 10.0)]),
                 fh.create_entity("IfcPropertySingleValue", Name="Simple",
                                  NominalValue=fh.create_entity("IfcText", "ok"))]
        pset = fh.create_entity("IfcPropertySet", GlobalId=ifcopenshell.guid.new(),
                                Name="Pset_Custom", HasProperties=props)
        fh.create_entity("IfcRelDefinesByProperties", GlobalId=ifcopenshell.guid.new(),
                         RelatedObjects=[fh.by_type("IfcWall")[0]], RelatingPropertyDefinition=pset)
        fh.write(src)
        tb = load(net, src, "table", 1)
        gt = tb.geometry()
        warn = gt.attribValue("ifc_warnings") if gt.findGlobalAttrib("ifc_warnings") else ""
        check(len(gt.prims()) == 12, "geometry still built with a warning (%d prims)" % len(gt.prims()))
        check("IfcPropertyTableValue" in warn, "table property reported in ifc_warnings: %r" % warn[:60])
        inner = tb.node("IFC_READ")
        check(inner is not None and any("IfcPropertyTableValue" in w for w in inner.warnings()),
              "node warning raised")
        check(first(tb, "ifc_psets") == {"Pset_Custom": {"Simple": "ok"}},
              "supported property still imported: %r" % (first(tb, "ifc_psets"),))

        print("== top levels in detail attributes: georeference, sites, buildings")
        sys.path.insert(0, HERE)
        import georef_fixture as gf
        import hifc.sop_import as si
        gpath = gf.make(os.path.join(TMP, "georef_IFC4.ifc"), "IFC4")
        gn = load(net, gpath, "georef", 1)
        gg = gn.geometry()
        check(gg.attribValue("ifc_crs") == gf.EXPECT["crs"], "s@ifc_crs = %r" % gg.attribValue("ifc_crs"))
        gr = gg.attribValue("ifc_georef") if gg.findGlobalAttrib("ifc_georef") else {}
        mo = list((gr.get("map_conversion") or {}).get("map_origin_m") or [])
        check(len(mo) == 3 and all(abs(a - b) < 1e-6 for a, b in zip(mo, gf.EXPECT["map_origin_m"])),
              "d@ifc_georef map origin (m) = %r" % mo)
        sites = gg.attribValue("ifc_sites") if gg.findGlobalAttrib("ifc_sites") else ()
        facs = gg.attribValue("ifc_facilities") if gg.findGlobalAttrib("ifc_facilities") else ()
        check(len(sites) == 1 and len(facs) == 1, "d[]@ifc_sites / d[]@ifc_facilities: %d / %d" % (len(sites), len(facs)))
        if sites and facs:
            sx, so = sites[0]["xform"], list(sites[0]["origin"])
            # IFC (10, 20, 0) м -> Houdini с Y вверх: (10, 0, -20)
            check(all(abs(a - b) < 1e-6 for a, b in zip(so, (10.0, 0.0, -20.0))), "site origin in Houdini axes = %r" % so)
            m4 = hou.Matrix4(list(sx))
            t = list(hou.Vector3(0, 0, 0) * m4)
            check(all(abs(a - b) < 1e-6 for a, b in zip(t, so)), "site xform works as hou.Matrix4: %r" % t)
            check(abs(sites[0]["latitude"] - gf.EXPECT["latitude"]) < 1e-6, "site latitude = %r" % sites[0]["latitude"])
            fo = list(facs[0]["origin"])
            check(all(abs(a - b) < 1e-6 for a, b in zip(fo, (13.0, 0.5, -24.0))), "building origin in Houdini axes = %r" % fo)
            bb = gg.boundingBox()
            # стена стоит в начале здания: её угол совпадает с началом здания в осях Houdini
            check(abs(bb.minvec()[0] - fo[0]) < 1e-5 and abs(bb.minvec()[1] - fo[1]) < 1e-5 and abs(bb.maxvec()[2] - fo[2]) < 1e-5,
                  "geometry and building xform agree: bbox min %r" % (list(bb.minvec()),))
        si._CACHE.clear()
        gn.node("IFC_READ").cook(force=True)
        check(gn.geometry().attribValue("ifc_crs") == gf.EXPECT["crs"], "top-level data survives the disk cache")

        print("== global_xform: top placement, Transform By Attribute, Move to Origin")

        def xform_by(src_node, name, invert):
            x = net.createNode("xformbyattrib", name)
            x.setInput(0, src_node)
            x.parm("xformattrib").set("global_xform")
            x.parm("invertxform").set(1 if invert else 0)
            return x

        def box_of(n):
            b = n.geometry().boundingBox()
            return list(b.minvec()), list(b.maxvec())

        near = load(net, gpath, "gx_near", 1)
        gxa = near.geometry().findGlobalAttrib("global_xform")
        check(gxa is not None and gxa.size() == 16 and gxa.qualifier() == "Matrix",
              "4@global_xform exists as a matrix (%s)" % (gxa.qualifier() if gxa else None))
        check("Site A" in near.geometry().attribValue("global_xform_source"),
              "source = %r" % near.geometry().attribValue("global_xform_source"))
        lo, hi = box_of(xform_by(near, "gx_near_inv", True))
        # здание стоит в (3, 4, 0.5) от площадки -> в осях Houdini (3, 0.5, -4); стена 0.2 м по IFC Y
        check(all(abs(a - b) < 1e-4 for a, b in zip(lo, (3.0, 0.5, -4.2))) and abs(hi[2] + 4.0) < 1e-4,
              "Invert Transformation puts the site at the origin: bbox min %r" % (lo,))

        far_path = gf.make(os.path.join(TMP, "georef_far.ifc"), "IFC4", site_origin_m=[500000.0, 5700000.0, 45.0])
        far = load(net, far_path, "gx_far", 1)
        lo, hi = box_of(xform_by(far, "gx_far_inv", True))
        print("  info float32 P far away, then inverted: wall thickness %.4f m (true 0.2)" % (hi[2] - lo[2]))
        far_o = load(net, far_path, "gx_far_origin", 1)
        far_o.parm("toorigin").set(1)
        lo, hi = box_of(far_o)
        check(all(abs(a - b) < 1e-4 for a, b in zip(lo, (3.0, 0.5, -4.2))) and abs((hi[2] - lo[2]) - 0.2) < 1e-5,
              "Move to Origin keeps the 0.2 m wall exact: bbox min %r, thickness %.6f" % (lo, hi[2] - lo[2]))
        go = far_o.geometry()
        check(go.attribValue("ifc_moved_to_origin") == 1, "i@ifc_moved_to_origin = 1")
        check(list(go.attribValue("global_xform")) == list(far.geometry().attribValue("global_xform")),
              "global_xform is the same with and without Move to Origin")
        so = list(go.attribValue("ifc_sites")[0]["origin"])
        check(all(abs(v) < 1e-9 for v in so), "site xform follows the moved geometry: origin %r" % so)
        lo, hi = box_of(xform_by(far_o, "gx_far_back", False))
        check(abs(lo[0] - 500003.0) < 1.0 and abs(lo[1] - 45.5) < 1.0 and abs(hi[2] + 5700004.0) < 1.0,
              "Transform By Attribute without Invert puts it back: bbox min %r" % (lo,))

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
