# GreenGate

**Environmental Geo-Compliance API** - Validate rural properties and land parcels against Brazilian environmental and regulatory databases.

![Python](https://img.shields.io/badge/Python-3.11+-blue?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-green?logo=fastapi&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-PostGIS-blue?logo=postgresql&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-Ready-blue?logo=docker&logoColor=white)

---

## What is GreenGate?

GreenGate is a geospatial validation engine that checks if land parcels overlap with:

- Deforestation alerts
- Indigenous lands
- Conservation units
- Environmental embargoes
- Permanent Preservation Areas
- Quilombola territories

### Use Cases

- Agricultural supply chain compliance (EUDR)
- ESG due diligence for land investments
- Regulatory reporting automation
- Monitoring system integration

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                              Client                                      │
│                    (Web App / Mobile / System)                           │
└─────────────────────────────────┬───────────────────────────────────────┘
                                  │ HTTPS
                                  ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                           FastAPI Backend                                │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐     │
│  │   Auth      │  │ Validations │  │   Reports   │  │   Admin     │     │
│  │  (JWT/API)  │  │   Engine    │  │    (PDF)    │  │  API Keys   │     │
│  └─────────────┘  └──────┬──────┘  └─────────────┘  └─────────────┘     │
│                          │                                               │
│  ┌───────────────────────┴───────────────────────────────────────┐      │
│  │                    Validation Engine                           │      │
│  │         (Shapely + GeoAlchemy2 + PostGIS)                     │      │
│  └───────────────────────┬───────────────────────────────────────┘      │
└──────────────────────────┼──────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                     PostgreSQL + PostGIS                                 │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐          │
│  │  Reference Data │  │   Validations   │  │   Audit Logs    │          │
│  │  (Geo Layers)   │  │    (Results)    │  │   (History)     │          │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘          │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Tech Stack

| Layer | Technology |
|-------|------------|
| **API** | FastAPI + Pydantic |
| **Database** | PostgreSQL + PostGIS |
| **ORM** | SQLAlchemy 2.0 (async) |
| **Migrations** | Alembic |
| **Auth** | JWT + API Keys + bcrypt |
| **Geo Validation** | Shapely + GeoAlchemy2 |
| **Reports** | ReportLab (PDF) |
| **Deploy** | Docker + Railway |

---

## Running Locally

### Prerequisites

- Python 3.11+
- PostgreSQL 14+ with PostGIS
- Docker (optional)

### With Docker (recommended)

```bash
# Clone the repository
git clone https://github.com/bruno-portfolio/greengate-portfolio.git
cd greengate-portfolio

# Set up environment variables
cp .env.example .env
# Edit .env with your settings

# Start containers
docker-compose up -d
```

### Without Docker

```bash
# Clone the repository
git clone https://github.com/bruno-portfolio/greengate-portfolio.git
cd greengate-portfolio/backend

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
# or: venv\Scripts\activate  # Windows

# Install dependencies
pip install -r requirements.txt

# Set up environment variables
cp ../.env.example ../.env

# Run migrations
alembic upgrade head

# Start the application
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

API available at `http://localhost:8000`

Interactive docs: `http://localhost:8000/docs`

---

## Testing

```bash
cd backend

# Run tests
pytest

# With coverage
pytest --cov=app --cov-report=html
```

---

## Project Structure

```
greengate-portfolio/
├── backend/
│   ├── app/
│   │   ├── api/            # API endpoints
│   │   ├── core/           # Config, auth, database
│   │   ├── models/         # SQLAlchemy + Pydantic models
│   │   ├── services/       # Business logic
│   │   ├── middleware/     # Rate limiting, logging
│   │   └── main.py         # FastAPI entrypoint
│   ├── alembic/            # Database migrations
│   └── tests/              # Automated tests
├── docs/                   # Documentation
├── docker-compose.yml
└── Dockerfile.railway
```

---

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/validate` | Validate geometry against layers |
| `GET` | `/api/v1/validations/{id}` | Get validation result |
| `GET` | `/api/v1/reports/{id}/pdf` | Generate PDF report |
| `POST` | `/api/v1/auth/login` | Admin login |
| `GET` | `/health` | Health check |

Full documentation: `/docs` (Swagger UI)

---

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

**Built with FastAPI + PostGIS**
