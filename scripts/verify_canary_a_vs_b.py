import sqlite3


def check_runs():
    conn = sqlite3.connect("data/news_v3.db")
    cursor = conn.cursor()

    # Canary A Window (approx)
    start_a = "2026-02-16 10:53:00"
    end_a = "2026-02-16 10:56:00"

    # Canary B Window (approx)
    start_b = "2026-02-16 11:10:00"  # Adjusted based on recent run
    # Wait, my recent verify_canary_b run was around 11:20?
    # I ran "verify_canary_b.py" at Step 1169 (time now is likely 11:something)
    # The B run started at ?
    # Let me check verify_canary_b results timestamp
    # Ah, I didn't print date.

    # I'll just query everything from cell today and order by date

    print("--- CELL Articles Today ---")
    cursor.execute("""
        SELECT id, title, collected_date, length(content)
        FROM articles
        WHERE source_id = 'cell' AND collected_date > '2026-02-16 00:00:00'
        ORDER BY collected_date ASC
    """)

    rows = cursor.fetchall()
    for r in rows:
        print(f"Time: {r[2]} | Len: {r[3]} | Title: {r[1][:50]}...")

    conn.close()


if __name__ == "__main__":
    check_runs()
