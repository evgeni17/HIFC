# HIFC — IFC import / export for Houdini

HIFC adds IFC import and export to SideFX Houdini as two SOP nodes. It uses
[IfcOpenShell](https://github.com/IfcOpenShell/IfcOpenShell), the same engine behind the
Bonsai add-on for Blender, and does not need Blender.

* **HIFC IFC Import** reads IFC2X3, IFC4 and IFC4X3. You get one packed primitive per element (or plain polygons), with
  `path`, GUID, class, storey, material, colour and all property sets as attributes.
* **HIFC IFC Export** writes polygons to IFC. Primitive attributes set the BIM structure (hierarchy, classes,
  storeys, materials, property sets). GlobalIds stay the same between exports.
* **Check Attributes** checks your attributes before export. An **attribute template** (Primitive Wrangle)
  and a built-in **guide** (press F1 on the export node) explain how to build a clean BIM structure.

Русская версия: [README.ru.md](README.ru.md).

## Requirements

* Houdini 22 (Python 3.13). Other versions should work if an IfcOpenShell wheel exists for their Python version.
* IfcOpenShell 0.8.x, installed into the plugin's `vendor/` folder (see below).

## Installation

1. Clone or download this repository (`git clone https://github.com/evgeni17/HIFC.git`), e.g. to `~/houdini_tools/HIFC`.
2. Copy `HIFC.json` to your Houdini packages folder
   (macOS `~/Library/Preferences/houdini/22.0/packages/`,
   Windows `%USERPROFILE%/Documents/houdini22.0/packages/`,
   Linux `~/houdini22.0/packages/`) and set `"HIFC"` to the path of the cloned folder.
   `"HIFC_HELP_LANG"` can be `en` or `ru`.
3. Start Houdini and run **HIFC › Install / Update ifcopenshell**, or install it manually (see `vendor/README.md`).
   Restart Houdini.
4. Run **HIFC › Rebuild HDAs** once if you changed `HIFC_HELP_LANG` or edited the node interface.

## Usage

* **Import:** **HIFC › Import IFC...** or Tab › HIFC IFC Import.
* **Export:** append **HIFC IFC Export** to your SOP chain. Set the attributes (see below), press **Check Attributes**,
  then **Export IFC**.

### Attributes understood by the exporter

| Attribute | Meaning |
|---|---|
| `s@path` | Hierarchy `/System/Group/Element`. **One path = one physical element.** Intermediate segments become `IfcElementAssembly`. |
| `s@ifc_class`, `s@ifc_predefined` | IFC class and PredefinedType (or use *Class Rules* on the node). |
| `s@ifc_storey` | Building storey. |
| `s@ifc_name`, `s@ifc_tag`, `s@ifc_object_type`, `s@ifc_description` | Name, mark, type, description. |
| `s@ifc_material`, `Cd`, `f@Alpha`, `s@ifc_style` | Material and surface style. |
| `d@ifc_psets` | `{SetName: {Property: value}}`. `Qto_*` sets become quantities. Plain numbers are written in project units (mm by default). |
| `d@ifc_measures` | `{SetName: {Property: "LENGTH"/"AREA"/"VOLUME"}}`: these values are in SI and are converted to the file units. Filled by the importer. |
| `s[]@ifc_materials` | Several materials -> `IfcMaterialConstituentSet`. |
| `s@ifc_guid` | Optional fixed GlobalId. If missing, a stable one is derived from path + storey. |

For the full guide, open the node help (F1). For a ready-made template, use **HIFC › Create Attribute Template**.

## Repository layout

```
HIFC.json               Houdini package file (template)
MainMenuCommon.xml      "HIFC" main menu
toolbar/hifc.shelf      HIFC shelf
otls/                   hifc::ifc_import / hifc::ifc_export digital assets (thin wrappers)
python3.13libs/hifc/    all logic: ifc_read / ifc_write (pure IfcOpenShell), sop_import / sop_export (Houdini layer)
vendor/                 IfcOpenShell per platform (not in git)
tests/                  dataset download + round-trip test
```

## Testing

Test data comes from the official buildingSMART
[Certification datasets](https://github.com/buildingSMART/Certification-datasets) (CC BY 4.0):

```bash
python tests/fetch_datasets.py
python tests/test_core.py
python tests/roundtrip.py
```

See [tests/README.md](tests/README.md) for the reference results.

## Performance tips

* Keep **Disk Cache** on: re-opening an unchanged IFC takes about a second.
* Read only the property sets you need (**Property Sets**, e.g. `Pset_* Qto_*`): properties are the slowest part of import.
* Use **Packed** output for large models; switch to Polygons only when you need to edit faces.
* On export, drop vendor property sets you do not need (**Property Sets to Export**, e.g. `* ^ArchiCADProperties`).
* Measure your own files: `hython tests/perf_bench.py model.ifc report.json`.

## Limitations (0.3)

* Geometry is exported as meshes (`IfcPolygonalFaceSet`). There are no parametric extrusions or profiles yet.
* Type objects (`IfcTypeProduct`), openings and host/opening relations are not written;
  `IfcSurfaceFeature` is exported as a proxy.
* Every spatial container (site, facility part, road part...) is exported as `IfcBuildingStorey`.
* Material layers/profiles are flattened to a constituent set (names only, no thicknesses).
* Georeferenced models with very large coordinates are not tested yet (Houdini stores positions in float32).

## License

Copyright 2026 EOK. HIFC is licensed under the [Apache License 2.0](LICENSE). See [NOTICE](NOTICE) and
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for third-party software (IfcOpenShell is LGPL-3.0-or-later
and is installed separately).

HIFC is an independent project and is not affiliated with SideFX, buildingSMART International,
IfcOpenShell or Bonsai. Houdini is a trademark of Side Effects Software Inc.; IFC and buildingSMART
are trademarks of buildingSMART International Ltd.
