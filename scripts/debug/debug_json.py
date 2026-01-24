import json

try:
    with open("data/exports/latest_articles.json", "r") as f:
        data = json.load(f)

    articles = data.get("articles", [])
    print(f"Searching {len(articles)} articles for ID 213...")

    found = False
    for article in articles:
        aid = str(article.get("id", ""))
        if aid == "213":
            found = True
            print("\n✅ FOUND ID 213 IN EXPORT:")
            print(f"  Title: {article.get('title')}")
            print(f"  URL: {article.get('url')}")
            content = article.get("content", "")
            summary = article.get("summary", "")
            print(f"  Content Length: {len(content) if content else 0}")
            print(f"  Summary Length: {len(summary) if summary else 0}")
            break

    if not found:
        print("❌ ID 213 NOT found in export.")

except Exception as e:
    print(f"Error: {e}")
