
"""Fingerprint the header of every monthly エリア需給 file, 202404 onward.

Hand-run tool. Answers: does one parser cover the archive, or does the
column layout change inside it? Page docs announce one 様式変更 (2024-04);
202404 has 20 columns and 202604 has 22, so they are incomplete.
"""

from __future__ import annotations

import time

import requests

BASE = (
    "https://www.hepco.co.jp/network/con_service/public_document"
    "/supply_demand_results/csv"
)
TIMEOUT = (5, 10)


def months(start=(2024, 4), end=(2026, 7)):
    y, m = start
    while (y, m) <= end:
        yield f"{y}{m:02d}"
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def header_of(yyyymm: str) -> str:
    url = f"{BASE}/eria_jukyu_{yyyymm}_01.csv"
    r = requests.get(url, timeout=TIMEOUT, headers={"Range": "bytes=0-2047"})
    r.raise_for_status()
    return r.content.decode("cp932", errors="replace").splitlines()[1]


def main() -> int:
    layouts: dict[str, list[str]] = {}
    for ym in months():
        try:
            layouts.setdefault(header_of(ym), []).append(ym)
        except requests.RequestException as exc:
            print(f"{ym}  ERR {type(exc).__name__}: {exc}")
        time.sleep(0.3)

    for i, (header, ms) in enumerate(layouts.items(), 1):
        cols = header.split(",")
        print(f"\nlayout {i}: {len(cols)} columns, {len(ms)} months")
        print(f"  {ms[0]} .. {ms[-1]}")
        print(f"  {header}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
