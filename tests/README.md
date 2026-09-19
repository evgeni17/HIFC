# Tests

Test data is not stored in this repository. HIFC is tested with the official
**buildingSMART Certification datasets** (IFC2X3, IFC4, IFC4X3):
https://github.com/buildingSMART/Certification-datasets
(© buildingSMART International Ltd., CC BY 4.0).

```bash
python tests/fetch_datasets.py   # downloads the .ifc files into tests/datasets/
python tests/test_core.py        # regression tests of the core (units, description, materials, classes, colours)
python tests/roundtrip.py        # read -> write -> read on all datasets, field-by-field comparison
python tests/roundtrip.py --schema IFC2X3 --unit m   # other target schema / units
```

In Houdini (Python Shell or `hython`):

```python
exec(open("<HIFC>/tests/houdini_regression.py").read())   # HDA tests, packed/polygons x IFC4/IFC4X3/IFC2X3
```

The scripts return exit code 1 on unexpected differences. Documented conversions are counted separately:
`IfcSurfaceFeature` -> proxy (no host relation yet), non-storey spatial containers -> `IfcBuildingStorey`,
empty names -> path leaf, classes missing in the target schema -> proxy.

Reference result (HIFC 0.2.0, IfcOpenShell 0.8.5, Houdini 22.0.429, macOS arm64):
`test_core.py` passed; `roundtrip.py` 35/35 without unexpected differences for IFC4/IFC4X3 (mm and m) and IFC2X3;
`houdini_regression.py` passed; HDA packed round trip of all 35 files keeps path, description, materials and
transparency. All written files pass `ifcopenshell.validate`.
