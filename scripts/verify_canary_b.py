import sqlite3
from datetime import datetime, timedelta


def verify_canary_b():
    conn = sqlite3.connect("data/news_v3.db")
    cursor = conn.cursor()

    # Check for articles collected in last 20 mins
    cutoff = datetime.now() - timedelta(minutes=20)
    print(f"Checking for articles since {cutoff}")

    cursor.execute(
        """
        SELECT id, title, source_id, collected_date, processing_status, final_score, length(content) 
        FROM articles 
        WHERE collected_date > ?
    """,
        (cutoff,),
    )

    rows = cursor.fetchall()
    print(f"Found {len(rows)} new articles.")
    for r in rows:
        print(f" - {r[1]} ({r[2]}) Score: {r[5]} ContentLen: {r[6]}")

    # Check for headless logs if possible? No, logs are in file.

    conn.close()


if __name__ == "__main__":
    verify_canary_b()
