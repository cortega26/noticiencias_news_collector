# Monitoring Common Output Format (monitoring.v1)

All monitoring entrypoints emit JSON payloads following this schema:

```json
{
  "version": "monitoring.v1",
  "status": "ok" | "info" | "warning" | "critical",
  "window": {
    "start": "ISO-8601 UTC timestamp",
    "end": "ISO-8601 UTC timestamp"
  },
  "generated_at": "ISO-8601 UTC timestamp",
  "metrics": [
    {"name": "metric.name", "value": 0.1, "unit": "optional", "labels": {"k": "v"}}
  ],
  "anomalies": [
    {
      "detector": "source_outage",
      "severity": "critical",
      "message": "Human readable summary",
      "labels": {"source_id": "nature"},
      "observations": {"ratio": 0.1}
    }
  ],
  "alerts": [
    {
      "title": "Canary failure for nature",
      "severity": "critical",
      "targets": ["pager", "slack://#news-alerts"],
      "runbook_url": "https://runbooks.noticiencias/collector-outage",
      "labels": {"source_id": "nature"},
      "annotations": {"error": "..."}
    }
  ],
  "metadata": {
    "suppressed_sources": ["nature"]
  }
}
```

The `status` field is derived automatically from the highest severity among
anomalies and alerts. All timestamps must be in UTC and ISO-8601 with timezone
offset.
