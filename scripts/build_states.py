import geopandas as gpd, json

g = gpd.read_file('data/cb_2024_us_state_500k.shp', columns=['STUSPS', 'NAME'])
g = g[g.STUSPS.notna() & g.STUSPS.str.strip().ne('')].to_crs(4326)
g['geometry'] = g.simplify(0.02, preserve_topology=True)

def polys(geom):
    # correct MultiPolygon nesting: coordinates = [poly = [ring = [pt = [x,y]]]]
    if geom is None or geom.is_empty:
        return []
    geoms = [geom] if geom.geom_type == 'Polygon' else \
            list(geom.geoms) if geom.geom_type == 'MultiPolygon' else []
    out = []
    for p in geoms:
        rings = [p.exterior] + list(p.interiors)
        out.append([[[round(x, 3), round(y, 3)] for x, y in r.coords] for r in rings])
    return out

feats = []
for _, row in g.iterrows():
    coords = polys(row.geometry)
    if not coords:
        continue
    feats.append({"type": "Feature", "properties": {"n": row.STUSPS.strip()},
                  "geometry": {"type": "MultiPolygon", "coordinates": coords}})

out = {"type": "FeatureCollection", "features": feats}
s = json.dumps(out, separators=(',', ':'))
open('out/states.json', 'w').write(s)
print("states:", len(feats), "size:", len(s) // 1024, "KB")
