"""Plot average April 2026 demand per 3 °C temperature bucket."""

import sqlite3
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # file output only, no window
import matplotlib.pyplot as plt
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
QUERY_PATH = REPO_ROOT / "sql" / "queries" / "demand_by_temperature_3c_apr2026.sql"
DB_PATH = Path("/tmp/hokkaido-2026-10-01.db")
OUTPUT_PATH = REPO_ROOT / "outputs" / "rung6" / "demand_by_temperature_3c_apr2026.png"
BUCKET_WIDTH_C = 3


def main() -> None:
    query = QUERY_PATH.read_text(encoding="utf-8")

    with sqlite3.connect(DB_PATH) as conn:
        df = pd.read_sql_query(query, conn)

    print(df)

    fig, ax = plt.subplots(figsize=(10, 6))
    ax.bar(
        df["bucket_lo_c"],
        df["avg_demand_mw"],
        width=BUCKET_WIDTH_C,
        align="edge",  # R11: bar starts at bucket_lo_c, spans 3 °C
        edgecolor="black",
    )
    ax.set_xticks([-3, 0, 3, 6, 9, 12, 15, 18, 21])  # 8 lower edges + last upper edge
    ax.set_xlabel("Temperature (°C)")
    ax.set_ylabel("Average demand (MW)")
    ax.set_title("Hokkaido average demand by 3 °C temperature bucket, April 2026")

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(OUTPUT_PATH, dpi=150)
    plt.close(fig)
    print(f"Saved {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
