# Deployment Guide

## Railway (Recommended)

### Prerequisites
- Railway account
- GitHub repository connected

### Steps

1. **Create Project**
   - New Project → Deploy from GitHub

2. **Add PostgreSQL**
   - + New → Database → PostgreSQL
   - Enable PostGIS:
   ```sql
   CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
   CREATE EXTENSION IF NOT EXISTS "postgis";
   ```

3. **Configure Variables**
   ```
   DATABASE_URL=${{Postgres.DATABASE_URL}}
   API_KEY=<generate-secure-key>
   DEBUG=false
   ```

4. **Initialize Database**
   - Run `scripts/init_railway_db.sql` in PostgreSQL Query tab

5. **Deploy**
   - Automatic on push to main

### Verify
```bash
curl https://your-app.up.railway.app/health
```

---

## Docker (Local/Self-Hosted)

```bash
docker-compose up -d
```

### Environment Variables

Create `.env` file:
```
DATABASE_URL=postgresql+asyncpg://postgres:postgres@db:5432/greengate
API_KEY=your-secure-key
DEBUG=true
```

---

## Health Endpoints

| Endpoint | Description |
|----------|-------------|
| `/health` | Basic health check |
| `/health/detailed` | Full system status |
