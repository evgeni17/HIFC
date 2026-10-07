#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 EOK
# SPDX-License-Identifier: Apache-2.0
"""Установка HIFC из папки разработки в рабочую папку плагина.

    python3 deploy.py [<папка установки>]      # по умолчанию ~/tools_houdini/HIFC
    python3 deploy.py --dry-run                # только показать, что будет сделано
    python3 deploy.py --clean                  # удалить файлы, которые ставил прежний запуск и которых больше нет

Копируются только изменённые файлы. В установку пишется INSTALL.json: версия, коммит, дата и список файлов —
по нему же работает --clean, поэтому чужие файлы в установке скрипт не трогает никогда.
vendor/ не трогаем: библиотеки ставит пользователь из меню плагина (они не в git).
"""
import argparse
import datetime
import filecmp
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_TARGET = os.path.expanduser("~/tools_houdini/HIFC")
INSTALL_JSON = "INSTALL.json"

SKIP_DIRS = {".git", "__pycache__", "backup", ".idea", ".vscode", "vendor"}
# test_repo.py проверяет сам репозиторий (vendor/README.md, VERSIONS.json) — в установке ему нечего делать
SKIP_REL = {"deploy.py", ".gitignore", ".gitattributes", ".DS_Store", os.path.join("tests", "test_repo.py"),
            os.path.join("tests", "private"), os.path.join("tests", "out"),
            os.path.join("tests", "datasets"), os.path.join("tests", "big")}
SKIP_SUFFIX = (".pyc", ".hip", ".hiplc", ".hipnc")


def _skipped(rel):
    parts = rel.split(os.sep)
    if any(p in SKIP_DIRS for p in parts) or rel.endswith(SKIP_SUFFIX):
        return True
    return any(rel == s or rel.startswith(s + os.sep) for s in SKIP_REL)


def source_files(root):
    out = []
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            rel = os.path.relpath(os.path.join(base, f), root)
            if not _skipped(rel):
                out.append(rel)
    return sorted(out)


def git_commit(root):
    def git(*a):
        return subprocess.run(["git", "-C", root] + list(a), capture_output=True, text=True).stdout.strip()
    sha = git("rev-parse", "--short", "HEAD")
    if not sha:
        return ""
    return sha + ("+local" if git("status", "--porcelain") else "")


def plugin_info(root):
    """__version__ и HDA_VERSION читаем из исходника, не импортируя пакет (hou здесь нет)."""
    src = open(os.path.join(root, "python3.13libs", "hifc", "__init__.py")).read()
    out = {}
    for key in ("__version__", "HDA_VERSION"):
        for line in src.splitlines():
            if line.startswith(key):
                out[key] = line.split("=", 1)[1].strip().strip('"')
                break
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("target", nargs="?", default=DEFAULT_TARGET)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--clean", action="store_true", help="удалить файлы прежней установки, исчезнувшие из разработки")
    args = ap.parse_args()
    target = os.path.abspath(os.path.expanduser(args.target))
    if os.path.abspath(HERE) == target:
        print("deploy: target is the development folder itself — nothing to do")
        return 1

    files = source_files(HERE)
    copied = unchanged = 0
    for rel in files:
        src, dst = os.path.join(HERE, rel), os.path.join(target, rel)
        same = os.path.isfile(dst) and filecmp.cmp(src, dst, shallow=False)
        if same:
            unchanged += 1
            continue
        copied += 1
        print("  copy %s" % rel)
        if not args.dry_run:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)

    old = {}
    try:
        old = json.load(open(os.path.join(target, INSTALL_JSON)))
    except Exception:
        pass
    stale = [r for r in old.get("files", []) if r not in files]
    failed = []
    for rel in stale:
        p = os.path.join(target, rel)
        print("  %s %s" % ("remove" if args.clean else "stale ", rel))
        if args.clean and not args.dry_run and os.path.isfile(p):
            try:
                os.remove(p)
            except OSError as ex:
                failed.append("%s (%s)" % (rel, ex.strerror or ex))

    info = dict(plugin_info(HERE), name="HIFC", commit=git_commit(HERE),
                date=datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
                source=HERE, files=files)
    if not args.dry_run:
        os.makedirs(target, exist_ok=True)
        with open(os.path.join(target, INSTALL_JSON), "w") as fh:
            json.dump(info, fh, indent=1, ensure_ascii=False)
            fh.write("\n")
    print("deploy %s -> %s: copied %d, unchanged %d, stale %d%s%s"
          % (info.get("__version__", "?"), target, copied, unchanged, len(stale),
             " (dry run)" if args.dry_run else ("" if not args.clean else ", removed"),
             ("; could not remove: " + ", ".join(failed)) if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
