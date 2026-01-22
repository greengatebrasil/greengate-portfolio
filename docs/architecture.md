# Architecture Overview

## Stack

| Component | Technology |
|-----------|------------|
| API | FastAPI (Python 3.11) |
| Database | PostgreSQL + PostGIS |
| ORM | SQLAlchemy (async) |
| Validation | Pydantic + Shapely |
| Reports | ReportLab (PDF) |
| Logs | structlog (JSON) |

## Data Flow

```
Request → Middleware → Validation → PostGIS Queries → Response
             │              │              │
         Rate Limit    Geometry      Spatial Joins
         Auth Check    Validation    Overlap Calc
```

## Database Schema

### Core Tables
- `reference_layers` - Geospatial reference data
- `validation_reports` - Audit trail
- `dataset_versions` - Data versioning

## API Structure

```
/api/v1/
├── validations/
│   ├── quick (POST) - Fast validation
│   └── {id} (GET) - Get result
└── reports/
    └── due-diligence/quick (POST) - PDF report
```

## Validation Checks

Each validation runs multiple spatial checks:
1. Deforestation overlap
2. Protected areas intersection
3. Indigenous territory check
4. Water buffer analysis
5. Embargo verification

Results are aggregated into a risk score (0-100).
