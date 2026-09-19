# Changelog

## 0.2.0 — 2026-09-20
Fixes from the independent test report (HIFC-test-v01):
* **Transparency:** opaque elements no longer become fully transparent after a packed import -> export chain
  (Alpha is always written, default 1.0).
* **Face colours in packed mode:** the export Unpack no longer copies the packed primitive's `Cd`/`Alpha`/`ifc_style`
  over the per-face colours. New export parameter **Packed Colors** (*Per Face* / *Override*).
* **Units of quantities:** lengths, areas and volumes in property/quantity sets are converted to SI on import and
  marked in the new `d@ifc_measures` attribute; export converts them to the file units with proper IFC measure types.
  Values without a mark are written as is (project units), as before.
* **Description** is imported (`s@ifc_description`) and survives a round trip.
* **Several materials** are kept as a list (`s[]@ifc_materials`) and exported as `IfcMaterialConstituentSet`
  (`IfcMaterialList` in IFC2X3) instead of one material named "A, B".
* **Class check:** Check Attributes and the writer share one rule; non-product, abstract and spatial classes
  (e.g. `IfcMaterial`, `IfcWallType`) are reported as errors and exported as proxies instead of crashing.
* PredefinedType is taken from the element only; USERDEFINED keeps the user ObjectType.
* **Tests:** `tests/roundtrip.py` compares class, types, names, description, tag, storey, materials, psets (SI),
  face colours and bounding boxes, separates documented conversions, and returns exit code 1 on unexpected differences.
  New `tests/test_core.py` and `tests/houdini_regression.py` (packed/polygons x IFC4/IFC4X3/IFC2X3).

## 0.1.0 — 2026-09-18
* First public release.
* HIFC IFC Import: IFC2X3 / IFC4 / IFC4X3. Packed or polygon output; path, GUID, class, storey, material, style and psets as attributes.
* HIFC IFC Export: path-based assemblies, class rules, storeys, materials, surface styles, property sets and quantities; GlobalIds stay stable between exports.
* Check Attributes, attribute template wrangle, built-in guide (EN/RU).
* Tested with the buildingSMART Certification datasets.
