"""
GreenGate - Dataset Version Model

Rastreia versões dos datasets de referência para:
- Reprodutibilidade de laudos
- Auditoria de atualizações
- Garantir uma única versão ativa por layer_type
"""
from datetime import datetime, date
from typing import Optional, Dict, Any
from uuid import uuid4

from sqlalchemy import (
    Column, String, Boolean, DateTime, Date, Text, Integer,
    UniqueConstraint, Index
)
from sqlalchemy.dialects.postgresql import UUID, JSONB

from app.models.database import Base


class DatasetVersion(Base):
    """
    Registra versões de cada dataset de referência.
    
    Apenas uma versão pode estar ativa por layer_type.
    Histórico completo é mantido para auditoria.
    """
    __tablename__ = "dataset_versions"
    
    # Primary Key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    
    # Identificação do dataset
    layer_type = Column(String(50), nullable=False, index=True)
    version = Column(String(50), nullable=False)
    
    # Origem dos dados
    source_url = Column(Text, nullable=True)
    source_date = Column(Date, nullable=True)  # Data de referência dos dados
    
    # Metadados
    record_count = Column(Integer, nullable=True)
    checksum = Column(String(64), nullable=True)  # SHA256 do arquivo original
    extra_info = Column(JSONB, nullable=True, default=dict)  # Info adicional (era 'metadata')
    
    # Ingestão
    ingested_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    ingested_by = Column(String(100), nullable=True)  # Quem executou a ingestão
    notes = Column(Text, nullable=True)
    
    # Status
    is_active = Column(Boolean, default=True, nullable=False, index=True)
    
    # Constraints
    __table_args__ = (
        # Apenas uma versão específica por layer_type
        UniqueConstraint('layer_type', 'version', name='uq_layer_version'),
        # Index composto para busca de versão ativa
        Index('ix_active_layer', 'layer_type', 'is_active'),
    )
    
    def __repr__(self):
        return f"<DatasetVersion {self.layer_type}:{self.version} active={self.is_active}>"
    
    def to_dict(self) -> Dict[str, Any]:
        """Converte para dicionário para uso em laudos."""
        return {
            "version": self.version,
            "source_date": self.source_date.isoformat() if self.source_date else None,
            "record_count": self.record_count,
            "ingested_at": self.ingested_at.isoformat() if self.ingested_at else None,
            "checksum": self.checksum,
        }
