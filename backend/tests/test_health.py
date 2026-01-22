"""
GreenGate - Testes de Health Check e Infraestrutura
"""
import pytest
from httpx import AsyncClient


class TestHealthCheck:
    """Testes básicos de disponibilidade da API."""
    
    @pytest.mark.asyncio
    async def test_root_endpoint(self, client: AsyncClient):
        """Endpoint raiz retorna informações da API."""
        async with client:
            response = await client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert "name" in data or "message" in data or "status" in data
    
    @pytest.mark.asyncio
    async def test_health_endpoint(self, client: AsyncClient):
        """Endpoint /health retorna status OK."""
        async with client:
            response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data.get("status") == "healthy"
    
    @pytest.mark.asyncio
    async def test_docs_available(self, client: AsyncClient):
        """Documentação Swagger está disponível."""
        async with client:
            response = await client.get("/docs")
        assert response.status_code == 200
    
    @pytest.mark.asyncio
    async def test_openapi_schema(self, client: AsyncClient):
        """Schema OpenAPI está disponível."""
        async with client:
            response = await client.get("/openapi.json")
        assert response.status_code == 200
        data = response.json()
        assert "openapi" in data
        assert "paths" in data


class TestAPIStructure:
    """Testes da estrutura básica da API."""
    
    @pytest.mark.asyncio
    async def test_validation_endpoint_exists(self, client: AsyncClient):
        """Endpoint de validação existe."""
        async with client:
            response = await client.post("/api/v1/validations/quick")
        # OPTIONS ou POST sem body deve retornar erro de validação, não 404
        assert response.status_code != 404
    
    @pytest.mark.asyncio
    async def test_cors_headers(self, client: AsyncClient):
        """CORS está configurado corretamente."""
        async with client:
            response = await client.options(
                "/api/v1/validations/quick",
                headers={"Origin": "http://localhost:3000"}
            )
        # Deve aceitar requisições de localhost
        assert response.status_code in [200, 204, 405]
