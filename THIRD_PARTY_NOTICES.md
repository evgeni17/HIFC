# Third-party software

HIFC's own code is Apache-2.0 (see `LICENSE`). The repository contains **no**
third-party source code or binaries. HIFC imports the libraries below at runtime.
They are installed by the user into `vendor/<python>-<os>-<arch>/`
(menu **HIFC › Install / Update ifcopenshell**, or `pip install --target`),
and each keeps its own licence.

| Package | Licence | Project |
|---|---|---|
| ifcopenshell (IfcOpenShell) | LGPL-3.0-or-later | https://github.com/IfcOpenShell/IfcOpenShell |
| shapely | BSD-3-Clause | https://github.com/shapely/shapely |
| lark | MIT | https://github.com/lark-parser/lark |
| isodate | BSD-3-Clause | https://github.com/gweis/isodate |
| python-dateutil | Apache-2.0 OR BSD-3-Clause | https://github.com/dateutil/dateutil |
| six | MIT | https://github.com/benjaminp/six |
| typing_extensions | PSF-2.0 | https://github.com/python/typing_extensions |
| numpy (shipped with Houdini) | BSD-3-Clause | https://numpy.org |

## IfcOpenShell and the LGPL

HIFC uses IfcOpenShell only as a separately installed, unmodified library through
its public Python API (`import ifcopenshell`). Users can replace or upgrade it at
any time (menu **HIFC › Install / Update ifcopenshell**). HIFC contains no
IfcOpenShell code, so HIFC itself is not a derivative work and is licensed under
Apache-2.0.

**If you redistribute HIFC together with the `vendor/` folder** (for example a
ready-to-use zip in GitHub Releases), you are redistributing IfcOpenShell and
must also:

1. keep the `*.dist-info` folders of every package (they contain the licence files);
2. include the text of the GNU LGPL v3 and GNU GPL v3;
3. state where the corresponding IfcOpenShell source code can be obtained
   (https://github.com/IfcOpenShell/IfcOpenShell, tag `ifcopenshell-python-0.8.5`
   or the version you ship), and
4. not modify the IfcOpenShell files (or publish your modifications under LGPL).

## Bonsai

The Bonsai add-on for Blender (GPL-3.0) inspired the overall approach. HIFC
contains no Bonsai code.

## Houdini

Houdini is commercial software by SideFX; it is not included. The digital asset
files in `otls/` were created with a commercial Houdini licence and contain only
HIFC's own node interfaces and Python calls. They can be rebuilt from source with
**HIFC › Rebuild HDAs**.

## Test data

Test files are **not** included. Use the buildingSMART Certification datasets,
© buildingSMART International Ltd., licensed CC BY 4.0:
https://github.com/buildingSMART/Certification-datasets
