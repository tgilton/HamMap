#!/usr/bin/env python3
"""Parse FCC ULS amateur license public-access files into a tidy parquet.

Verified field layouts (pipe-delimited, public-access format, 0-indexed):
  HD| sys_id | uls_fileno | ? | callsign | license_status | service | grant |
      expire | effective | cancel | ...           (status: A/C/E/T observed)
  EN| sys_id | ? | ? | callsign | entity_type(L=licensee) | license_id |
      name | first | mi | last | suffix | ? ? ? | street | city | state |
      zip(+4, no dash) | po_box | ? | c_block | frn | type_code | district
  AM| sys_id | ? ? | callsign | op_class | group | region | trustee_call ...

Filter: license_status == 'A' AND (expire empty OR expire >= today).
"""
import pandas as pd
import sys
from pathlib import Path

SRC = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/tmp/amat")
OUT = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(__file__).resolve().parent.parent / "data"
TODAY = "2026-10-28"

def read_pipe(path, cols):
    df = pd.read_csv(path, sep="|", header=None, dtype=str,
                     usecols=sorted(cols), encoding="latin-1",
                     on_bad_lines="skip", low_memory=False)
    df.columns = [cols[c] for c in sorted(cols)]
    return df

def main():
    hd = read_pipe(SRC / "HD.dat", {1: "sys_id", 4: "callsign", 5: "status",
                                    6: "service", 7: "grant_date", 8: "expire_date"})
    en = read_pipe(SRC / "EN.dat", {1: "sys_id", 5: "entity_type", 15: "street",
                                    16: "city", 17: "state", 18: "zip", 19: "po_box", 22: "frn"})
    am = read_pipe(SRC / "AM.dat", {1: "sys_id", 5: "op_class", 7: "region"})

    print(f"HD {len(hd)} | EN {len(en)} | AM {len(am)}")
    act = hd[hd.status == "A"].copy()
    exp = pd.to_datetime(act.expire_date, format="%m/%d/%Y", errors="coerce")
    act = act[exp.isna() | (exp >= pd.Timestamp(TODAY))]
    print(f"status A: {(hd.status == 'A').sum()} -> not expired: {len(act)}")

    en_l = en[en.entity_type == "L"].drop_duplicates("sys_id")
    df = (act.merge(en_l.drop(columns="entity_type"), on="sys_id", how="left")
             .merge(am.drop_duplicates("sys_id"), on="sys_id", how="left"))

    df["state"] = df["state"].str.strip().str.upper()
    n0 = len(df)
    df = df[~df.state.isin({"AA", "AE", "AP"}) & df.state.notna()]
    print(f"dropped military APO/FPO: {n0 - len(df)}")

    df["zip5"] = df["zip"].str.extract(r"^(\d{5})")[0]
    s = df.street.str.strip().str.upper()
    df["street_clean"] = s
    df["has_street"] = (s.str.len() > 3) & ~s.fillna("").str.contains(r"P\.?\s?O\.?\s?BOX|^BOX\b", regex=True)

    keep = ["sys_id", "callsign", "service", "grant_date", "expire_date",
            "op_class", "region", "frn", "street_clean", "city", "state",
            "zip5", "po_box", "has_street"]
    out = df[keep]
    out.to_parquet(OUT / "licenses_active.parquet", index=False)
    print(f"wrote {len(out)} rows -> {OUT/'licenses_active.parquet'}")
    print("op_class:", out.op_class.value_counts(dropna=False).to_dict())
    print(f"no street: {(~out.has_street).sum()} | no zip5: {out.zip5.isna().sum()} | no state: {out.state.isna().sum()}")
    print("top states:", out.state.value_counts().head(8).to_dict())

if __name__ == "__main__":
    main()
