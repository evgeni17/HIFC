# SPDX-FileCopyrightText: 2026 EOK
# SPDX-License-Identifier: Apache-2.0
"""Память и время одного режима импорта в отдельном процессе.

    hython tests/mem_bench.py model.ifc <0|1|2> [report.json]

Режим: 0 packed, 1 polygons, 2 auto.
Файл читается до замера, поэтому rss_geometry_mb — это цена самой геометрии Houdini,
без памяти на разбор IFC.
"""
import json
import os
import resource
import sys
import tempfile
import time

import hou

P = sys.argv[1]
MODE = int(sys.argv[2])
OUT = sys.argv[3] if len(sys.argv) > 3 else os.path.join(tempfile.gettempdir(), "hifc_mem_%d.json" % MODE)


def rss_mb():
    v = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return round(v / (1e6 if sys.platform == "darwin" else 1e3), 1)  # macOS: байты, linux: КБ


import hifc.sop_import as si  # noqa: E402

si.clear_disk_cache()
net = hou.node("/obj").createNode("geo", "mem")
imp = net.createNode("hifc::ifc_import::1.0", "imp")
imp.parm("file").set(P)
# прогрев кэша записей без построения геометрии: дальше меряем только цену геометрии
si._load(P, [], ["IfcOpeningElement", "IfcSpace", "IfcVirtualElement"], "elements", True, 0, None, True)
before = rss_mb()

imp.parm("output").set(MODE)
t = time.time()
imp.cook(force=True)
secs = round(time.time() - t, 2)
g = imp.geometry()
peak = rss_mb()

packed = [p for p in g.prims() if p.type() == hou.primType.PackedGeometry]
uniq, shown = {}, 0
for p in packed:
    e = p.getEmbeddedGeometry()
    n = len(e.prims())
    shown += n
    uniq.setdefault(p.intrinsicValue("geometryid"), n)
info = {"file": os.path.basename(P), "mode": MODE, "seconds": secs,
        "rss_after_read_mb": before, "rss_peak_mb": peak, "rss_geometry_mb": round(peak - before, 1),
        "prims": len(g.prims()), "points": g.intrinsicValue("pointcount"),
        "packed": len(packed), "unique_packed_geometries": len(uniq),
        "triangles_in_packed_shown": shown, "triangles_in_packed_stored": sum(uniq.values()),
        "errors": imp.errors()}
with open(OUT, "w") as fh:
    json.dump(info, fh, indent=1)
print("[HIFC mem]", json.dumps(info))
