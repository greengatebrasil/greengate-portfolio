"""
GreenGate - Dataset Version Service

Gerencia versões dos datasets de referência:
- Registra novas versões (arquiva antigas automaticamente)
- Retorna versões ativas (com cache)
- Garante consistência transacional
"""
from datetime import date, datetime, timezone
from typing import Optional, Dict, Any, List
from functools import lru_cache
import hashlib

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dataset import DatasetVersion
from app.core.logging_config import get_logger

log = get_logger(__name__)

# Cache TTL em segundos (5 minutos)
_versions_cache: Optional[Dict[str, Dict]] = None
_cache_timestamp: Optional[datetime] = None
CACHE_TTL_SECONDS = 300


class DatasetVersionService:
    """Serviço para gerenciar versões de datasets."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def register_new_version(
        self,
        layer_type: str,
        version: str,
        source_url: Optional[str] = None,
        source_date: Optional[date] = None,
        record_count: Optional[int] = None,
        checksum: Optional[str] = None,
        extra_info: Optional[Dict[str, Any]] = None,
        ingested_by: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> DatasetVersion:
        """
        Registra nova versão de um dataset.
        
        Automaticamente arquiva (is_active=False) versões anteriores
        do mesmo layer_type.
        
        Args:
            layer_type: Tipo do layer (prodes, mapbiomas, etc)
            version: Identificador da versão (2024.1, v8.0, etc)
            source_url: URL de origem dos dados
            source_date: Data de referência dos dados
            record_count: Quantidade de registros
            checksum: SHA256 do arquivo original
            extra_info: Metadados adicionais (JSONB)
            ingested_by: Identificação de quem executou
            notes: Observações
        
        Returns:
            DatasetVersion criado
        """
        global _versions_cache
        
        async with self.db.begin_nested():  # SAVEPOINT
            # 1. Arquivar versões anteriores deste layer_type
            await self.db.execute(
                update(DatasetVersion)
                .where(DatasetVersion.layer_type == layer_type)
                .where(DatasetVersion.is_active == True)
                .values(is_active=False)
            )
            
            # 2. Criar nova versão ativa
            new_version = DatasetVersion(
                layer_type=layer_type,
                version=version,
                source_url=source_url,
                source_date=source_date,
                record_count=record_count,
                checksum=checksum,
                extra_info=extra_info or {},
                ingested_by=ingested_by,
                notes=notes,
                is_active=True,
            )
            
            self.db.add(new_version)
            await self.db.flush()  # Garante que o ID foi gerado
            
            log.info(
                "dataset_version_registered",
                layer_type=layer_type,
                version=version,
                record_count=record_count,
                ingested_by=ingested_by,
            )
        
        # Invalidar cache
        _versions_cache = None
        
        return new_version
    
    async def get_active_versions(self) -> Dict[str, Dict[str, Any]]:
        """
        Retorna todas as versões ativas dos datasets.
        
        Usa cache em memória com TTL de 5 minutos.
        
        Returns:
            Dict no formato:
            {
                "prodes": {"version": "2024.1", "source_date": "2024-08-01", ...},
                "mapbiomas": {"version": "8.0", ...},
                ...
            }
        """
        global _versions_cache, _cache_timestamp
        
        # Verificar cache
        now = datetime.now(timezone.utc)
        if _versions_cache is not None and _cache_timestamp is not None:
            age = (now - _cache_timestamp).total_seconds()
            if age < CACHE_TTL_SECONDS:
                return _versions_cache
        
        # Buscar do banco
        result = await self.db.execute(
            select(DatasetVersion)
            .where(DatasetVersion.is_active == True)
            .order_by(DatasetVersion.layer_type)
        )
        
        versions = {}
        for row in result.scalars():
            versions[row.layer_type] = row.to_dict()
        
        # Atualizar cache
        _versions_cache = versions
        _cache_timestamp = now
        
        log.debug("dataset_versions_loaded", count=len(versions))
        
        return versions
    
    async def get_version_history(
        self, 
        layer_type: str, 
        limit: int = 10
    ) -> List[DatasetVersion]:
        """
        Retorna histórico de versões de um layer_type.
        
        Args:
            layer_type: Tipo do layer
            limit: Máximo de registros
        
        Returns:
            Lista de DatasetVersion ordenada por ingested_at DESC
        """
        result = await self.db.execute(
            select(DatasetVersion)
            .where(DatasetVersion.layer_type == layer_type)
            .order_by(DatasetVersion.ingested_at.desc())
            .limit(limit)
        )
        
        return list(result.scalars())
    
    async def get_active_version(self, layer_type: str) -> Optional[DatasetVersion]:
        """
        Retorna a versão ativa de um layer_type específico.
        
        Args:
            layer_type: Tipo do layer
        
        Returns:
            DatasetVersion ativo ou None
        """
        result = await self.db.execute(
            select(DatasetVersion)
            .where(DatasetVersion.layer_type == layer_type)
            .where(DatasetVersion.is_active == True)
        )
        
        return result.scalar_one_or_none()


def invalidate_versions_cache():
    """Invalida o cache de versões (usar após ingestão)."""
    global _versions_cache, _cache_timestamp
    _versions_cache = None
    _cache_timestamp = None
    log.debug("dataset_versions_cache_invalidated")


def calculate_file_checksum(file_path: str) -> str:
    """
    Calcula SHA256 de um arquivo.
    
    Útil para registrar checksum durante ingestão.
    
    Args:
        file_path: Caminho do arquivo
    
    Returns:
        Hash SHA256 em hexadecimal
    """
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()
