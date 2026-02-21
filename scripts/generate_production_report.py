import os
import sqlite3

import pandas as pd

DB_PATH = "data/metrics/production/enrichment_metrics.db"
REPORT_PATH = "PRODUCTION_TRAINING_REPORT.md"


def generate_report():
    if not os.path.exists(DB_PATH):
        print(f"ERROR: DB not found at {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)

    # query_basics
    df = pd.read_sql_query("SELECT * FROM enrichment_metrics", conn)

    with open(REPORT_PATH, "w") as f:
        f.write("# Production Training Report\n\n")
        f.write("**Status:** Completed\n")
        f.write(f"**Sources Analyzed:** {len(df)}\n\n")

        # 1. Yield & Success Rates
        f.write("## 1. Yield & Success Rates\n\n")
        f.write("Columns: T=Total, Pub=Publishable, Yield=Pub/T\n\n")

        summary_cols = [
            "source_id",
            "total_enrichment_attempted",
            "total_publishable",
            "http_attempts",
            "http_success",
            "headless_attempts",
            "headless_success",
            "scholarly_attempts",
            "scholarly_success",
        ]

        # Calculate Yield
        df["yield_pct"] = (
            (df["total_publishable"] / df["total_enrichment_attempted"] * 100)
            .fillna(0)
            .round(1)
        )
        df["http_rate"] = (
            (df["http_success"] / df["http_attempts"] * 100).fillna(0).round(1)
        )
        df["headless_rate"] = (
            (df["headless_success"] / df["headless_attempts"] * 100).fillna(0).round(1)
        )

        display_cols = [
            "source_id",
            "total_enrichment_attempted",
            "total_publishable",
            "yield_pct",
            "http_rate",
            "headless_rate",
        ]
        # Use simple string formatting since tabulate is missing
        f.write(
            df[display_cols]
            .sort_values("yield_pct", ascending=False)
            .to_markdown(index=False)
            if hasattr(df, "to_markdown") and False
            else df[display_cols]
            .sort_values("yield_pct", ascending=False)
            .to_string(index=False)
        )
        f.write("\n\n")

        # 2. Headless Impact
        f.write("## 2. Headless Impact (Lift)\n\n")
        headless_df = df[df["headless_attempts"] > 0].copy()
        if not headless_df.empty:
            headless_df["lift"] = headless_df["yield_pct"]
            f.write(
                headless_df[
                    ["source_id", "http_rate", "headless_rate", "headless_attempts"]
                ].to_string(index=False)
            )
        else:
            f.write("No headless attempts recorded.\n")
        f.write("\n\n")

        # 3. Lock Recommendations
        f.write("## 3. Strategy Lock Recommendations\n\n")
        f.write(
            "Criteria: >5 attempts AND (Headless Yield > HTTP Yield + 20% OR HTTP Yield == 0)\n\n"
        )

        recs = []
        for _, row in df.iterrows():
            if row["total_enrichment_attempted"] < 5:
                continue

            http_y = row["http_rate"]
            head_y = row["headless_rate"]

            if row["headless_attempts"] > 0:
                if head_y > (http_y + 20.0) or (http_y < 1.0 and head_y > 20.0):
                    recs.append(
                        f"- **{row['source_id']}**: LOCK to `headless_fallback` (HTTP: {http_y}%, Headless: {head_y}%)"
                    )

            # Scholarly check
            schol_ops = row.get("scholarly_attempts", 0)
            if schol_ops > 0:
                schol_y = row.get("scholarly_success", 0) / schol_ops * 100
                if schol_y > 50:  # Arbitrary high bar
                    recs.append(
                        f"- **{row['source_id']}**: LOCK to `scholarly` (Success: {schol_y}%)"
                    )

        if recs:
            f.write("\n".join(recs))
        else:
            f.write("No locks recommended based on current evidence.")
        f.write("\n")

    conn.close()
    print(f"Report generated at {REPORT_PATH}")


if __name__ == "__main__":
    generate_report()
