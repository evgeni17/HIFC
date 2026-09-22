# Changelog

## 0.5.1 — 2026-09-22
* **`4@global_xform`** — the matrix of the top placement level (the root site, or the root building if there is no
  site) in scene axes and units, with `s@global_xform_source` naming where it comes from. Transform By Attribute with
  Attribute = `global_xform` and *Invert Transformation* moves the model to the origin; without Invert it moves it back.
* **Move to Origin** (import, off by default) does that move in double precision *before* positions are stored.
  Needed for far-away models: at 5,700 km the float32 step is half a metre, and a 200 mm wall imported in place
  collapses to zero thickness before any SOP can move it. With Move to Origin it arrives exact; `global_xform` keeps
  the original placement for the way back, `i@ifc_moved_to_origin` is set, and site/facility `xform` follow the moved
  geometry. Tested with a synthetic model placed 5,700 km from the origin.

## 0.5.0 — 2026-09-22
* **Top levels of the file in detail attributes.** Import now reads where the model sits in the world and how its
  sites and buildings are placed:
  `s@ifc_crs`, `d@ifc_georef` (IfcMapConversion + IfcProjectedCRS in IFC4/IFC4X3, the `ePSet_MapConversion` /
  `ePSet_ProjectedCRS` convention in IFC2X3; map origin in metres, map rotation, true north, WCS, precision),
  `d@ifc_project` (name, GUID, phase, unit scales), `d[]@ifc_sites` (latitude/longitude in decimal degrees,
  reference elevation, land title, address, property sets) and `d[]@ifc_facilities` (buildings; bridges, roads,
  railways in IFC4X3; elevations, parent site). Sites and facilities carry their placement twice: `ifc_matrix` as in
  the file (IFC axes, metres) and `xform` in scene axes and units, ready for `hou.Matrix4`. All lengths in metres.
* The map offset is deliberately not applied to the geometry (float32 precision); it is available for later use.
* **File Info** shows the CRS, map origin and rotation, true north, and site/facility origins.
* New `tests/georef_fixture.py` (georeferenced IFC4 and IFC2X3 test files); `test_core.py` checks every value,
  `houdini_regression.py` checks the detail attributes, the `xform` matrices against the geometry, and the disk cache.

## 0.4.1 — 2026-09-21
Fixes from the second independent test report (HIFC-test-v02) and the stricter tests it asked for:
* **Units of an overridden property.** If an occurrence overrode a property of its type with a dimensionless
  value while another property of the same set stayed measured, the fast property reader kept the inherited
  LENGTH/AREA/VOLUME mark: `IfcReal(7)` came back as `IfcLengthMeasure(7000)` in a millimetre project.
  Marks inherited from the type are now dropped for every property the occurrence overrides. The bug came in
  with the fast reader in 0.3.0; the reference reader was right all along, and the two are now compared by a test.
* **Complex and table properties are no longer dropped in silence.** `IfcComplexProperty` is imported flattened
  (`Nested.Child`); `IfcPropertyTableValue`, `IfcPropertyReferenceValue` and the like are counted and reported
  through a new warning channel — a node warning plus the `ifc_warnings` detail attribute, also shown by
  **File Info**. The supported set of property types is now written out in the node help and the README.
* **Round-trip comparison hardened** — it used to pass things it should not have:
  element sets are compared both ways (extra and duplicated elements are errors now), colours are compared as
  the area each colour covers (a swap between faces no longer passes) over unique faces, measure marks are
  compared as well as values, and a class may only be replaced by a proxy when the writer's own rule says so
  (`downgrade_reason`) — the blanket "schemas differ, so anything goes" exemption is gone.
  `tests/test_core.py` now contains negative tests: every one of those mutations must fail the comparison.
  All 35 certification files still pass in both `auto`/mm and `IFC2X3`/cm under the strict rules.
* On a class downgrade the element's own ObjectType is kept; the original class goes into ObjectType only when
  the element has none.
* `world_verts()` uses `einsum`: on macOS/arm64 the BLAS path raised spurious divide-by-zero and overflow flags
  on ordinary rotation matrices. Verified bit-identical results.

## 0.4.0 — 2026-09-21
* **Instancing of repeated geometry.** IFC stores repeated objects (identical windows, doors, furniture) as one
  geometry plus a placement matrix per occurrence (`IfcRepresentationMap` / `IfcMappedItem`, `IfcLocalPlacement`).
  The importer now keeps that: such geometry is created once and placed as packed copies, so no transforms have to
  be guessed. New **Output: Auto (instance repeated geometry)** — now the default — packs only the repeated
  geometry and leaves everything else as plain polygons, because packing every element slows the viewport down
  instead of speeding it up. **Instance From N Copies** sets the threshold (default 2).
  Measured on the 49 MB test model (3,569 elements, 260k triangles): 246 elements share 58 geometries,
  45,896 triangles displayed from 15,949 stored, 260,091 primitives in the scene drop to 214,441 (-18%),
  same cook time as Polygons (0.9 s). The gain scales with how much a model repeats.
* Import writes two primitive groups: `ifc_packed` (packed copies of repeated geometry) and `ifc_polygons`
  (plain polygons), so instances can be separated from the rest with one Blast.
* The importer reads geometry in local coordinates and keeps the IFC placement matrix (`matrix`, `geom_id` in the
  element record, `ifc_read.world_verts()` for world coordinates).
* Disk cache: the key now carries a record-format number, so a cache written by an older version can no longer
  return records without the new fields.
* New `tests/mem_bench.py` (memory and time of one import mode in a separate process); `tests/perf_bench.py` gained
  the `auto` stage; `tests/houdini_regression.py` checks instancing against the Polygons output and a re-export.

## 0.3.0 — 2026-09-20
Performance (measured on a 49 MB IFC2X3 model: 3,569 elements, 260k triangles, Houdini 22, Apple Silicon):
* Import, Polygons output: 49 s -> 1.1 s. Elements are built once as packed primitives and unpacked in C++
  (property dictionaries used to be written onto every triangle).
* Import, repeat open of an unchanged file (new session too): 7.1 s -> 0.9 s with the new **Disk Cache**
  (`$HOUDINI_TEMP_DIR/hifc_cache`, button *Clear Disk Cache*).
* Import: property sets are read ~1.7x faster (index access, type property sets cached);
  new **Property Sets** filter (e.g. `Pset_* Qto_*`, `* ^ArchiCADProperties`).
* Export: 35 s -> 12.5 s. Triangle-only elements are written as `IfcTriangulatedFaceSet`, property sets are
  created without per-call API overhead, dictionaries are read once per element, polygon vertices are read
  in one buffer (new `PREP` node inside the export HDA). New **Property Sets to Export** filter.
* `tests/perf_bench.py`: stage-by-stage benchmark to run in a separate `hython`.

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
