#!/usr/bin/env python3
"""Assemble final geocoded point list: street geocode, ZIP-centroid fallback."""
from pathlib import Path
import pandas as pd

DATA = Path(__file__).resolve().parent.parent / "data"

lic = pd.read_parquet(DATA / "licenses_active.parquet")
lic["city"] = lic.city.str.strip().str.upper().str.replace(r"[^A-Z ]", "", regex=True)
lic["key"] = lic.street_clean.fillna("") + "|" + lic.city + "|" + lic.state + "|" + lic.zip5

geo = pd.concat([pd.read_csv(f) for f in sorted((DATA / "geocode").glob("matches_w*.csv"))], ignore_index=True)
geo = geo.drop_duplicates("key")
geo_ok = geo[geo.lat.notna()].drop_duplicates("key")
geo_no = set(geo[geo.lat.isna()].key)

df = lic.merge(geo_ok[["key", "lat", "lon", "quality"]], on="key", how="left")
df["source"] = "street"
df.loc[df.lat.isna(), "source"] = "zip_centroid"

zref = pd.read_parquet(DATA / "zip_ref.parquet")
zref = zref.set_index("zip5")[["zip_lat", "zip_lon"]]
need = df.lat.isna()
df.loc[need, "lat"] = df.loc[need, "zip5"].map(zref.zip_lat)
df.loc[need, "lon"] = df.loc[need, "zip5"].map(zref.zip_lon)
df = df.rename(columns={"zip_lat": "lat", "zip_lon": "lon"})

still = df.lat.isna()
print(f"total {len(df)} | street {int((df.source=='street').sum())} | "
      f"zip-fallback {int(((df.source=='zip_centroid') & ~still).sum())} | "
      f"unplaced {int(still.sum())}")
print(df.loc[df.source == 'street', 'quality'].value_counts())

out = df[~still][["callsign", "op_class", "region", "state", "zip5",
                  "county_fips" if "county_fips" in df else "zip5",
                  "lat", "lon", "source"]]
out = df[~still].copy()
z = zref.reset_index()
# attach county info via zip
try:
    zc = pd.read_parquet(DATA / "zip_ref.parquet")[["zip5", "county_fips", "county_pop_2024"]]
    out = out.merge(zc, on="zip5", how="left")
except Exception as e:
    print("county join skipped:", e)
out.to_parquet(DATA / "ham_points.parquet", index=False)
print("wrote", DATA / "ham_points.parquet", len(out), "points")
# sanity: known dense/sparse places
for z5 in ("10001", "85001", "83706", "99701"):
    n = (out.zip5 == z5).sum()
    print(f"  zip {z5}: {n} hams")
