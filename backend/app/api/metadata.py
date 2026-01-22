"""
Metadata API Endpoints

Endpoints públicos (sem autenticação) para metadados do sistema,
como datas de atualização dos dados, versões, etc.
"""

from datetime import datetime, timezone
from typing import Dict

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.services.data_freshness import get_data_freshness

router = APIRouter(
    prefix="/metadata",
    tags=["Metadados"],
    # Endpoint público - sem necessidade de API key
)


@router.get("/data-freshness")
async def get_layers_freshness(
    db: AsyncSession = Depends(get_db),
) -> Dict:
    """
    Retorna as datas de última atualização de todas as camadas de dados.

    **Endpoint público** - não requer API key.

    Útil para:
    - Mostrar "última atualização" na interface
    - Validar se os dados estão frescos
    - Monitoramento externo

    Example response:
    ```json
    {
      "layers": {
        "prodes": "2025-12-30T10:30:00Z",
        "embargo_ibama": "2025-12-30T13:01:00Z",
        "terra_indigena": "2025-12-02T12:30:00Z",
        "uc": "2025-12-02T12:31:00Z",
        "quilombola": "2025-12-02T17:52:00Z",
        "mapbiomas": "2025-12-02T22:11:00Z"
      },
      "last_check": "2025-12-30T14:00:00Z"
    }
    ```
    """
    data_freshness = await get_data_freshness(db)

    return {
        "layers": data_freshness,
        "last_check": datetime.now(timezone.utc)
    }
