"""
GreenGate - Configuração de Testes

IMPORTANTE: Antes de rodar os testes pela primeira vez, execute:
    Get-Content scripts\\setup_test_db.sql | docker exec -i greengate-db psql -U postgres -d greengate_test
"""
import os
import sys

# =============================================================================
# PASSO 1: FORÇAR BANCO DE TESTE ANTES DE QUALQUER IMPORT
# =============================================================================
os.environ["DATABASE_URL"] = "postgresql+asyncpg://postgres:postgres@localhost:5432/greengate_test"

# Limpar módulos da app se já importados
for mod in list(sys.modules.keys()):
    if mod.startswith("app"):
        del sys.modules[mod]

# =============================================================================
# PASSO 2: IMPORTS
# =============================================================================
import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import NullPool

# =============================================================================
# PASSO 3: CRIAR ENGINE DE TESTE
# =============================================================================
TEST_DB_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/greengate_test"

test_engine = create_async_engine(
    TEST_DB_URL,
    echo=False,
    poolclass=NullPool,
)

test_session_maker = async_sessionmaker(
    bind=test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)

# =============================================================================
# PASSO 4: SUBSTITUIR ENGINE NO MÓDULO DATABASE
# =============================================================================
# Importar database e substituir engine ANTES de importar app
from app.core import database
database.engine = test_engine
database.async_session_maker = test_session_maker

# Agora importar app (vai usar o engine substituído)
from app.main import app
from app.core.database import get_db


async def override_get_db():
    """Substitui get_db para usar o banco de teste."""
    async with test_session_maker() as session:
        try:
            yield session
        finally:
            await session.close()


# Aplicar override também
app.dependency_overrides[get_db] = override_get_db


# =============================================================================
# PYTEST HOOKS
# =============================================================================

def pytest_configure(config):
    """Executado no início da sessão de testes."""
    config.addinivalue_line("markers", "integration: testes de integração")
    config.addinivalue_line("markers", "slow: testes lentos")
    
    print("\n" + "="*60)
    print("🧪 GREENGATE - TESTES (banco: greengate_test)")
    print("="*60 + "\n")


def pytest_unconfigure(config):
    """Limpar ao final dos testes."""
    app.dependency_overrides.clear()


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def client():
    """Cliente HTTP para testar endpoints - NOVO a cada teste."""
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


@pytest.fixture
def clean_polygon() -> dict:
    """Polígono em área LIMPA - sem sobreposição com nenhuma restrição."""
    return {
        "type": "Polygon",
        "coordinates": [[
            [-46.50, -23.50],
            [-46.50, -23.51],
            [-46.49, -23.51],
            [-46.49, -23.50],
            [-46.50, -23.50]
        ]]
    }


@pytest.fixture
def deforestation_polygon() -> dict:
    """Polígono que SOBREPÕE com PRODES 2021 (TEST_PRODES_001)."""
    return {
        "type": "Polygon",
        "coordinates": [[
            [-47.285, -22.745],
            [-47.285, -22.755],
            [-47.275, -22.755],
            [-47.275, -22.745],
            [-47.285, -22.745]
        ]]
    }


@pytest.fixture
def terra_indigena_polygon() -> dict:
    """Polígono que SOBREPÕE com Terra Indígena (TEST_TI_001)."""
    return {
        "type": "Polygon",
        "coordinates": [[
            [-47.48, -22.61],
            [-47.48, -22.63],
            [-47.46, -22.63],
            [-47.46, -22.61],
            [-47.48, -22.61]
        ]]
    }


@pytest.fixture
def embargo_polygon() -> dict:
    """Polígono que SOBREPÕE com embargo IBAMA (TEST_EMB_001)."""
    return {
        "type": "Polygon",
        "coordinates": [[
            [-47.395, -22.705],
            [-47.395, -22.715],
            [-47.385, -22.715],
            [-47.385, -22.705],
            [-47.395, -22.705]
        ]]
    }


@pytest.fixture
def invalid_polygon_not_closed() -> dict:
    """Polígono inválido - não fechado."""
    return {
        "type": "Polygon",
        "coordinates": [[
            [-47.05, -22.90],
            [-47.05, -22.91],
            [-47.04, -22.91],
            [-47.04, -22.90]
        ]]
    }


@pytest.fixture
def invalid_polygon_too_few_points() -> dict:
    """Polígono inválido - menos de 4 pontos."""
    return {
        "type": "Polygon",
        "coordinates": [[
            [-47.05, -22.90],
            [-47.05, -22.91],
            [-47.05, -22.90]
        ]]
    }


@pytest.fixture
def huge_polygon() -> dict:
    """Polígono muito grande - deve ser rejeitado."""
    return {
        "type": "Polygon",
        "coordinates": [[
            [-48.0, -22.0],
            [-48.0, -23.0],
            [-47.0, -23.0],
            [-47.0, -22.0],
            [-48.0, -22.0]
        ]]
    }


@pytest.fixture
def polygon_with_many_vertices() -> dict:
    """Polígono com muitos vértices."""
    import math
    center_lon, center_lat = -47.0, -22.9
    radius = 0.01
    points = []
    for i in range(2000):
        angle = (2 * math.pi * i) / 2000
        lon = center_lon + radius * math.cos(angle)
        lat = center_lat + radius * math.sin(angle)
        points.append([lon, lat])
    points.append(points[0])
    return {"type": "Polygon", "coordinates": [points]}
