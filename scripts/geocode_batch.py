#!/usr/bin/env python3
"""Batch-geocode unique license addresses via US Census Batch Geocoder.

Resumable: results are appended per-batch to outdir/matches.csv; batches whose
keys are fully present are skipped. Run repeatedly until exit 0 with all done.
CSV out columns: key,lat,lon,quality,matched
key = upper(street)|city|state|zip5   (the address join key)
"""
import io, sys, time, csv, random
from pathlib import Path
import pandas as pd
import requests

DATA = Path(__file__).resolve().parent.parent / "data"
GEO = DATA / "geocode"
GEO.mkdir(exist_ok=True)
_w = __import__("os").environ.get("GEO_WORKER", "0")
MATCHES = GEO / f"matches_w{_w}.csv"
URL = "https://geocoding.geo.census.gov/geocoder/locations/addressbatch"
BATCH = 9_000
HEADERS = {"User-Agent": "ham-density-map research (contact: tgilton@users.noreply.github.com)"}

def load_done():
    done = set()
    for mf in sorted(GEO.glob("matches_w*.csv")) + ([GEO / "matches.csv"] if (GEO / "matches.csv").exists() else []):
        with open(mf) as f:
            r = csv.reader(f)
            next(r, None)
            for row in r:
                if row:
                    done.add(row[0])
    return done

def geocode_batch(df_batch):
    """df_batch: columns id,street,city,state,zip -> dict id -> (lat,lon,quality,matched)"""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["id", "street", "city", "state", "zip"])
    for r in df_batch.itertuples():
        street = " ".join(str(r.street).replace('"', " ").split())
        city = " ".join(str(r.city).replace('"', " ").split())
        w.writerow([r.id, street, city, r.state, r.zip5])
    for attempt in range(6):
        try:
            resp = requests.post(URL,
                                 files={"addressFile": ("b.csv", buf.getvalue().encode(), "text/csv")},
                                 data={"benchmark": "4", "vintage": "4", "format": "csv"},
                                 headers=HEADERS, timeout=300)
            if resp.status_code != 200:
                raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:200]}")
            out = {}
            rows = list(csv.reader(io.StringIO(resp.text)))
            for row in rows:
                if len(row) >= 7 and row[0] != "id":
                    _id, _in, match, qual, matched, coord, _rest = row[:7]
                    if match == "Match" and coord and "," in coord:
                        lon, lat = coord.split(",")
                        out[_id] = (lat, lon, qual, matched)
                    else:
                        out[_id] = None
                elif len(row) == 3 and row[0] != "id" and row[2] == "No_Match":
                    out[row[0]] = None
            return out
        except Exception as e:
            wait = 15 * (attempt + 1) + random.uniform(0, 10)
            print(f"  retry {attempt+1} after {e} (sleep {wait:.0f}s)", flush=True)
            time.sleep(wait)
    raise RuntimeError("batch permanently failed")

def main():
    import os
    worker = int(os.environ.get("GEO_WORKER", "0"))
    nnodes = int(os.environ.get("GEO_NNODES", "1"))
    lic = pd.read_parquet(DATA / "licenses_active.parquet")
    st = lic[lic.has_street].copy()
    st["city"] = st["city"].str.strip().str.upper().str.replace(r"[^A-Z ]", "", regex=True)
    st["key"] = st.street_clean.fillna("") + "|" + st.city + "|" + st.state + "|" + st.zip5
    uniq = (st[["key", "street_clean", "city", "state", "zip5"]]
            .drop_duplicates("key").reset_index(drop=True))
    uniq = uniq.rename(columns={"street_clean": "street"})
    print(f"unique street addresses to geocode: {len(uniq)}", flush=True)

    done = load_done()
    todo = uniq[~uniq.key.isin(done)].reset_index(drop=True)
    if nnodes > 1:
        todo = todo.iloc[worker::nnodes].reset_index(drop=True)
    print(f"worker {worker}/{nnodes} already done: {len(uniq) - len(todo) - len(uniq) % 1 if nnodes == 1 else 'see log'}; remaining: {len(todo)}", flush=True)

    new_file = not MATCHES.exists() or MATCHES.stat().st_size == 0
    fh = open(MATCHES, "a", newline="")
    w = csv.writer(fh)
    if new_file:
        w.writerow(["key", "lat", "lon", "quality", "matched"])
        fh.flush()

    keymap = todo.set_index(todo.index.to_series().apply(lambda i: todo.at[i, "key"]))
    n_batches = (len(todo) + BATCH - 1) // BATCH
    for b in range(n_batches):
        chunk = todo.iloc[b * BATCH:(b + 1) * BATCH].copy()
        chunk["id"] = chunk.index.astype(str)
        key_by_id = dict(zip(chunk.id, chunk.key))
        res = geocode_batch(chunk)
        n_m = 0
        for _id, val in res.items():
            if val is not None:
                w.writerow([key_by_id[_id], *val])
                n_m += 1
            else:
                w.writerow([key_by_id[_id], "", "", "No_Match", ""])
        fh.flush()
        print(f"batch {b+1}/{n_batches}: {len(res)} rows, {n_m} matched ({sum(1 for v in res.values() if v)})", flush=True)
        time.sleep(1.5)
    fh.close()
    print("ALL BATCHES DONE", flush=True)

if __name__ == "__main__":
    main()
