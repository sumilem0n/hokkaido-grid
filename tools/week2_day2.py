#!/usr/bin/env python3
"""Week 2 Day 2 — Python fundamentals drill.
Read a messy CSV, clean it, write a filtered result.
Rehearses the HEPCO capstone: read the data before coding.
"""

INPUT = "plants.csv"
OUTPUT = "plants_over_500.csv"

def load_rows(path):
    with open(path) as f:               # (a) `with`
        lines = f.read().splitlines()   # splitlines() strips the trailing newline per line
    return lines[1:]                    # (b) slice off the header (index 0)

def parse(line):
    name, type_, cap_str = line.split(",")   # (c) unpack — raises ValueError if not 3 fields
    return name, type_, int(cap_str)         # int() raises ValueError on non-numeric

def main():
    rows = load_rows(INPUT)
    plants = []
    for line in rows:
        try:                                 # (d) exceptions: EAFP
            name, type_, cap = parse(line)
        except ValueError as e:
            print(f"skipping bad row: {line!r} ({e})")
            continue
        plants.append((name, type_, cap))

    big = [p for p in plants if p[2] > 500]   # (e) comprehension: filter > 500 MW

    totals = {}                               # (f) dict accumulate
    for name, type_, cap in plants:
        totals[type_] = totals.get(type_, 0) + cap

    with open(OUTPUT, "w") as f:              # `with` again, write mode
        for name, type_, cap in big:
            f.write(f"{name},{type_},{cap}\n")

    print(f"{len(plants)} valid rows, {len(big)} over 500 MW")
    for type_, total in totals.items():
        print(f"{type_}: {total} MW")

if __name__ == "__main__":                    # (g) run-vs-import guard
    main()
