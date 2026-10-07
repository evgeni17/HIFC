#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 EOK
# SPDX-License-Identifier: Apache-2.0
"""Заморозка версии ассетов: неизменяемая копия пакета рядом с изменяемым.

    python3 freeze.py 1.0            # python3.13libs/hifc -> python3.13libs/hifc_1_0 (FROZEN, HDA_VERSION=1.0)
    python3 freeze.py --seal 1.0     # контрольные суммы + запись в VERSIONS.json (после сборки HDA)
    python3 freeze.py --next 6.0     # разработка переходит на следующую версию ассетов
    python3 freeze.py --archive 6.0  # dist/hifc_6.0_reference.zip: эталонная сцена, её IFC и снимок состояния

Порядок выпуска целиком (см. CONTRIBUTING.md):
    freeze.py N.M -> deploy.py -> в Houdini build_all(force=True, otls=<репозиторий>/otls) замороженной копии
    -> deploy.py -> freeze.py --seal N.M -> freeze.py --next <следующая> -> deploy.py -> build_all -> deploy.py

Замороженная копия после запечатывания не редактируется никогда: ноды этой версии в чужих сценах должны
вызывать ровно тот код, с которым их проверяли. Нужное старым сценам исправление — это новая версия ассетов.
"""
import argparse
import datetime
import hashlib
import json
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LIBS = os.path.join(HERE, "python3.13libs")
PKG = "hifc"
SUMS = "FROZEN.sha256"


def pkg_name(version):
    return "%s_%s" % (PKG, version.replace(".", "_"))


def read_const(path, name):
    for line in open(path):
        if line.startswith(name):
            return line.split("=", 1)[1].strip().strip('"')
    return ""


def set_const(text, name, value, quote=True):
    v = '"%s"' % value if quote else value
    return re.sub(r"(?m)^%s\s*=.*$" % re.escape(name), "%s = %s" % (name, v), text, count=1)


def files_of(folder):
    out = []
    for base, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for f in sorted(files):
            if f.endswith(".pyc") or f == SUMS:
                continue
            out.append(os.path.relpath(os.path.join(base, f), folder))
    return sorted(out)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def freeze(version):
    src = os.path.join(LIBS, PKG)
    dst = os.path.join(LIBS, pkg_name(version))
    if os.path.isdir(dst):
        print("freeze: %s already exists — a frozen version is never re-created" % os.path.basename(dst))
        return 1
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    init = os.path.join(dst, "__init__.py")
    text = open(init).read()
    text = set_const(text, "HDA_VERSION", version)
    text = set_const(text, "FROZEN", "True", quote=False)
    open(init, "w").write(text)
    # внутри пакета ссылки относительные; на всякий случай переписываем абсолютные
    renamed = []
    for rel in files_of(dst):
        if not rel.endswith(".py"):
            continue
        p = os.path.join(dst, rel)
        t = open(p).read()
        t2 = re.sub(r"\b(import|from)\s+%s\b(?!_)" % PKG, lambda m: "%s %s" % (m.group(1), pkg_name(version)), t)
        if t2 != t:
            open(p, "w").write(t2)
            renamed.append(rel)
    print("freeze: %s -> %s (HDA_VERSION=%s, FROZEN=True); module references rewritten in %d files"
          % (PKG, os.path.basename(dst), version, len(renamed)))
    print("next: deploy.py, then in Houdini  import %s.hda_build as b; b.build_all(force=True, otls=\"%s/otls\")"
          % (pkg_name(version), HERE))
    return 0


def seal(version):
    name = pkg_name(version)
    dst = os.path.join(LIBS, name)
    if not os.path.isdir(dst):
        print("seal: %s does not exist — run freeze.py %s first" % (name, version))
        return 1
    versions_path = os.path.join(HERE, "VERSIONS.json")
    sealed_before = json.load(open(versions_path))["assets"].get(version, {}).get("status") == "frozen"
    if os.path.isfile(os.path.join(dst, SUMS)) or sealed_before:
        # иначе запечатывание можно повторить поверх изменённого кода, и суммы перестанут что-либо значить
        print("seal: ::%s is already sealed (%s/%s). A sealed version is never re-sealed: "
              "if it needs a change, that is a new asset version." % (version, name, SUMS))
        return 1
    otls = [f for f in sorted(os.listdir(os.path.join(HERE, "otls"))) if f.endswith("_%s.hda" % version)]
    if not otls:
        print("seal: no otls/*_%s.hda — build the frozen assets first" % version)
        return 1
    sums = {os.path.join(name, rel): sha256(os.path.join(dst, rel)) for rel in files_of(dst)}
    sums.update({os.path.join("otls", f): sha256(os.path.join(HERE, "otls", f)) for f in otls})
    with open(os.path.join(dst, SUMS), "w") as fh:
        for k in sorted(sums):
            fh.write("%s  %s\n" % (sums[k], k))

    versions = json.load(open(versions_path))
    dev = versions["assets"].get(read_const(os.path.join(LIBS, PKG, "__init__.py"), "HDA_VERSION"), {})
    rec = versions["assets"].get(version, {})
    rec.update({
        "status": "frozen",
        "package": name,
        "plugin": read_const(os.path.join(dst, "__init__.py"), "__version__"),
        "vendor": json.loads(json.dumps(dev.get("vendor", {}))) if dev.get("vendor") else rec.get("vendor", {}),
        "houdini": dev.get("houdini", rec.get("houdini", "")),
        "python": dev.get("python", rec.get("python", "")),
        "assets": otls,
        "sealed": datetime.date.today().isoformat(),
        "also_tested": rec.get("also_tested", []),
    })
    versions["assets"][version] = rec
    json.dump(versions, open(os.path.join(HERE, "VERSIONS.json"), "w"), indent=2, ensure_ascii=False)
    open(os.path.join(HERE, "VERSIONS.json"), "a").write("\n")
    print("seal: %d files hashed into %s/%s; VERSIONS.json entry %s is frozen" % (len(sums), name, SUMS, version))
    print("next: freeze.py --next %s  (development must leave the released number)" % _suggest_next(version))
    return 0


def _suggest_next(version):
    major, minor = (int(x) for x in version.split("."))
    return "%d.0" % (major + 1)


def archive(version):
    """Архив эталона выпуска: HIP, исходный и экспортированные IFC, снимок состояния.

    Пересоздать сцену текущей версией плагина — не то же самое: исторический эталон должен остаться
    ровно таким, каким его записал выпуск. Архив кладётся в dist/ и прикладывается к релизу на GitHub.
    """
    import zipfile
    ref = os.path.join(HERE, "tests", "reference")
    hip = os.path.join(ref, "hifc_%s_reference.hip" % version.replace(".", "_"))
    if not os.path.isfile(hip):
        print("archive: %s not found — build it first: hython tests/hip_compat.py build %s" % (hip, hip))
        return 1
    dist = os.path.join(HERE, "dist")
    os.makedirs(dist, exist_ok=True)
    out = os.path.join(dist, "hifc_%s_reference.zip" % version)
    names = [f for f in sorted(os.listdir(ref))
             if f.endswith((".hip", ".json", ".ifc", ".md")) and not f.endswith(".hip.bak")]
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in names:
            z.write(os.path.join(ref, f), os.path.join("hifc_%s_reference" % version, f))
        z.writestr(os.path.join("hifc_%s_reference" % version, "VERSIONS.json"),
                   open(os.path.join(HERE, "VERSIONS.json")).read())
    print("archive: %s (%d files, %.1f KB)" % (out, len(names) + 1, os.path.getsize(out) / 1024.0))
    return 0


def next_version(version):
    """Разработка переходит на следующую версию ассетов (номер должен быть свободным и больше всех занятых)."""
    init = os.path.join(LIBS, PKG, "__init__.py")
    versions_all = json.load(open(os.path.join(HERE, "VERSIONS.json")))["assets"]
    taken = {v for v, r in versions_all.items() if r.get("status") == "frozen"}
    taken |= {os.path.basename(p)[len("hifc_"):].replace("_", ".") for p in
              __import__("glob").glob(os.path.join(LIBS, "hifc_*")) if os.path.isdir(p)}
    if version in taken:
        print("next: ::%s is already frozen — development may not take a released number" % version)
        return 1
    current = read_const(init, "HDA_VERSION")
    keyed = [tuple(int(x) for x in v.split(".")) for v in taken | {current}]
    if keyed and tuple(int(x) for x in version.split(".")) <= max(keyed):
        print("next: ::%s is not above what is already taken (frozen %r, development ::%s)"
              % (version, sorted(taken), current))
        return 1
    text = set_const(open(init).read(), "HDA_VERSION", version)
    open(init, "w").write(text)
    versions = json.load(open(os.path.join(HERE, "VERSIONS.json")))
    dev = [k for k, v in versions["assets"].items() if v.get("status") == "development"]
    if dev:
        rec = versions["assets"].pop(dev[0])
    else:
        # запись разработки стала замороженной (так бывает при переходе старого плагина на версии):
        # окружение берём у последней замороженной версии, оно же сейчас установлено
        base = sorted((v for v in versions["assets"].values() if v.get("status") == "frozen"),
                      key=lambda v: v.get("sealed", ""))[-1]
        rec = {"status": "development", "package": PKG,
               "vendor": dict(base.get("vendor", {})), "houdini": base.get("houdini", ""),
               "python": base.get("python", "")}
    rec["status"] = "development"
    rec["package"] = PKG
    rec.pop("assets", None)
    rec.pop("sealed", None)
    # версия плагина поднимается здесь же, чтобы шаг нельзя было забыть
    major, minor = (int(x) for x in version.split("."))
    plugin = "0.%d.%d.dev1" % (major, minor) if minor else "0.%d.0.dev1" % major
    text = set_const(open(init).read(), "__version__", plugin)
    open(init, "w").write(text)
    rec["plugin"] = plugin
    versions["assets"][version] = rec
    json.dump(versions, open(os.path.join(HERE, "VERSIONS.json"), "w"), indent=2, ensure_ascii=False)
    open(os.path.join(HERE, "VERSIONS.json"), "a").write("\n")
    print("development is now ::%s, plugin %s (was ::%s)" % (version, plugin, dev[0] if dev else "?"))
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("version", help="версия ассетов, например 1.0")
    ap.add_argument("--seal", action="store_true", help="посчитать суммы и записать версию в VERSIONS.json")
    ap.add_argument("--next", action="store_true", help="перевести разработку на эту версию ассетов")
    ap.add_argument("--archive", action="store_true", help="собрать dist/hifc_<версия>_reference.zip для релиза")
    args = ap.parse_args()
    if args.archive:
        return archive(args.version)
    if args.seal:
        return seal(args.version)
    if args.next:
        return next_version(args.version)
    return freeze(args.version)


if __name__ == "__main__":
    sys.exit(main())
