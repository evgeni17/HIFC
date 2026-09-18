# vendor/

IfcOpenShell and its dependencies are installed here per platform, e.g.
`vendor/py313-macos-arm64/`, `vendor/py313-win-x64/`, `vendor/py313-linux-x64/`.

Install from Houdini: **HIFC › Install / Update ifcopenshell**.

Or manually (Houdini 22 uses Python 3.13; pick the folder name for your platform):

```bash
# macOS Apple Silicon
pip install --target vendor/py313-macos-arm64 --platform macosx_11_0_arm64 \
    --python-version 3.13 --only-binary=:all: --implementation cp ifcopenshell
# Windows x64
pip install --target vendor/py313-win-x64 --platform win_amd64 \
    --python-version 3.13 --only-binary=:all: --implementation cp ifcopenshell
# Linux x64
pip install --target vendor/py313-linux-x64 --platform manylinux_2_28_x86_64 \
    --python-version 3.13 --only-binary=:all: --implementation cp ifcopenshell
```

Then delete the `numpy*` folders from the target: Houdini ships its own NumPy.

Everything in this folder is third-party software under its own licence
(see `../THIRD_PARTY_NOTICES.md`). It is excluded from git.
