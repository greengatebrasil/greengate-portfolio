"""
GreenGate - Teste de Diagnóstico do Banco
"""
import pytest
from httpx import AsyncClient


class TestDiagnostic:
    """Testes para diagnosticar problemas de conexão."""
    
    @pytest.mark.asyncio
    async def test_check_database_connection(self, client: AsyncClient):
        """Verifica qual banco está sendo usado e se tem dados."""
        
        # Fazer uma validação simples
        polygon = {
            "type": "Polygon",
            "coordinates": [[
                [-47.285, -22.745],
                [-47.285, -22.755],
                [-47.275, -22.755],
                [-47.275, -22.745],
                [-47.285, -22.745]
            ]]
        }
        
        async with client:
            response = await client.post(
                "/api/v1/validations/quick",
                json=polygon
            )
        
        data = response.json()
        
        print("\n" + "="*60)
        print("DIAGNÓSTICO")
        print("="*60)
        print(f"Status: {data.get('status')}")
        print(f"Risk Score: {data.get('risk_score')}")
        print(f"\nChecks:")
        
        for check in data.get('checks', []):
            print(f"  - {check['check_type']}: {check['status']} (score={check['score']})")
            print(f"    Mensagem: {check['message'][:80]}...")
        
        print("="*60)
        
        # Verificar se tem erro nos checks
        skip_checks = [c for c in data.get('checks', []) if c['status'] == 'skip']
        if skip_checks:
            print("\n⚠️  CHECKS COM ERRO:")
            for c in skip_checks:
                print(f"  {c['check_type']}: {c.get('details', {}).get('error', 'N/A')}")
        
        assert response.status_code == 200
