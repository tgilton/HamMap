"""hamdensity — query amateur-radio license density by location.

Data source: FCC ULS amateur license public-access files (weekly),
geocoded via US Census batch geocoder. License classes:
  Tech/Novice  -> "t"   (no HF above Novice privileges)
  General      -> "g"
  Adv/Extra    -> "e"

Two query backends:
  HexDensity  — O(1) lookup of precomputed H3 hex counts (res 5/6/7).
  PointQuery  — exact per-license spherical queries (radius, bearing sector,
                azimuthal profile) over the raw geocoded point list.

Typical use (antenna pattern deconvolution):
    from hamdensity import load
    hd = load()                         # ~740k points, builds KD-tree once
    hd.density_at(43.6, -116.2)         # hams / 100 km^2 around point
    hd.density_at(43.6, -116.2, cls="e")            # Extra/Advanced only
    hd.sector(43.6, -116.2, bearing=45, half_width_deg=10, max_km=500)
    profile = hd.azimuthal_profile(43.6, -116.2, n_sectors=36, max_km=1000,
                                   bin_km=100)      # 3D array [sector, range]
"""
from __future__ import annotations
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

PKG_DIR = Path(__file__).resolve().parent
DEFAULT_POINTS = next((p for p in (PKG_DIR.parent / "data" / "ham_points.parquet",
                                   PKG_DIR.parent / "data" / "ham_points_slim.parquet")
                       if p.exists()), PKG_DIR.parent / "data" / "ham_points.parquet")
DEFAULT_HEX = PKG_DIR.parent / "data" / "hex"

CLASS_GROUPS = {
    "all": {"T", "N", "G", "A", "E"},
    "tech": {"T", "N"},
    "general": {"G"},
    "extra": {"A", "E"},
    "general_plus": {"G", "A", "E"},
}

EARTH_R = 6371.0088  # km


def _ecef(lat, lon, r=EARTH_R):
    la, lo = np.radians(lat), np.radians(lon)
    return np.stack([r * np.cos(la) * np.cos(lo),
                     r * np.cos(la) * np.sin(lo),
                     r * np.sin(la)], axis=-1)


def _gc(lat1, lon1, lat2, lon2):
    """great-circle distance km (vectorized, haversine)"""
    la1, lo1, la2, lo2 = map(np.radians, (lat1, lon1, lat2, lon2))
    hav = (np.sin((la2 - la1) / 2) ** 2
           + np.cos(la1) * np.cos(la2) * np.sin((lo2 - lo1) / 2) ** 2)
    return 2 * EARTH_R * np.arcsin(np.sqrt(hav))


def _bearing(lat1, lon1, lat2, lon2):
    la1, lo1, la2, lo2 = map(np.radians, (lat1, lon1, lat2, lon2))
    dlo = lo2 - lo1
    y = np.sin(dlo) * np.cos(la2)
    x = np.cos(la1) * np.sin(la2) - np.sin(la1) * np.cos(la2) * np.cos(dlo)
    return np.degrees(np.arctan2(y, x)) % 360


class PointQuery:
    """Exact queries over the geocoded point list."""

    def __init__(self, points: pd.DataFrame, max_neighbors: int = 200_000):
        import scipy.spatial
        self.df = points
        self.lat = points.lat.to_numpy(np.float64)
        self.lon = points.lon.to_numpy(np.float64)
        self.cls = points.op_class.astype(str).to_numpy()
        self._mask_cache = {}
        for name, allowed in CLASS_GROUPS.items():
            self._mask_cache[name] = np.isin(self.cls, sorted(allowed))
        xyz = _ecef(self.lat, self.lon)
        self._tree = scipy.spatial.cKDTree(xyz)
        self.max_neighbors = max_neighbors

    def _nearby(self, lat, lon, radius_km):
        # chord length on the sphere for a gc radius
        chord = 2 * EARTH_R * np.sin(min(radius_km, EARTH_R * np.pi) / (2 * EARTH_R))
        idx = self._tree.query_ball_point(
            _ecef(np.float64(lat), np.float64(lon)), chord)
        return np.asarray(idx, dtype=int)

    def density_at(self, lat, lon, radius_km=25.0, cls="all"):
        """hams per 100 km^2 within radius_km of point (default 25 km)."""
        idx = self._nearby(lat, lon, radius_km)
        if idx.size == 0:
            return 0.0
        d = _gc(lat, lon, self.lat[idx], self.lon[idx])
        keep = d <= radius_km
        n = int((keep & self._mask_cache[cls][idx]).sum())
        area = np.pi * radius_km ** 2
        return 100.0 * n / area if area else 0.0

    def count_within(self, lat, lon, radius_km, cls="all"):
        idx = self._nearby(lat, lon, radius_km)
        if idx.size == 0:
            return 0
        d = _gc(lat, lon, self.lat[idx], self.lon[idx])
        return int(((d <= radius_km) & self._mask_cache[cls][idx]).sum())

    def sector(self, lat, lon, bearing, half_width_deg=15.0,
               max_km=1000.0, min_km=0.0, cls="all"):
        """count + mean distance of hams in a bearing sector."""
        idx = self._nearby(lat, lon, max_km)
        if idx.size == 0:
            return {"count": 0, "mean_km": None}
        d = _gc(lat, lon, self.lat[idx], self.lon[idx])
        b = _bearing(lat, lon, self.lat[idx], self.lon[idx])
        db = np.abs((b - bearing + 180) % 360 - 180)
        keep = ((d <= max_km) & (d >= min_km)
                & (db <= half_width_deg) & self._mask_cache[cls][idx])
        n = int(keep.sum())
        return {"count": n, "mean_km": float(d[keep].mean()) if n else None}

    def azimuthal_profile(self, lat, lon, n_sectors=36, max_km=1000.0,
                          bin_km=100.0, cls="all"):
        """2D array [n_sectors, n_bins] of counts: hams per (bearing, range) cell.

        This is the likelihood-of-contact surface for pattern deconvolution:
        weight a received/transmitted azimuth pattern by profile × path
        propagation probability.
        """
        nb = int(max_km / bin_km)
        out = np.zeros((n_sectors, nb), int)
        idx = self._nearby(lat, lon, max_km)
        if idx.size == 0:
            return out
        d = _gc(lat, lon, self.lat[idx], self.lon[idx])
        b = _bearing(lat, lon, self.lat[idx], self.lon[idx])
        m = self._mask_cache[cls][idx]
        ok = (d <= max_km) & m
        d, b = d[ok], b[ok]
        sec = (b / (360.0 / n_sectors)).astype(int) % n_sectors
        rng = np.clip((d / bin_km).astype(int), 0, nb - 1)
        np.add.at(out, (sec, rng), 1)
        return out

    def top_callsigns(self, lat, lon, radius_km=50.0, cls="all", limit=20):
        idx = self._nearby(lat, lon, radius_km)
        if idx.size == 0:
            return pd.DataFrame()
        d = _gc(lat, lon, self.lat[idx], self.lon[idx])
        keep = np.where((d <= radius_km) & self._mask_cache[cls][idx])[0]
        sub = self.df.iloc[idx[keep]].assign(dist_km=d[keep])
        return sub.nsmallest(limit, "dist_km")[["callsign", "op_class", "dist_km"]]


@lru_cache(maxsize=2)
def load(points_path: str | None = None):
    """PointQuery over all geocoded active licenses (~1s import)."""
    import scipy.spatial  # noqa: F401
    path = Path(points_path) if points_path else DEFAULT_POINTS
    pts = pd.read_parquet(path)
    return PointQuery(pts)


@lru_cache(maxsize=8)
def _hex_frame(res: int):
    f = pd.read_csv(DEFAULT_HEX / f"hex_{res}.csv", dtype={"h3": str})
    return f.set_index("h3", drop=False)


def hex_density(lat, lon, res=6, col="count"):
    """Precomputed license count in the H3 hex containing (lat, lon).

    col: 'count' | 'n_priv' (General+) | 'n_extra' (Adv/Extra)
    Density = value / hex_area_km2 (also returned in the row).
    Returns the row (Series) or None if no hex data (water/outside US).
    """
    import h3
    cell = h3.latlng_to_cell(lat, lon, res)
    f = _hex_frame(res)
    row = f.loc[cell] if cell in f.index else None
    if row is None or col not in row:
        return None
    return {
        "h3": cell, "res": res, col: int(row[col]),
        "count": int(row["count"]),
        "n_priv": int(row["n_priv"]), "n_extra": int(row["n_extra"]),
        "area_km2": float(row["hex_area_km2"]),
        "per_100km2": 100.0 * float(row[col]) / float(row["hex_area_km2"]),
    }
