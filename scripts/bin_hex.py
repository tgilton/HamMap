#!/usr/bin/env python3
"""Bin geocoded hams into H3 hexagons at res 5/6/7.

Output per res: hex/hex_{res}.csv with columns
  h3 (str), count, n_priv (General+), n_extra (Extra/Advanced)
"""
from pathlib import Path
import numpy as np
import pandas as pd
import h3

DATA = Path(__file__).resolve().parent.parent / "data"
OUT = DATA / "hex"
OUT.mkdir(exist_ok=True)

RESOLUTIONS = [5, 6, 7]

pts = pd.read_parquet(DATA / "ham_points.parquet")
lat = pts.lat.to_numpy(np.float64)
lon = pts.lon.to_numpy(np.float64)
class_rank = {"E": 2, "A": 2, "G": 1, "T": 0, "N": 0}
priv = pts.op_class.map(class_rank).fillna(0).to_numpy()
f = np.vectorize(h3.latlng_to_cell, otypes=[object])

for res in RESOLUTIONS:
    cells = f(lat, lon, res)
    tmp = pd.DataFrame({"h3": cells, "priv": priv})
    g = tmp.groupby("h3").agg(
        count=("priv", "size"),
        n_priv=("priv", lambda x: int((x >= 1).sum())),
        n_extra=("priv", lambda x: int((x == 2).sum())),
    ).reset_index()
    g["hex_area_km2"] = h3.average_hexagon_area(res, unit="km^2")

    # county attribution for per-capita mode: hex centroid -> county polygon
    import geopandas as gpd
    ctr = np.array([h3.cell_to_latlng(c) for c in g.h3])
    hs = gpd.GeoDataFrame(g, geometry=gpd.points_from_xy(ctr[:, 1], ctr[:, 0]), crs=4326)
    counties = gpd.read_file(DATA.parent / "cb_2024_us_county_500k.zip"
                             if (DATA.parent / "cb_2024_us_county_500k.zip").exists()
                             else DATA / "cb_2024_us_county_500k.shp",
                             columns=["GEOID"]).to_crs(4326)
    counties["county_area_km2"] = counties.to_crs(5070).area / 1e6
    joined = gpd.sjoin(hs, counties[["GEOID", "county_area_km2", "geometry"]],
                       how="left", predicate="within").drop_duplicates("h3")
    g = pd.DataFrame(joined.drop(columns="geometry")).rename(columns={"GEOID": "county_fips"})

    g.to_csv(OUT / f"hex_{res}.csv", index=False)
    top = g.nlargest(5, "count")
    print(f"res {res}: {len(g)} hexes | max {int(g['count'].max())} | "
          f"top5 hexes: {top['count'].tolist()}")
