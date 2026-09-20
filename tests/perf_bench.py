# SPDX-FileCopyrightText: 2026 EOK
# SPDX-License-Identifier: Apache-2.0
"""Замер скорости HIFC на большой модели (запускать в отдельном процессе hython).

    hython tests/perf_bench.py model.ifc [report.json] [stage ...]

stage: core | packed | polys | export  (по умолчанию все); дисковый кэш HIFC очищается в начале
Каждый этап пишет результат в JSON сразу — при падении видно, на каком этапе.
"""
import cProfile
import io
import json
import os
import pstats
import sys
import tempfile
import time

import hou

P = sys.argv[1]
OUT = sys.argv[2] if len(sys.argv) > 2 else os.path.join(tempfile.gettempdir(), "hifc_perf.json")
STAGES = sys.argv[3:] or ["core", "auto", "packed", "polys", "export"]
res = {"file": P, "size_mb": round(os.path.getsize(P) / 1e6, 1), "stages": {}}


def save():
    with open(OUT, "w") as fh:
        json.dump(res, fh, indent=1)


def prof(fn, top=10):
    pr = cProfile.Profile()
    t = time.time()
    pr.enable()
    val = fn()
    pr.disable()
    s = io.StringIO()
    pstats.Stats(pr, stream=s).sort_stats("tottime").print_stats(top)
    return val, round(time.time() - t, 2), s.getvalue()[-3000:]


def stage(name, fn):
    res["stages"][name] = {"status": "running"}
    save()
    try:
        info, secs, profile = prof(fn)
        res["stages"][name] = {"status": "ok", "seconds": secs, "info": info, "profile": profile}
    except Exception as ex:
        import traceback
        res["stages"][name] = {"status": "error", "error": traceback.format_exc()[-1500:]}
    save()


import hifc.ifc_read as r  # noqa: E402
import hifc.sop_export as se  # noqa: E402
import hifc.sop_import as si  # noqa: E402

si.clear_disk_cache()  # холодный старт

net = hou.node("/obj").createNode("geo", "perf")
imp = net.createNode("hifc::ifc_import::1.0", "imp")
imp.parm("file").set(P)

if "core" in STAGES:
    def core():
        recs = list(r.iter_ifc(P))
        return {"elements": len(recs), "triangles": int(sum(len(x["faces"]) for x in recs))}
    stage("core_read", core)

if "auto" in STAGES:
    def auto():
        imp.parm("output").set(2)
        imp.cook(force=True)
        g = imp.geometry()
        packed = [pr for pr in g.prims() if pr.type() == hou.primType.PackedGeometry]
        names = list(packed[0].intrinsicNames()) if packed else []
        key = next((k for k in ("geometryid", "packedprimitivename") if k in names), None)
        uniq, stored, shown = {}, 0, 0
        for pr in packed:
            e = pr.getEmbeddedGeometry()
            n = len(e.prims())
            shown += n
            k = pr.intrinsicValue(key) if key else id(e)
            if k not in uniq:
                uniq[k] = n
                stored += n
        return {"prims": len(g.prims()), "packed": len(packed), "uniq_key": key,
                "unique_geometries": len(uniq), "triangles_stored": stored,
                "triangles_shown": shown, "errors": imp.errors()}
    stage("hda_auto_cook", auto)

if "auto" in STAGES:
    def auto_warm():
        imp.parm("output").set(1)
        imp.cook(force=True)
        imp.parm("output").set(2)
        imp.cook(force=True)
        return {"prims": len(imp.geometry().prims())}
    stage("hda_auto_cook_warm_cache", auto_warm)

if "packed" in STAGES:
    def packed():
        imp.parm("output").set(0)
        imp.cook(force=True)
        g = imp.geometry()
        return {"prims": len(g.prims()), "errors": imp.errors()}
    stage("hda_packed_cook", packed)

if "packed" in STAGES:
    def packed_disk():
        si._CACHE.clear()  # как новая сессия Houdini: остаётся только дисковый кэш
        imp.node("IFC_READ").cook(force=True)  # force на HDA не перекукивает внутренние ноды
        return {"prims": len(imp.geometry().prims())}
    stage("hda_packed_from_disk_cache", packed_disk)

if "polys" in STAGES:
    def polys():
        imp.parm("output").set(1)
        imp.cook(force=True)
        g = imp.geometry()
        return {"prims": len(g.prims()), "errors": imp.errors()}
    stage("hda_polys_cook", polys)

if "export" in STAGES:
    def export():
        imp.parm("output").set(0)
        exp = net.createNode("hifc::ifc_export::1.0", "exp")
        exp.setInput(0, imp)
        exp.parm("file").set(os.path.join(tempfile.gettempdir(), "hifc_perf_out.ifc"))
        se.export_node({"node": exp, "silent": True})
        return {"report": exp.parm("report").eval()}
    stage("hda_export", export)

res["done"] = True
save()
print("[HIFC perf] written", OUT)
