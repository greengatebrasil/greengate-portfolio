# API Reference

## Authentication

All requests require `x-api-key` header:
```
x-api-key: your-api-key
```

## Endpoints

### POST /api/v1/validations/quick

Validate a polygon against all reference layers.

**Request:**
```json
{
  "type": "Polygon",
  "coordinates": [[[lon, lat], [lon, lat], ...]]
}
```

**Response:**
```json
{
  "plot_id": "uuid",
  "status": "approved|warning|rejected",
  "risk_score": 0-100,
  "checks": [...],
  "validated_at": "ISO-8601",
  "processing_time_ms": 150
}
```

### GET /health

Basic health check.

**Response:**
```json
{
  "status": "ok",
  "app": "GreenGate",
  "version": "1.0.0"
}
```

### GET /health/detailed

Detailed system status including database connectivity.

## Status Codes

| Code | Meaning |
|------|---------|
| 200 | Success |
| 400 | Invalid request |
| 401 | Unauthorized (missing/invalid API key) |
| 413 | Payload too large |
| 422 | Validation error (invalid geometry) |
| 429 | Rate limit exceeded |
| 500 | Server error |

## Rate Limits

- Authenticated: 100 requests/minute
- Anonymous: 20 requests/minute

Headers included in response:
```
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 95
X-RateLimit-Reset: 1701234567
```

## Geometry Constraints

- Maximum vertices: 10,000
- Maximum area: 10,000 hectares
- Coordinates must be within Brazil bounding box
- Valid GeoJSON Polygon required
