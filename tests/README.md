# Tests

Test data is not stored in this repository. HIFC is tested with the official
**buildingSMART Certification datasets** (IFC2X3, IFC4, IFC4X3):
https://github.com/buildingSMART/Certification-datasets
(© buildingSMART International Ltd., CC BY 4.0).

```bash
python tests/fetch_datasets.py   # downloads the .ifc files into tests/datasets/
python tests/roundtrip.py        # read -> write -> read, compares GlobalId/path, validates output
```

`roundtrip.py` needs a Python with `ifcopenshell` installed. In Houdini you can
also point **HIFC IFC Import** at any file in `tests/datasets/`.

Reference result (HIFC 0.1.0, IfcOpenShell 0.8.5, Houdini 22.0.429, macOS arm64):
35 files, all written files pass `ifcopenshell.validate`; 33/35 keep identical
GlobalId / path / class / bounding box. The two `Infra-Road` files differ by design:
`IfcSurfaceFeature` needs a host relation that HIFC does not write yet, so it is
exported as `IfcBuildingElementProxy` with `ObjectType = IfcSurfaceFeature`.
