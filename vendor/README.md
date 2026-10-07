# vendor/

Third-party modules live here per platform, e.g. `vendor/py313-macos-arm64/`, `vendor/py313-win-x64/`,
`vendor/py313-linux-x64/`. NumPy is **not** installed here — Houdini ships its own.

Install from Houdini: **HIFC › Install / Update ifcopenshell**. It installs exactly the versions pinned in
`python3.13libs/hifc/__init__.py` (`VENDOR`) with `--no-deps`, the same set that is recorded in `VERSIONS.json`.

Manually (Houdini 22 uses Python 3.13; pick the folder for your platform):

```bash
# macOS Apple Silicon
pip install --target vendor/py313-macos-arm64 --platform macosx_11_0_arm64 \
    --python-version 3.13 --only-binary=:all: --implementation cp --no-deps \
    ifcopenshell==0.8.5 \
    shapely==2.1.2 \
    isodate==0.7.2 \
    python-dateutil==2.9.0.post0 \
    six==1.17.0 \
    lark==1.3.1 \
    typing-extensions==4.16.0
# Windows x64: --target vendor/py313-win-x64 --platform win_amd64
# Linux x64:   --target vendor/py313-linux-x64 --platform manylinux_2_28_x86_64
```

Changing a module version is a deliberate step: install it, run the full regression on every installed asset
version, then update `VENDOR` in `__init__.py`, `VERSIONS.json`, this file, `THIRD_PARTY_NOTICES.md` and the
changelog in the same commit.

Everything in this folder is third-party software under its own licence (see `../THIRD_PARTY_NOTICES.md`).
It is excluded from git.
