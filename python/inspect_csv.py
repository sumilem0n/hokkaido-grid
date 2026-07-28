"""
inspect_csv.py — look at a raw CSV before you trust it.

    uv run python python/inspect_csv.py <path>

Prints, in order:
  1. file size + line count
  2. line endings (CRLF vs LF) — read as BYTES, so Python can't hide \r\n
  3. which of utf-8 / cp932 / shift_jis decode cleanly (a hypothesis, not proof)
  4. first 3 lines, decoded with whichever worked
  5. field count of line 1 vs line 2
"""
import sys


def main():
    # guard argv before indexing it — no path, no crash
    if len(sys.argv) < 2:
        print("usage: uv run python python/inspect_csv.py <path>")
        sys.exit(1)

    path = sys.argv[1]

    # read raw bytes ONCE; everything below works off this
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except FileNotFoundError:
        print(f"file not found: {path}")
        sys.exit(1)

    # 1. size + line count
    size = len(raw)
    line_count = raw.count(b"\n")
    if raw and not raw.endswith(b"\n"):
        line_count += 1  # last line has no terminator, still counts
    print(f"size: {size} bytes")
    print(f"lines: {line_count}")

    # 2. line endings — straight off the bytes, before Python normalizes anything
    if b"\r\n" in raw:
        print("line endings: CRLF (\\r\\n)")
    elif b"\n" in raw:
        print("line endings: LF (\\n)")
    else:
        print("line endings: none found")

    # 3. encoding check — try each, report which decode and which raise
    text = None
    winner = None
    for codec in ("utf-8", "cp932", "shift_jis"):
        try:
            decoded = raw.decode(codec)
        except UnicodeDecodeError:
            print(f"{codec}: raises (illegal byte)")
        else:
            print(f"{codec}: decodes cleanly")
            if text is None:  # keep the first codec that worked
                text, winner = decoded, codec
    print("note: a clean decode means no illegal byte, not proof of identity.")

    if text is None:
        print("no codec decoded cleanly — can't show lines")
        return

    # 4. first 3 lines, decoded with the winner
    lines = text.splitlines()
    print(f"first 3 lines (decoded as {winner}):")
    for line in lines[:3]:
        print(f"  {line}")

    # 5. field count, line 1 vs line 2 — the banner-vs-header tell
    n1 = len(lines[0].split(",")) if len(lines) >= 1 else 0
    n2 = len(lines[1].split(",")) if len(lines) >= 2 else 0
    print(f"fields: line 1 = {n1}, line 2 = {n2}")


if __name__ == "__main__":
    main()
