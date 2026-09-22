# SPDX-FileCopyrightText: 2026 EOK
# SPDX-License-Identifier: Apache-2.0
"""Синтетические IFC с геопривязкой для тестов верхних уровней (IFC4 и IFC2X3).

IFC4:   IfcMapConversion (Eastings/Northings/высота, поворот 30°, EPSG:25832), TrueNorth,
        площадка с широтой/долготой и отметкой, здание со сдвигом и ElevationOfRefHeight, стена с геометрией.
IFC2X3: те же данные через ePSet_MapConversion / ePSet_ProjectedCRS и широту/долготу площадки.
Проект в миллиметрах — чтобы проверить пересчёт в метры.
"""
import math

import numpy as np

import ifcopenshell
import ifcopenshell.api as api

EXPECT = {
    "crs": "EPSG:25832",
    "map_origin_m": [500000.0, 5700000.0, 45.0],
    "map_rotation_deg": 30.0,
    "site_origin_m": [10.0, 20.0, 0.0],
    "latitude": 51.4575,         # 51°27'27"
    "longitude": 7.0144444444,   # 7°0'52"
    "ref_elevation_m": 45.0,
    "building_origin_m": [13.0, 24.0, 0.5],   # площадка (10, 20, 0) + относительный сдвиг (3, 4, 0.5)
    "elevation_of_ref_height_m": 45.5,
}


def _placement(f, rel_to, xyz_mm):
    pt = f.create_entity("IfcCartesianPoint", Coordinates=[float(c) for c in xyz_mm])
    ax = f.create_entity("IfcAxis2Placement3D", Location=pt)
    return f.create_entity("IfcLocalPlacement", PlacementRelTo=rel_to, RelativePlacement=ax)


def make(path, schema="IFC4", site_origin_m=None):
    """Пишет файл и возвращает путь. В IFC2X3 OwnerHistory обязателен — подставляем пользователя на время записи.

    site_origin_m — своё положение площадки (например, «общие координаты» Revit в сотнях километров).
    """
    import ifcopenshell.api.owner.settings as owner
    f = ifcopenshell.file(schema=schema)
    saved = (owner.get_user, owner.get_application)
    if schema == "IFC2X3":
        org = f.create_entity("IfcOrganization", Name="HIFC tests")
        user = f.create_entity("IfcPersonAndOrganization", ThePerson=f.create_entity("IfcPerson"), TheOrganization=org)
        app = f.create_entity("IfcApplication", ApplicationDeveloper=org, Version="test",
                              ApplicationFullName="HIFC tests", ApplicationIdentifier="HIFC")
        owner.get_user = lambda _f: user
        owner.get_application = lambda _f: app
    try:
        return _make(f, path, schema, site_origin_m or EXPECT["site_origin_m"])
    finally:
        owner.get_user, owner.get_application = saved


def _make(f, path, schema, site_origin_m):
    proj = api.run("root.create_entity", f, ifc_class="IfcProject", name="Georef test")
    api.run("unit.assign_unit", f, length={"is_metric": True, "raw": "MILLIMETERS"})
    model = api.run("context.add_context", f, context_type="Model")
    body = api.run("context.add_context", f, context_type="Model", context_identifier="Body",
                   target_view="MODEL_VIEW", parent=model)
    a = math.radians(EXPECT["map_rotation_deg"])
    if schema != "IFC2X3":
        api.run("georeference.add_georeferencing", f)
        api.run("georeference.edit_georeferencing", f,
                projected_crs={"Name": EXPECT["crs"], "Description": "ETRS89 / UTM zone 32N"},
                coordinate_operation={"Eastings": EXPECT["map_origin_m"][0], "Northings": EXPECT["map_origin_m"][1],
                                      "OrthogonalHeight": EXPECT["map_origin_m"][2],
                                      "XAxisAbscissa": math.cos(a), "XAxisOrdinate": math.sin(a), "Scale": 0.001})
        # MapUnit = метр: Eastings/Northings записаны в метрах
        crs = f.by_type("IfcProjectedCRS")[0]
        crs.MapUnit = f.create_entity("IfcSIUnit", UnitType="LENGTHUNIT", Name="METRE")
        model.TrueNorth = f.create_entity("IfcDirection", DirectionRatios=[-0.5, math.sqrt(3) / 2])
    else:
        ps = api.run("pset.add_pset", f, product=proj, name="ePSet_MapConversion")
        api.run("pset.edit_pset", f, pset=ps, properties={
            "Eastings": EXPECT["map_origin_m"][0], "Northings": EXPECT["map_origin_m"][1],
            "OrthogonalHeight": EXPECT["map_origin_m"][2], "XAxisAbscissa": math.cos(a),
            "XAxisOrdinate": math.sin(a), "Scale": 0.001})
        ps = api.run("pset.add_pset", f, product=proj, name="ePSet_ProjectedCRS")
        api.run("pset.edit_pset", f, pset=ps, properties={"Name": EXPECT["crs"], "MapUnit": "METRE"})

    site = api.run("root.create_entity", f, ifc_class="IfcSite", name="Site A")
    site.RefLatitude = [51, 27, 27, 0]
    site.RefLongitude = [7, 0, 52, 0]
    site.RefElevation = EXPECT["ref_elevation_m"] * 1000.0
    site.LandTitleNumber = "LT-42"
    site.ObjectPlacement = _placement(f, None, [v * 1000.0 for v in site_origin_m])
    api.run("aggregate.assign_object", f, relating_object=proj, products=[site])
    ps = api.run("pset.add_pset", f, product=site, name="Pset_SiteCommon")
    api.run("pset.edit_pset", f, pset=ps, properties={"TotalArea": 1200.0})

    bld = api.run("root.create_entity", f, ifc_class="IfcBuilding", name="Building B")
    bld.ObjectPlacement = _placement(f, site.ObjectPlacement, [3000.0, 4000.0, 500.0])
    bld.ElevationOfRefHeight = EXPECT["elevation_of_ref_height_m"] * 1000.0
    api.run("aggregate.assign_object", f, relating_object=site, products=[bld])
    storey = api.run("root.create_entity", f, ifc_class="IfcBuildingStorey", name="L0")
    storey.ObjectPlacement = _placement(f, bld.ObjectPlacement, [0.0, 0.0, 0.0])
    api.run("aggregate.assign_object", f, relating_object=bld, products=[storey])

    wall = api.run("root.create_entity", f, ifc_class="IfcWall", name="W")
    wall.ObjectPlacement = _placement(f, storey.ObjectPlacement, [0.0, 0.0, 0.0])
    api.run("spatial.assign_container", f, relating_structure=storey, products=[wall])
    v = np.array([[x, y, z] for x in (0, 2000.0) for y in (0, 200.0) for z in (0, 3000.0)])
    faces = [[0, 2, 3, 1], [4, 5, 7, 6], [0, 1, 5, 4], [2, 6, 7, 3], [0, 4, 6, 2], [1, 3, 7, 5]]
    rep = f.create_entity("IfcShapeRepresentation", ContextOfItems=body, RepresentationIdentifier="Body",
                          RepresentationType="Brep", Items=[f.create_entity(
                              "IfcFacetedBrep", Outer=f.create_entity("IfcClosedShell", CfsFaces=[
                                  f.create_entity("IfcFace", Bounds=[f.create_entity(
                                      "IfcFaceOuterBound", Bound=f.create_entity(
                                          "IfcPolyLoop", Polygon=[f.create_entity(
                                              "IfcCartesianPoint", Coordinates=[float(c) for c in v[i]])
                                              for i in fc]), Orientation=True)]) for fc in faces]))])
    wall.Representation = f.create_entity("IfcProductDefinitionShape", Representations=[rep])
    f.write(path)
    return path
