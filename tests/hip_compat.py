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
    """Небольшая модель, записанная текущим (разрабатываемым) писателем: три элемента, разные классы,
    этажи, материалы, свойства и по два цвета на элемент — чтобы поэлементному сравнению было что сверять."""
    import numpy as np
    from hifc import ifc_write

    def box(w, d, h, off):
        v = np.array([[x, y, z] for x in (0, w) for y in (0, d) for z in (0, h)], float) + np.array(off, float)
        f = [[0, 2, 3, 1], [4, 5, 7, 6], [0, 1, 5, 4], [2, 6, 7, 3], [0, 4, 6, 2], [1, 3, 7, 5]]
        return v, f

    els = []
    specs = [("/Frame/Wall_1", "IfcWall", "L0", ["Concrete"], (2.0, 0.2, 4.0), (0, 0, 0),
              {"Qto_WallBaseQuantities": {"Length": 2.0}}, {"Qto_WallBaseQuantities": {"Length": "LENGTH"}}),
             ("/Frame/Slab_1", "IfcSlab", "L1", ["Concrete", "Insulation"], (3.0, 3.0, 0.3), (0, 0, 4.0),
              {"Pset_SlabCommon": {"IsExternal": True, "Reference": "S-1"}}, {}),
             ("/Frame/Column_1", "IfcColumn", "L0", ["Steel"], (0.4, 0.4, 4.0), (4.0, 0, 0),
              {"Pset_ColumnCommon": {"Reference": "C-1"}}, {})]
    for path_, cls, storey, mats, size, off, psets, measures in specs:
        v, f = box(*size, off=off)
        els.append({"path": path_, "ifc_class": cls, "ifc_storey": storey, "name": path_.rsplit("/", 1)[1],
                    "description": "compat", "materials": mats, "psets": psets, "measures": measures,
                    "items": [{"verts": v, "faces": f[:3], "color": (0, 0, 1, 1)},
                              {"verts": v, "faces": f[3:], "color": (1, 0, 0, 1)}]})
    ifc_write.write_ifc(els, path, {"schema": "IFC4"})
    return path


MODES = ((0, "packed"), (1, "polys"), (2, "auto"))


def _prim_color(geo_or_prim, prim):
    """Цвет примитива (RGBA) или None."""
    g = prim.geometry() if hasattr(prim, "geometry") else geo_or_prim
    col = tuple(round(float(x), 3) for x in prim.attribValue("Cd")) if g.findPrimAttrib("Cd") else None
    if col is None:
        return None
    alpha = round(float(prim.attribValue("Alpha")), 3) if g.findPrimAttrib("Alpha") else 1.0
    return col + (alpha,)


def _tri_data(geo, prim):
    """Треугольники примитива: (площадь, центр в мировых координатах, цвет).

    У packed-примитива цвета лежат на гранях вложенной геометрии, а не на нём самом —
    иначе сравнение в режимах Packed и Auto видело бы по одному цвету на элемент.
    """
    import numpy as np
    out = []
    if prim.type() == hou.primType.PackedGeometry:
        emb = prim.getEmbeddedGeometry()
        m = prim.fullTransform()
        own = _prim_color(geo, prim)
        faces = [([hou.Vector3(v.point().position()) * m for v in sub.vertices()],
                  _prim_color(emb, sub) or own) for sub in emb.prims()]
    else:
        faces = [([hou.Vector3(v.point().position()) for v in prim.vertices()], _prim_color(geo, prim))]
    for pts, col in faces:
        if len(pts) < 3:
            continue
        a, b, c = (np.array(pts[0]), np.array(pts[1]), np.array(pts[2]))
        area = 0.5 * float(np.linalg.norm(np.cross(b - a, c - a)))
        cen = sum(np.array(p) for p in pts) / len(pts)
        out.append((area, cen, col))
    return out


def element_signatures(geo):
    """По каждому элементу (GUID): класс, этаж, материалы, свойства, геометрия и раскладка цветов.

    Цвет сравнивается не палитрой, а площадью и её центром по каждому цвету — так видно и потерю цвета,
    и перестановку цветов между гранями. Геометрия — число треугольников, суммарная площадь и габариты.
    """
    import numpy as np
    if geo.findPrimAttrib("ifc_guid") is None:
        return {}
    has = lambda n: geo.findPrimAttrib(n) is not None
    out = {}
    for prim in geo.prims():
        guid = prim.attribValue("ifc_guid")
        e = out.setdefault(guid, {"tris": 0, "area": 0.0, "lo": None, "hi": None, "colors": {},
                                  "class": prim.attribValue("ifc_class") if has("ifc_class") else "",
                                  "storey": prim.attribValue("ifc_storey") if has("ifc_storey") else "",
                                  "name": prim.attribValue("ifc_name") if has("ifc_name") else "",
                                  "materials": sorted(prim.attribValue("ifc_materials")) if has("ifc_materials") else [],
                                  "psets": str(prim.attribValue("ifc_psets")) if has("ifc_psets") else "",
                                  "measures": str(prim.attribValue("ifc_measures")) if has("ifc_measures") else ""})
        for area, cen, col in _tri_data(geo, prim):
            e["tris"] += 1
            e["area"] += area
            e["lo"] = cen if e["lo"] is None else np.minimum(e["lo"], cen)
            e["hi"] = cen if e["hi"] is None else np.maximum(e["hi"], cen)
            if col is not None:
                a, mom = e["colors"].get(col, (0.0, np.zeros(3)))
                e["colors"][col] = (a + area, mom + area * cen)
    sig = {}
    for guid, e in out.items():
        colors = {str(c): [round(a, 5), [round(float(x), 4) for x in (mom / max(a, 1e-12))]]
                  for c, (a, mom) in sorted(e["colors"].items())}
        sig[guid] = {"class": e["class"], "storey": e["storey"], "name": e["name"], "materials": e["materials"],
                     "psets": e["psets"], "measures": e["measures"], "tris": e["tris"], "area": round(e["area"], 5),
                     "centres": [[round(float(x), 4) for x in e["lo"]], [round(float(x), 4) for x in e["hi"]]]
                     if e["lo"] is not None else [], "colors": colors}
    return sig


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
                "elements": element_signatures(g),
            }
    return state


def self_check(state):
    """Отрицательные проверки: сравнение элементов обязано ловить подмены."""
    import copy
    # берём состояние с самой богатой раскраской: на нём видно и перестановку цветов
    base = max((st["elements"] for st in state.values() if st["elements"]),
               key=lambda els: max((len(e["colors"]) for e in els.values()), default=0), default={})
    check(len(base) >= 3, "в эталоне несколько элементов (%d)" % len(base))
    if not base:
        return
    guid = max(base, key=lambda g: len(base[g]["colors"]))

    def mutated(fn):
        b = copy.deepcopy(base)
        fn(b)
        return element_diff(base, b)

    cases = [
        ("пропавший элемент", lambda b: b.pop(sorted(b)[1])),
        ("лишний элемент", lambda b: b.setdefault("0extraGUID0extraGUID00", copy.deepcopy(b[guid]))),
        ("другой класс", lambda b: b[guid].__setitem__("class", "IfcBeam")),
        ("другой этаж", lambda b: b[guid].__setitem__("storey", "L9")),
        ("другой материал", lambda b: b[guid].__setitem__("materials", ["Wood"])),
        ("другое свойство", lambda b: b[guid].__setitem__("psets", "{'Pset_X': {'A': 1}}")),
        ("меньше треугольников", lambda b: b[guid].__setitem__("tris", b[guid]["tris"] - 1)),
        ("другая площадь", lambda b: b[guid].__setitem__("area", b[guid]["area"] * 1.01)),
        ("пропавший цвет", lambda b: b[guid]["colors"].pop(sorted(b[guid]["colors"])[0])),
        ("цвета переставлены", lambda b: b[guid].__setitem__(
            "colors", {k: v for k, v in zip(sorted(b[guid]["colors"]), reversed(list(b[guid]["colors"].values())))})),
    ]
    for name, fn in cases:
        found = mutated(fn)
        check(bool(found), "сравнение ловит: %s (%s)" % (name, found[0] if found else "ПРОПУЩЕНО"))


def element_diff(a, b, tol=1e-4):
    """Расхождения подписей элементов: пропавшие, лишние и отличающиеся поля."""
    diffs = []
    for guid in sorted(set(a) - set(b)):
        diffs.append("%s: элемент пропал" % guid)
    for guid in sorted(set(b) - set(a)):
        diffs.append("%s: лишний элемент" % guid)
    for guid in sorted(set(a) & set(b)):
        x, y = a[guid], b[guid]
        for key in ("class", "storey", "name", "materials", "psets", "measures", "tris"):
            if json.dumps(x.get(key), sort_keys=True, default=str) != json.dumps(y.get(key), sort_keys=True, default=str):
                diffs.append("%s: %s %r -> %r" % (guid, key, x.get(key), y.get(key)))
        if abs(float(x["area"]) - float(y["area"])) > tol * max(1.0, float(x["area"])):
            diffs.append("%s: площадь %.5f -> %.5f" % (guid, x["area"], y["area"]))
        if set(x["colors"]) != set(y["colors"]):
            diffs.append("%s: цвета %r -> %r" % (guid, sorted(x["colors"]), sorted(y["colors"])))
        else:
            for c, (area, cen) in x["colors"].items():
                area2, cen2 = y["colors"][c]
                if abs(area - area2) > tol * max(1.0, area) or max(abs(p - q) for p, q in zip(cen, cen2)) > 1e-3:
                    diffs.append("%s: цвет %s — площадь %.5f -> %.5f, центр %r -> %r" % (guid, c, area, area2, cen, cen2))
    return diffs


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
    # между версиями результат должен совпадать поэлементно, в каждом режиме
    base_ver = min(vers)
    for _, mode in MODES:
        same = {tuple(state["%s|%s" % (v, mode)]["bbox"]) for v in vers}
        check(len(same) == 1, "режим %s: габариты одинаковы у всех версий (%r)" % (mode, same))
        base = state["%s|%s" % (base_ver, mode)]["elements"]
        for v in vers:
            if v == base_ver:
                continue
            diff = element_diff(base, state["%s|%s" % (v, mode)]["elements"])
            check(not diff, "режим %s: ::%s совпадает с ::%s поэлементно (%d элементов, расхождения: %r)"
                  % (mode, v, base_ver, len(base), diff[:3]))
    self_check(state)
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
        # сравниваем только то, что было записано в снимке: эталон старого выпуска мог хранить меньше полей
        diff = [k for k in ("package", "parms", "prims", "points", "packed", "bbox", "prim_attribs",
                            "detail_attribs", "groups", "guid", "psets", "export_counts", "elements")
                if k in st
                and json.dumps(now.get(k), sort_keys=True, default=str) != json.dumps(st.get(k), sort_keys=True, default=str)]
        check(not diff, "%s: после перезапуска совпадает всё (расходится: %r)" % (key, diff))
        check(now.get("export_valid"), "%s: экспорт из открытой сцены валиден" % key)
        if "elements" in diff:
            for line in element_diff(st.get("elements", {}), now.get("elements", {}))[:5]:
                print("       %s" % line)
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
