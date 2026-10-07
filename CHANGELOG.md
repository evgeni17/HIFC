# Changelog

## 0.7.0-dev.2 — 2026-10-07
* **Compatibility is now compared element by element.** `tests/hip_compat.py` records, for every element (by GUID):
  class, storey, name, materials, property sets and measures, triangle count, total area, the span of its face
  centres, and per colour the area it covers with the centre of that area. Packed primitives are opened so face
  colours are seen in Packed and Auto as well, not just the one colour of the packed primitive. Asset versions are
  compared against each other per element in every output mode, and the same comparison runs after the scene is
  reopened. Ten negative self-checks run on every build: a missing element, an extra one, a changed class, storey,
  material, property, triangle count, area, a lost colour and colours swapped between faces must all be reported.
  The sample model grew to three elements with different classes, storeys, materials, properties and two colours each.
* `freeze.py --archive N.M` packs the release reference (scene, IFC, snapshot, `VERSIONS.json`) into
  `dist/hifc_N.M_reference.zip`; releases on GitHub carry it as an attachment, and the procedure is in CONTRIBUTING.
* Reopening a scene compares only the fields its snapshot recorded, so a reference saved by an older release still
  checks out against a newer plugin.

## 0.7.0-dev.1 — 2026-10-07
* Development moved to assets `::7.0` (`freeze.py --next 7.0`, which also raised the plugin version). `::6.0` and
  `::1.0` stay frozen and keep serving the scenes that use them. No behaviour changes yet.
* Checked with all three asset versions installed at once: core, the Houdini regression, a scene holding nodes of
  every version in every output mode, and the `0.6.0` reference scene reopened after the update — unchanged.

## 0.6.0 — 2026-10-07
First release with versioned, frozen assets. Nothing in import or export changed since 0.5.1; this release is about
scenes staying reproducible.
* **Assets `::6.0`, frozen.** The release code lives in `python3.13libs/hifc_6_0` (`FROZEN = True`) and the
  `hifc::ifc_import::6.0` / `hifc::ifc_export::6.0` assets are built from it, so a node in a scene always runs the
  code it was released with. `FROZEN.sha256` records every file and both HDAs; `VERSIONS.json` records the plugin
  version, the pinned module set, the Houdini and Python versions it was verified with.
* **`::1.0` stays available** for scenes made before versioning, running its own frozen `hifc_1_0` package.
* **The release procedure cannot be bypassed:** a sealed version cannot be sealed or frozen again, and development
  cannot take a number that is frozen or not above everything already taken; `freeze.py --next` raises the plugin
  version itself, so that step cannot be skipped. `tests/test_freeze.py` covers all of it.
* **Reference scene.** `tests/hip_compat.py` now builds, for every installed asset version, import nodes in all
  three output modes (Packed, Polygons, Auto) and exports from each, checks that the bounds agree across modes and
  across versions, saves the scene, and reopens it in a separate process to compare parameters, geometry, groups,
  attributes, GUIDs, property sets and export counts. The saved `tests/reference/hifc_6_0_reference.hip` is the
  baseline for the next release.

## 0.6.0-dev.3 — 2026-10-07
Versioned, frozen assets — existing scenes keep the exact code they were built against:
* **The current code is frozen as `::1.0`.** `freeze.py 1.0` copied the package to `python3.13libs/hifc_1_0`
  (`FROZEN = True`), and the `hifc::ifc_import::1.0` / `hifc::ifc_export::1.0` assets were rebuilt from that copy:
  every button and the cook stub inside them import `hifc_1_0`, never the package that keeps changing.
  `freeze.py --seal 1.0` wrote `FROZEN.sha256` (package files and both HDAs) and the frozen record in
  `VERSIONS.json`. A frozen copy is never edited again; a fix for old scenes is a new asset version.
* **Development moved to `::6.0`** (`freeze.py --next 6.0`), matching the release rule 0.N -> `::N.0`.
  HDA files now carry the version in their name (`otls/hifc_ifc_import_6.0.hda`), so versions live side by side;
  `build_all` refuses to rebuild a frozen package without `force=True`.
* **Dependencies across versions.** IfcOpenShell is one library per Houdini session, so each asset version records
  the set it was verified with (`vendor`, plus `also_tested` for later sets); `tests/test_frozen.py` checks that the
  installed set is among them, and the nodes already warn when the installed modules differ from the pinned ones.
* **New `tests/hip_compat.py`**: builds a scene with nodes of every installed asset version, checks which package
  each one calls, exports from both, saves the scene, and reopens it in a **separate process** to compare
  parameters, geometry, attributes, GUIDs, property sets and the export — nodes stay on their own version, nothing
  upgrades itself. New `tests/test_frozen.py`: checksums, no leaks from a frozen copy to the development package,
  complete `VERSIONS.json`, development version ahead of every frozen one.

## 0.6.0-dev.2 — 2026-10-07
Two gaps found in review, both with tests that fail without the fix:
* `deploy.py` no longer forgets a stale file it could not delete: unremoved files stay in `INSTALL.json` as
  `pending_removal` until a later `--clean` actually removes them. New `tests/test_deploy.py` covers install,
  re-install, stale bookkeeping across runs, foreign files and `--dry-run`.
* The round-trip colour check compares, per colour, the area **and the area-weighted centre and bounds** of the faces
  it covers, instead of the area alone: swapping colours between faces of equal area used to pass. The measure does
  not depend on how the surface is triangulated, so re-tessellation on export still compares clean (35/35 in both
  `auto`/mm and `IFC2X3`/cm). `tests/test_core.py` has the equal-area swap as a negative test.

## 0.6.0-dev.1 — 2026-10-07
Repository and installation hygiene (no change to import/export behaviour):
* **Pinned dependency versions.** `VENDOR` in `python3.13libs/hifc/__init__.py` is now the single place that says
  which versions HIFC is tested with: ifcopenshell 0.8.5, shapely 2.1.2, isodate 0.7.2, python-dateutil 2.9.0.post0,
  six 1.17.0, lark 1.3.1, typing-extensions 4.16.0 (NumPy comes from Houdini). **HIFC › Install / Update
  ifcopenshell** installs exactly those with `--no-deps`; the nodes warn when what is installed differs, and
  **About** lists pinned against installed. The same set is recorded in the new `VERSIONS.json`, in
  `vendor/README.md` and in `THIRD_PARTY_NOTICES.md`.
* **`deploy.py`** installs the plugin from the repository into the working folder (`~/tools_houdini/HIFC` by default),
  copying only changed files and writing `INSTALL.json` (version, commit, date, file list). `--clean` removes files a
  previous install left behind, `--dry-run` shows what would happen. The repository is never loaded by Houdini.
* **Node type names** come from `IMPORT_TYPE` / `EXPORT_TYPE` (built from `HDA_VERSION`), including the tests.
* **Node help is bilingual in one page**: English first, the same text in Russian below. `HIFC_HELP_LANG` is gone —
  the repository and the installed copy now hold identical HDAs.
* New `tests/test_repo.py`: dependency versions agree across all the places that record them, no hard-coded type
  names, banner in both READMEs, help has both languages.

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
