#!/usr/bin/env python3
"""Build zip5 reference table: centroid, land area, county FIPS, county pop 2024."""
from pathlib import Path
import pandas as pd
import geopandas as gpd

DATA = Path(__file__).resolve().parent.parent / "data"

zcta = gpd.read_file(DATA / "cb_2020_us_zcta520_500k.shp",
                     columns=["ZCTA5CE20", "ALAND20"])
zcta = zcta.to_crs(4326)
zcta["zip5"] = zcta["ZCTA5CE20"].astype(str).str.zfill(5)
# centroid of valid geometry (use representative_point for robustness)
zcta["pt"] = zcta.geometry.representative_point()
zcta["zip_lat"] = zcta.pt.y
zcta["zip_lon"] = zcta.pt.x

county = gpd.read_file(DATA / "cb_2024_us_county_500k.shp",
                       columns=["GEOID", "NAME"]).to_crs(4326)
county = county[county.GEOID.str[:2].astype(int) <= 72]  # states+DC+PR, skip islands

# point-in-polygon: zip centroid -> county
sjoin = gpd.sjoin(zcta.set_geometry("pt")[["zip5", "zip_lat", "zip_lon", "ALAND20", "pt"]],
                  county[["GEOID", "geometry"]], how="left", predicate="within")
# some centroids fall in gaps (island ZCTAs): nearest county fallback
miss = sjoin.GEOID.isna()
if miss.any():
    near = gpd.sjoin_nearest(sjoin.loc[miss, ["zip5", "pt"]],
                             county[["GEOID", "geometry"]], how="left",
                             distance_col="d")
    near = near.sort_values("d").drop_duplicates("zip5")
    sjoin.loc[miss, "GEOID"] = near.set_index("zip5").reindex(sjoin.index[miss]).GEOID.values

sjoin["county_fips"] = sjoin["GEOID"]

# county population 2024
pop = pd.read_csv(DATA / "co-est2024-alldata.csv",                  dtype={"STATE": str, "COUNTY": str, "SUMLEV": str},
                  usecols=["SUMLEV", "STATE", "COUNTY", "CTYNAME", "POPESTIMATE2024"],
                  encoding="latin-1", low_memory=False)
pop = pop[pop.SUMLEV == "050"].copy()
pop["county_fips"] = pop.STATE.str.zfill(2) + pop.COUNTY.str.zfill(3)
pop["county_pop_2024"] = pop.POPESTIMATE2024

ref = sjoin.merge(pop[["county_fips", "county_pop_2024"]], on="county_fips", how="left")
ref = ref[["zip5", "zip_lat", "zip_lon", "ALAND20", "county_fips", "county_pop_2024"]]
ref = ref.rename(columns={"ALAND20": "zip_land_m2"})
ref.to_parquet(DATA / "zip_ref.parquet", index=False)
print(f"zip ref rows: {len(ref)}; missing centroid: {ref.zip_lat.isna().sum()}; "
      f"missing county: {ref.county_fips.isna().sum()}; missing pop: {ref.county_pop_2024.isna().sum()}")
print(ref.head(3).to_string())
