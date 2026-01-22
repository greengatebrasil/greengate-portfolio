"""
Data Freshness Service

Consulta as datas de última atualização de cada layer de referência.
Essas datas são usadas no PDF e na interface do app para mostrar
quando os dados foram atualizados pela última vez.
"""

from typing import Dict
from datetime import datetime
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def get_data_freshness(db: AsyncSession) -> Dict[str, datetime]:
    """
    Retorna a data de última atualização de cada layer de referência.

    Args:
        db: Sessão do banco de dados

    Returns:
        Dicionário com layer_type como chave e datetime de última atualização

    Example:
        {
            "prodes": datetime(2025, 12, 30, 10, 30),
            "embargo_ibama": datetime(2025, 12, 30, 13, 1),
            "terra_indigena": datetime(2025, 12, 2, 12, 30),
            "uc": datetime(2025, 12, 2, 12, 31),
            "quilombola": datetime(2025, 12, 2, 17, 52),
            "mapbiomas": datetime(2025, 12, 2, 22, 11)
        }
    """
    query = text("""
        SELECT
            layer_type,
            MAX(ingested_at) as last_updated
        FROM reference_layers
        WHERE is_active = true
        GROUP BY layer_type
        ORDER BY layer_type
    """)

    result = await db.execute(query)
    rows = result.fetchall()

    return {
        row.layer_type: row.last_updated
        for row in rows
    }


async def get_layer_last_update(db: AsyncSession, layer_type: str) -> datetime | None:
    """
    Retorna a data de última atualização de um layer específico.

    Args:
        db: Sessão do banco de dados
        layer_type: Tipo do layer (ex: 'prodes', 'embargo_ibama')

    Returns:
        Datetime da última atualização ou None se layer não encontrado
    """
    query = text("""
        SELECT MAX(ingested_at) as last_updated
        FROM reference_layers
        WHERE layer_type = :layer_type
        AND is_active = true
    """)

    result = await db.execute(query, {"layer_type": layer_type})
    row = result.fetchone()

    return row.last_updated if row else None
