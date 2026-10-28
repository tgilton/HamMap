#!/usr/bin/env python3
"""Static publication-quality density map (matplotlib, log color, USA)."""
import sys
from pathlib import Path
import numpy as np
import pandas as pd
import h3
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import cm, colors, colors as mcolors
from matplotlib.collections import PolyCollection

ROOT = Path(__file__).resolve().parent.parent
HEX = ROOT / "data" / "hex"
OUT = ROOT / "out"

def build(res=6, col="count", projection="albers"):
    df = pd.read_csv(HEX / f"hex_{res}.csv", dtype={"h3": str})
    df = df[df[col] > 0]
    # simple conic-albers-ish: scale x by cos(38deg) — good enough for lower-48 square
    xs = 0.78
    polys, vals = [], []
    for cell, v in zip(df.h3, df[col]):
        if not (-180 < h3.cell_to_latlng(cell)[1] < -60):
            continue
        b = np.array(h3.cell_to_boundary(cell))
        pts = np.column_stack([b[:, 1] * xs, b[:, 0]])
        polys.append(pts)
        vals.append(v)
    return polys, np.array(vals)

def main(col="count", res=6, fname="ham_density.png"):
    polys, vals = build(res, col)
    vmax = vals.max()
    norm = colors.LogNorm(vmin=1, vmax=vmax)
    cmap = plt.colormaps["inferno"](norm(np.maximum(vals, 1)))
    cmap[:, 3] = 200 / 255
    cmap[vals < 1, 3] = 0

    fig, ax = plt.subplots(figsize=(20, 12.5), dpi=200)
    fig.patch.set_facecolor("#0b0b0f"); ax.set_facecolor("#0b0b0f")
    # rough US outline via county bounds: skip, hexes speak for themselves
    pc = PolyCollection(polys, facecolors=cmap, edgecolors="none")
    ax.add_collection(pc)
    ax.set_xlim(-127 * 0.78, -66 * 0.78); ax.set_ylim(23.5, 50.5)
    ax.set_axis_off()
    label = {"count": "active amateur licensees",
             "n_priv": "General-class and above",
             "n_extra": "Advanced/Extra-class"}[col]
    ax.set_title(f"Amateur Radio License Density — USA ({label}, H3 res {res})",
                 color="#ddd", fontsize=18, pad=14, loc="left")
    sm = plt.cm.ScalarMappable(cmap=plt.colormaps["inferno"], norm=norm)
    cbar = fig.colorbar(sm, ax=ax, fraction=0.025, pad=0.02)
    cbar.set_label("licenses per hex (log)", color="#bbb")
    cbar.ax.yaxis.set_tick_params(color="#888", labelcolor="#bbb")
    fig.text(0.01, 0.02, "FCC ULS active licenses · street-geocoded (Census) · hexes do not imply propagation paths",
             color="#777", fontsize=9)
    fig.savefig(OUT / fname, bbox_inches="tight", facecolor=fig.get_facecolor())
    print("wrote", OUT / fname)

if __name__ == "__main__":
    col = sys.argv[1] if len(sys.argv) > 1 else "count"
    fname = sys.argv[2] if len(sys.argv) > 2 else f"ham_density_{col}.png"
    main(col, 6, fname)
