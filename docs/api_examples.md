# Noticiencias API Examples

## List ranked articles

**Request**

```
GET /v1/articles?source=nature&topic=health&page_size=1
```

**Response**

```json
{
  "data": [
    {
      "id": 42,
      "title": "CRISPR gene therapy milestone",
      "summary": "Breakthrough in CRISPR gene therapy",
      "url": "https://example.com/crispr",
      "source": {
        "id": "nature",
        "name": "Nature"
      },
      "category": "science",
      "topics": [
        "science",
        "health"
      ],
      "published_at": "2025-10-01T04:15:00+00:00",
      "collected_at": "2025-10-01T06:05:00+00:00",
      "final_score": 0.92,
      "score_components": {
        "source_credibility": 0.95,
        "recency": 0.85,
        "content_quality": 0.9,
        "engagement_potential": 0.88
      },
      "why_ranked": [
        "Fuente altamente confiable",
        "Publicado hace pocas horas",
        "Contenido con alta calidad científica"
      ]
    }
  ],
  "pagination": {
    "next_cursor": "MC45MjAwMDB8MjAyNS0xMC0wMVQwNjowNTowMCswMDowMHw0Mg==",
    "has_more": true,
    "page_size": 1,
    "returned": 1
  },
  "filters": {
    "source": [
      "nature"
    ],
    "topic": [
      "health"
    ],
    "date_from": null,
    "date_to": null
  },
  "meta": {
    "generated_at": "2025-10-01T06:05:02.143201+00:00"
  }
}
```

## Health probe

**Request**

```
GET /healthz
```

**Response**

```json
{
  "status": "ok",
  "details": {
    "status": "healthy",
    "total_articles": 1835,
    "pending_articles": 12,
    "recent_articles": 148,
    "active_sources": 37,
    "failed_sources": 0,
    "last_updated": "2025-10-01T05:59:41.112313+00:00"
  }
}
```

## Readiness probe

**Request**

```
GET /readyz
```

**Response**

```json
{
  "status": "ready"
}
```
