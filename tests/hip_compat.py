# SPDX-FileCopyrightText: 2026 EOK
# SPDX-License-Identifier: Apache-2.0
"""Совместимость старых сцен: ноды всех установленных версий ассетов во всех режимах вывода.

    hython tests/hip_compat.py build  <scene.hip>    # собрать сцену, прогнать, сохранить + снимок состояния
    hython tests/hip_compat.py reopen <scene.hip>    # открыть в НОВОМ процессе и сверить со снимком

Для каждой версии ассетов создаются узлы импорта во всех трёх режимах (Packed, Polygons, Auto),
и из каждого делается экспорт. Проверяется: какой пакет вызывает версия, параметры, геометрия, атрибуты,
валидность экспорта, и то, что при открытии сцены ноды остаются на своей версии.
"""
import json
import os
import re
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


MODES = ((0, "packed"), (1, "polys"), (2, "auto"))


def node_names(ver, mode):
    tag = "%s_%s" % (ver.replace(".", "_"), mode)
    return "imp_" + tag, "exp_" + tag


def snapshot(net, out_dir):
    """Состояние каждой пары (версия ассетов, режим вывода)."""
    state = {}
    for ver in installed_versions():
        pkg = package_of(ver)
        mod = __import__(pkg + ".sop_export", fromlist=["sop_export"])
        for _, mode in MODES:
            iname, ename = node_names(ver, mode)
            imp, exp = net.node(iname), net.node(ename)
            if imp is None or exp is None:
                continue
            g = imp.geometry()
            prim = g.prims()[0] if len(g.prims()) else None
            bb = g.boundingBox()
            key = "%s|%s" % (ver, mode)
            out = os.path.join(out_dir, "export_%s_%s.ifc" % (ver, mode))
            exp.parm("file").set(out)
            if exp.parm("validate"):
                exp.parm("validate").set(1)      # иначе в отчёте нет строки проверки
            mod.export_node({"node": exp, "silent": True})
            rep = exp.parm("report").eval()
            state[key] = {
                "package": pkg,
                "type": imp.type().name(),
                "parms": {p: imp.parm(p).eval() for p in ("file", "output", "yup", "scale") if imp.parm(p)},
                "prims": len(g.prims()),
                "points": g.intrinsicValue("pointcount"),
                "packed": sum(1 for p in g.prims() if p.type() == hou.primType.PackedGeometry),
                "bbox": [round(x, 5) for x in list(bb.minvec()) + list(bb.maxvec())],
                "prim_attribs": sorted(a.name() for a in g.primAttribs()),
                "detail_attribs": sorted(a.name() for a in g.globalAttribs()),
                "groups": sorted(gr.name() for gr in g.primGroups()),
                "guid": prim.attribValue("ifc_guid") if prim and g.findPrimAttrib("ifc_guid") else "",
                "psets": str(prim.attribValue("ifc_psets")) if prim and g.findPrimAttrib("ifc_psets") else "",
                # из отчёта берём только счётчики: время выполнения от запуска к запуску разное
                "export_counts": dict(re.findall(r"(Schema|Elements|Assemblies|Storeys|Styles|Materials):\s*(\S+)", rep)),
                "export_valid": "Validation: OK" in rep,
            }
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
        for out_mode, mode in MODES:
            iname, ename = node_names(ver, mode)
            imp = net.createNode(imp_type, iname)
            imp.parm("file").set(ifc_path)
            imp.parm("output").set(out_mode)
            exp = net.createNode(exp_type, ename)
            exp.setInput(0, imp)
            check(not imp.errors(), "%s %s: импорт без ошибок %r" % (imp_type, mode, imp.errors()[:1]))
    state = snapshot(net, out_dir)
    for ver in vers:
        # у выпущенной версии есть своя замороженная копия; номер в разработке работает от общего пакета
        frozen = "hifc_%s" % ver.replace(".", "_")
        want = frozen if os.path.isdir(os.path.join(ROOT, "python3.13libs", frozen)) else "hifc"
        check(package_of(ver) == want, "ассеты ::%s вызывают пакет %s (ожидали %s)" % (ver, package_of(ver), want))
        for _, mode in MODES:
            st = state.get("%s|%s" % (ver, mode), {})
            check(st.get("prims", 0) > 0 and st.get("export_valid"),
                  "::%s %s: %s примитивов, экспорт валиден" % (ver, mode, st.get("prims")))
        packed = state["%s|packed" % ver]["packed"]
        polys = state["%s|polys" % ver]["packed"]
        check(packed > 0 and polys == 0, "::%s: Packed даёт packed-примитивы (%d), Polygons — нет (%d)"
              % (ver, packed, polys))
        bbs = {m: state["%s|%s" % (ver, m)]["bbox"] for _, m in MODES}
        check(len({tuple(b) for b in bbs.values()}) == 1, "::%s: габариты совпадают во всех режимах: %r" % (ver, bbs))
    # между версиями результат тоже должен совпадать
    for _, mode in MODES:
        same = {tuple(state["%s|%s" % (v, mode)]["bbox"]) for v in vers}
        check(len(same) == 1, "режим %s: габариты одинаковы у всех версий (%r)" % (mode, same))
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
    for key in before:
        ver, mode = key.split("|")
        imp = net.node(node_names(ver, mode)[0])
        check(imp is not None and imp.type().name() == before[key]["type"],
              "%s нода осталась своей версии (%s)" % (key, imp.type().name() if imp else "нет ноды"))
    after = snapshot(net, os.path.dirname(os.path.abspath(hip)))
    for key, st in before.items():
        now = after.get(key, {})
        diff = [k for k in ("package", "parms", "prims", "points", "packed", "bbox", "prim_attribs",
                            "detail_attribs", "groups", "guid", "psets", "export_counts")
                if json.dumps(now.get(k), sort_keys=True, default=str) != json.dumps(st.get(k), sort_keys=True, default=str)]
        check(not diff, "%s: после перезапуска совпадает всё (расходится: %r)" % (key, diff))
        check(now.get("export_valid"), "%s: экспорт из открытой сцены валиден" % key)
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
