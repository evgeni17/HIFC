# SPDX-FileCopyrightText: 2026 EOK
# SPDX-License-Identifier: Apache-2.0
"""Совместимость старых сцен: ноды всех установленных версий ассетов в одной сцене.

    hython tests/hip_compat.py build  <scene.hip>    # собрать сцену, прогнать, сохранить + снимок состояния
    hython tests/hip_compat.py reopen <scene.hip>    # открыть в НОВОМ процессе и сверить со снимком

Проверяется: какой пакет вызывает каждая версия, параметры, геометрия, атрибуты, экспорт, и то,
что при открытии сцены ноды остаются на своей версии (никакого самовольного обновления).
"""
import json
import os
import sys

import hou

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "python3.13libs"))

NET = "/obj/__hifc_compat"
FAILS = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


def installed_versions():
    """Версии ассетов, установленные в сессии: {версия: (тип импорта, тип экспорта)}."""
    cat = hou.sopNodeTypeCategory().nodeTypes()
    out = {}
    for name in cat:
        if name.startswith("hifc::ifc_import::"):
            ver = name.rsplit("::", 1)[1]
            exp = "hifc::ifc_export::" + ver
            if exp in cat:
                out[ver] = (name, exp)
    return dict(sorted(out.items()))


def package_of(version):
    """Имя пакета, который вызывает ассет этой версии (по коду Python SOP внутри HDA)."""
    import re
    cat = hou.sopNodeTypeCategory().nodeTypes()
    d = cat["hifc::ifc_import::" + version].definition()
    for section, content in d.sections().items():
        m = re.search(r"import (hifc[a-z0-9_]*)\.sop_import", content.contents())
        if m:
            return m.group(1)
    return ""


def sample_ifc(path):
    """Небольшая модель, записанная текущим (разрабатываемым) писателем."""
    import numpy as np
    from hifc import ifc_write
    v = np.array([[x, y, z] for x in (0, 2.0) for y in (0, 0.2) for z in (0, 4.0)], float)
    f = [[0, 2, 3, 1], [4, 5, 7, 6], [0, 1, 5, 4], [2, 6, 7, 3], [0, 4, 6, 2], [1, 3, 7, 5]]
    els = [{"path": "/Frame/Wall_1", "ifc_class": "IfcWall", "ifc_storey": "L0", "name": "Wall 1",
            "description": "compat", "materials": ["Concrete"],
            "psets": {"Qto_WallBaseQuantities": {"Length": 2.0}},
            "measures": {"Qto_WallBaseQuantities": {"Length": "LENGTH"}},
            "items": [{"verts": v, "faces": f[:3], "color": (0, 0, 1, 1)},
                      {"verts": v, "faces": f[3:], "color": (1, 0, 0, 1)}]}]
    ifc_write.write_ifc(els, path, {"schema": "IFC4"})
    return path


def snapshot(net, ifc_path, out_dir):
    """Состояние каждой версии: параметры, геометрия, атрибуты, отчёт экспорта."""
    state = {}
    for ver, (imp_type, exp_type) in installed_versions().items():
        imp = net.node("imp_" + ver.replace(".", "_"))
        exp = net.node("exp_" + ver.replace(".", "_"))
        g = imp.geometry()
        prim = g.prims()[0] if len(g.prims()) else None
        bb = g.boundingBox()
        state[ver] = {
            "package": package_of(ver),
            "type": imp.type().name(),
            "parms": {p: imp.parm(p).eval() for p in ("file", "output", "yup", "scale") if imp.parm(p)},
            "prims": len(g.prims()),
            "points": g.intrinsicValue("pointcount"),
            "bbox": [round(x, 5) for x in list(bb.minvec()) + list(bb.maxvec())],
            "prim_attribs": sorted(a.name() for a in g.primAttribs()),
            "detail_attribs": sorted(a.name() for a in g.globalAttribs()),
            "guid": prim.attribValue("ifc_guid") if prim and g.findPrimAttrib("ifc_guid") else "",
            "psets": str(prim.attribValue("ifc_psets")) if prim and g.findPrimAttrib("ifc_psets") else "",
            "export_elements": None,
        }
        out = os.path.join(out_dir, "export_%s.ifc" % ver)
        exp.parm("file").set(out)
        if exp.parm("validate"):
            exp.parm("validate").set(1)      # иначе в отчёте нет строки проверки
        mod = __import__(state[ver]["package"] + ".sop_export", fromlist=["sop_export"])
        mod.export_node({"node": exp, "silent": True})
        rep = exp.parm("report").eval()
        state[ver]["export_elements"] = [ln for ln in rep.splitlines() if ln.startswith("Schema:")]
        state[ver]["export_valid"] = "Validation: OK" in rep
    return state


def build(hip):
    out_dir = os.path.dirname(os.path.abspath(hip))
    ifc_path = sample_ifc(os.path.join(out_dir, "compat.ifc"))
    obj = hou.node("/obj")
    old = obj.node("__hifc_compat")
    if old:
        old.destroy()
    net = obj.createNode("geo", "__hifc_compat")
    vers = installed_versions()
    check(len(vers) >= 2, "в сессии есть несколько версий ассетов: %s" % list(vers))
    for ver, (imp_type, exp_type) in vers.items():
        tag = ver.replace(".", "_")
        imp = net.createNode(imp_type, "imp_" + tag)
        imp.parm("file").set(ifc_path)
        imp.parm("output").set(1)          # полигоны: сравнивать проще и по ним же считается геометрия
        exp = net.createNode(exp_type, "exp_" + tag)
        exp.setInput(0, imp)
        check(not imp.errors(), "%s: импорт без ошибок %r" % (imp_type, imp.errors()[:1]))
    state = snapshot(net, ifc_path, out_dir)
    for ver, st in state.items():
        want = "hifc" if ver == max(state) else "hifc_%s" % ver.replace(".", "_")
        check(st["package"] == want, "ассеты ::%s вызывают пакет %s (ожидали %s)" % (ver, st["package"], want))
        check(st["prims"] > 0 and st["export_valid"], "::%s: %d примитивов, экспорт валиден" % (ver, st["prims"]))
    hou.hipFile.save(hip)
    json.dump(state, open(hip + ".json", "w"), indent=1, ensure_ascii=False, default=str)
    print("scene saved: %s" % hip)
    return state


def reopen(hip):
    hou.hipFile.load(hip, suppress_save_prompt=True, ignore_load_warnings=True)
    before = json.load(open(hip + ".json"))
    net = hou.node(NET)
    check(net is not None, "сцена открылась, сеть на месте")
    if net is None:
        return {}
    for ver in before:
        imp = net.node("imp_" + ver.replace(".", "_"))
        check(imp is not None and imp.type().name() == before[ver]["type"],
              "::%s нода осталась своей версии (%s)" % (ver, imp.type().name() if imp else "нет ноды"))
    after = snapshot(net, "", os.path.dirname(os.path.abspath(hip)))
    for ver, st in before.items():
        now = after.get(ver, {})
        for key in ("package", "parms", "prims", "points", "bbox", "prim_attribs", "detail_attribs", "guid", "psets"):
            same = json.dumps(now.get(key), sort_keys=True, default=str) == json.dumps(st.get(key), sort_keys=True, default=str)
            check(same, "::%s %s совпадает после перезапуска" % (ver, key))
        check(now.get("export_valid"), "::%s экспорт из открытой сцены валиден" % ver)
    return after


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "build"
    hip = sys.argv[2] if len(sys.argv) > 2 else os.path.join(HERE, "out", "compat", "compat.hip")
    os.makedirs(os.path.dirname(os.path.abspath(hip)), exist_ok=True)
    print("== hip_compat %s: %s" % (mode, hip))
    (build if mode == "build" else reopen)(hip)
    print("\nhip_compat %s: %s (%d failures)" % (mode, "OK" if not FAILS else "FAILED", len(FAILS)))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
