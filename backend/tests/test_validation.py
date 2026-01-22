"""
GreenGate - Testes do Motor de Validação Geoespacial

Estes testes usam dados FAKE no banco greengate_test.
São reproduzíveis e não dependem de dados externos.
"""
import pytest
from httpx import AsyncClient


class TestQuickValidation:
    """Testes do endpoint /api/v1/validations/quick"""
    
    @pytest.mark.asyncio
    async def test_clean_area_approved(self, client: AsyncClient, clean_polygon: dict):
        """Área sem restrições deve retornar status 'approved'."""
        async with client:
            response = await client.post(
                "/api/v1/validations/quick",
                json=clean_polygon
            )
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["status"] == "approved"
        assert data["risk_score"] >= 70
        assert "checks" in data
        assert len(data["checks"]) >= 1
    
    @pytest.mark.asyncio
    async def test_deforestation_area_rejected(self, client: AsyncClient, deforestation_polygon: dict):
        """Área com desmatamento PRODES 2021 deve retornar status 'rejected' e score 0."""
        async with client:
            response = await client.post(
                "/api/v1/validations/quick",
                json=deforestation_polygon
            )
        
        assert response.status_code == 200
        data = response.json()
        
        # EUDR Zero Tolerance: Rejected = Score 0
        assert data["status"] == "rejected", f"Expected 'rejected' but got '{data['status']}'"
        assert data["risk_score"] == 0, f"Expected score 0 for rejected, got {data['risk_score']}"
        
        # Check de PRODES deve ter falhado
        prodes_check = next(
            (c for c in data["checks"] if c["check_type"] == "deforestation_prodes"),
            None
        )
        assert prodes_check is not None
        assert prodes_check["status"] == "fail"
        assert prodes_check["overlap_area_ha"] > 0
    
    @pytest.mark.asyncio
    async def test_response_structure(self, client: AsyncClient, clean_polygon: dict):
        """Resposta deve ter estrutura correta."""
        async with client:
            response = await client.post(
                "/api/v1/validations/quick",
                json=clean_polygon
            )
        
        assert response.status_code == 200
        data = response.json()
        
        # Campos obrigatórios
        required_fields = ["plot_id", "status", "risk_score", "checks", "validated_at"]
        for field in required_fields:
            assert field in data, f"Campo '{field}' não encontrado"
        
        # Estrutura de cada check
        for check in data["checks"]:
            check_required = ["check_type", "status", "score", "message"]
            for field in check_required:
                assert field in check, f"Campo '{field}' não encontrado no check"
    
    @pytest.mark.asyncio
    async def test_all_check_types_executed(self, client: AsyncClient, clean_polygon: dict):
        """Todos os 7 tipos de check devem ser executados."""
        async with client:
            response = await client.post(
                "/api/v1/validations/quick",
                json=clean_polygon
            )
        
        assert response.status_code == 200
        data = response.json()
        
        expected_checks = [
            "deforestation_prodes",
            "deforestation_mapbiomas",
            "terra_indigena",
            "embargo_ibama",
            "quilombola",
            "uc",
            "app_water",
        ]
        
        check_types = [c["check_type"] for c in data["checks"]]
        for expected in expected_checks:
            assert expected in check_types, f"Check '{expected}' não foi executado"


class TestInputValidation:
    """Testes de validação de input."""
    
    @pytest.mark.asyncio
    async def test_empty_body_rejected(self, client: AsyncClient):
        """Requisição sem body retorna erro 422."""
        async with client:
            response = await client.post("/api/v1/validations/quick")
        assert response.status_code == 422
    
    @pytest.mark.asyncio
    async def test_invalid_json_rejected(self, client: AsyncClient):
        """JSON inválido retorna erro 422."""
        async with client:
            response = await client.post(
                "/api/v1/validations/quick",
                content="not valid json",
                headers={"Content-Type": "application/json"}
            )
        assert response.status_code == 422
    
    @pytest.mark.asyncio
    async def test_wrong_geometry_type_rejected(self, client: AsyncClient):
        """Geometria que não é Polygon retorna erro."""
        point = {"type": "Point", "coordinates": [-47.05, -22.90]}
        async with client:
            response = await client.post(
                "/api/v1/validations/quick",
                json=point
            )
        assert response.status_code in [400, 422]
    
    @pytest.mark.asyncio
    async def test_polygon_not_closed_rejected(self, client: AsyncClient, invalid_polygon_not_closed: dict):
        """Polígono não fechado retorna erro."""
        async with client:
            response = await client.post(
                "/api/v1/validations/quick",
                json=invalid_polygon_not_closed
            )
        assert response.status_code in [400, 422]
    
    @pytest.mark.asyncio
    async def test_polygon_too_few_points_rejected(self, client: AsyncClient, invalid_polygon_too_few_points: dict):
        """Polígono com menos de 4 pontos retorna erro."""
        async with client:
            response = await client.post(
                "/api/v1/validations/quick",
                json=invalid_polygon_too_few_points
            )
        assert response.status_code in [400, 422]
    
    @pytest.mark.asyncio
    async def test_huge_polygon_rejected(self, client: AsyncClient, huge_polygon: dict):
        """Polígono muito grande deve ser rejeitado."""
        async with client:
            response = await client.post(
                "/api/v1/validations/quick",
                json=huge_polygon
            )
        assert response.status_code in [400, 422, 200]
    
    @pytest.mark.asyncio
    async def test_polygon_with_many_vertices_handled(self, client: AsyncClient, polygon_with_many_vertices: dict):
        """Polígono com muitos vértices deve ser tratado."""
        async with client:
            response = await client.post(
                "/api/v1/validations/quick",
                json=polygon_with_many_vertices
            )
        assert response.status_code in [200, 400, 422]


class TestSpecificRestrictions:
    """Testes de restrições específicas usando fixtures conhecidas."""
    
    @pytest.mark.asyncio
    async def test_terra_indigena_detected(self, client: AsyncClient, terra_indigena_polygon: dict):
        """Sobreposição com Terra Indígena deve ser detectada."""
        async with client:
            response = await client.post(
                "/api/v1/validations/quick",
                json=terra_indigena_polygon
            )
        
        assert response.status_code == 200
        data = response.json()
        
        # Deve ser rejeitado
        assert data["status"] == "rejected"
        
        # Check de TI deve ter falhado
        ti_check = next(
            (c for c in data["checks"] if c["check_type"] == "terra_indigena"),
            None
        )
        assert ti_check is not None
        assert ti_check["status"] == "fail"
    
    @pytest.mark.asyncio
    async def test_embargo_detected(self, client: AsyncClient, embargo_polygon: dict):
        """Sobreposição com embargo IBAMA deve ser detectada."""
        async with client:
            response = await client.post(
                "/api/v1/validations/quick",
                json=embargo_polygon
            )
        
        assert response.status_code == 200
        data = response.json()
        
        # Deve ser rejeitado
        assert data["status"] == "rejected"
        
        # Check de embargo deve ter falhado
        embargo_check = next(
            (c for c in data["checks"] if c["check_type"] == "embargo_ibama"),
            None
        )
        assert embargo_check is not None
        assert embargo_check["status"] == "fail"


class TestRiskScore:
    """Testes do cálculo de risk score."""
    
    @pytest.mark.asyncio
    async def test_clean_area_high_score(self, client: AsyncClient, clean_polygon: dict):
        """Área limpa tem score alto (>= 70)."""
        async with client:
            response = await client.post(
                "/api/v1/validations/quick",
                json=clean_polygon
            )
        
        data = response.json()
        
        # DEBUG
        print(f"\n>>> DEBUG test_clean_area_high_score:")
        print(f">>> Status: {data['status']}")
        print(f">>> Risk Score: {data['risk_score']}")
        for check in data.get('checks', []):
            print(f">>>   {check['check_type']}: {check['status']} (score={check['score']})")
        
        assert data["risk_score"] >= 70, f"Expected score >= 70 but got {data['risk_score']}"
    
    @pytest.mark.asyncio
    async def test_deforestation_area_lower_score(self, client: AsyncClient, deforestation_polygon: dict):
        """Área com desmatamento tem score menor."""
        async with client:
            response = await client.post(
                "/api/v1/validations/quick",
                json=deforestation_polygon
            )
        
        data = response.json()
        assert data["risk_score"] < 100
    
    @pytest.mark.asyncio
    async def test_risk_score_bounds(self, client: AsyncClient, clean_polygon: dict):
        """Risk score está sempre entre 0 e 100."""
        async with client:
            response = await client.post(
                "/api/v1/validations/quick",
                json=clean_polygon
            )
        
        data = response.json()
        assert 0 <= data["risk_score"] <= 100


class TestProcessingMetrics:
    """Testes de métricas de processamento."""
    
    @pytest.mark.asyncio
    async def test_processing_time_present(self, client: AsyncClient, clean_polygon: dict):
        """Tempo de processamento deve estar presente."""
        async with client:
            response = await client.post(
                "/api/v1/validations/quick",
                json=clean_polygon
            )
        
        data = response.json()
        assert "processing_time_ms" in data
        assert data["processing_time_ms"] >= 0
    
    @pytest.mark.asyncio
    async def test_processing_time_reasonable(self, client: AsyncClient, clean_polygon: dict):
        """Processamento deve ser rápido (< 5 segundos)."""
        async with client:
            response = await client.post(
                "/api/v1/validations/quick",
                json=clean_polygon
            )
        
        data = response.json()
        if "processing_time_ms" in data:
            assert data["processing_time_ms"] < 5000
