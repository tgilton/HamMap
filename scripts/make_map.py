#!/usr/bin/env python3
"""Render interactive US amateur-license density map (pure MapLibre GL, H3 hex GeoJSON).

Reads data/hex/hex_5|6|7.csv -> out/ham_density.html
Color: log-scaled inferno ramp via MapLibre interpolate expression.
Toggles: class (All / General+ / Adv-Extra) and mode (Per area / Per capita).
Zoom-switched hex resolution: r5 <4, r6 4-6.5, r7 6.5+.
"""
import json
from pathlib import Path

import pandas as pd
import numpy as np
import h3

ROOT = Path(__file__).resolve().parent.parent
HEX = ROOT / "data" / "hex"
OUT = ROOT / "out"
OUT.mkdir(exist_ok=True)


def load_pop():
    pop = pd.read_csv(ROOT / "data" / "co-est2024-alldata.csv",
                      usecols=["SUMLEV", "STATE", "COUNTY", "POPESTIMATE2024"],
                      dtype={"STATE": str, "COUNTY": str, "SUMLEV": str},
                      encoding="latin-1", low_memory=False)
    pop = pop[pop.SUMLEV == "050"].copy()
    pop["county_fips"] = pop.STATE.str.zfill(2) + pop.COUNTY.str.zfill(3)
    return pop.set_index("county_fips").POPESTIMATE2024


def hex_rows(res):
    df = pd.read_csv(HEX / f"hex_{res}.csv", dtype={"h3": str, "county_fips": str})
    if "county_fips" in df.columns and "county_area_km2" in df.columns:
        pop = load_pop()
        dens = df.county_fips.map(pop) / df.county_area_km2
        df["pop"] = (dens.fillna(0) * df.hex_area_km2).round(0).astype(int)
    else:
        df["pop"] = 0
    return [{"h": h, "c": int(c), "gp": int(g), "ex": int(x), "p": int(p)}
            for h, c, g, x, p in zip(df["h3"], df["count"], df["n_priv"], df["n_extra"], df["pop"])]


data = {str(r): hex_rows(r) for r in (5, 6, 7)}
maxn = max(max(r["c"] for r in data[str(res)]) for res in (5, 6, 7))

# density ramp: visible even at the low end over the dark basemap
INFERNO = ["#10305f", "#2563eb", "#22d3ee", "#34d399", "#fde047", "#fb923c", "#ef4444", "#fff7d6"]

html = open(Path(__file__).with_name("map_template.html")).read()
V = Path(__file__).with_name("vendor")
html = html.replace("__MAPLIBRE_CSS__", (V / "maplibre-gl.css").read_text())
html = html.replace("__MAPLIBRE_JS__", (V / "maplibre-gl.js").read_text())
html = html.replace("__H3_JS__", (V / "h3-js.js").read_text())
html = html.replace("__STATES__", (ROOT / "out" / "states.json").read_text())
html = html.replace("__DATA_R5__", json.dumps(data["5"], separators=(",", ":")))
html = html.replace("__DATA_R6__", json.dumps(data["6"], separators=(",", ":")))
html = html.replace("__DATA_R7__", json.dumps(data["7"], separators=(",", ":")))
html = html.replace("__MAXN__", str(int(maxn)))
html = html.replace("__RAMP__", json.dumps(INFERNO))
(OUT / "ham_density.html").write_text(html)
mb = (OUT / "ham_density.html").stat().st_size / 1e6
print(f"wrote {OUT/'ham_density.html'} ({mb:.1f} MB, max hex count {maxn})")
