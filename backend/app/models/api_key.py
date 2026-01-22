"""
Modelo de API Keys para controle de acesso e quotas
"""
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4
from sqlalchemy import Column, String, Integer, Boolean, DateTime, BigInteger, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class APIKey(Base):
    """
    API Key para controle de acesso à API GreenGate.

    Cada API key tem:
    - Quotas mensais (ou ilimitadas)
    - Rastreamento de uso
    - Plano associado
    - Possibilidade de expiração
    """
    __tablename__ = 'api_keys'

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)

    # API Key (hash SHA256 para segurança)
    key_hash = Column(String(64), unique=True, nullable=False, index=True)

    # Prefixo visível (para identificação, ex: "gg_live_abcd1234...")
    key_prefix = Column(String(20), nullable=False, index=True)

    # Informações do cliente
    client_name = Column(String(255), nullable=False)
    client_email = Column(String(255), nullable=True)
    client_document = Column(String(20), nullable=True)  # CPF/CNPJ

    # Plano e quotas
    plan = Column(String(50), nullable=False, default='free')  # free, professional, enterprise
    monthly_quota = Column(Integer, nullable=True)  # null = ilimitado

    # Contadores de uso
    total_requests = Column(BigInteger, default=0, nullable=False)
    requests_this_month = Column(Integer, default=0, nullable=False)
    last_reset_at = Column(DateTime(timezone=True), nullable=True)

    # Status
    is_active = Column(Boolean, default=True, nullable=False)
    is_revoked = Column(Boolean, default=False, nullable=False)

    # Datas
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    last_used_at = Column(DateTime(timezone=True), nullable=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)

    # Metadados
    notes = Column(Text, nullable=True)
    created_by = Column(String(255), nullable=True)  # Admin que criou

    def __repr__(self):
        return f"<APIKey {self.key_prefix} - {self.client_name} ({self.plan})>"

    @property
    def is_valid(self) -> bool:
        """Verifica se a API key é válida."""
        if not self.is_active or self.is_revoked:
            return False

        if self.expires_at and datetime.now(timezone.utc) > self.expires_at:
            return False

        return True

    @property
    def has_quota_available(self) -> bool:
        """Verifica se ainda tem quota disponível."""
        if self.monthly_quota is None:
            return True  # Ilimitado

        return self.requests_this_month < self.monthly_quota

    @property
    def quota_remaining(self) -> Optional[int]:
        """Retorna quota restante."""
        if self.monthly_quota is None:
            return None  # Ilimitado

        return max(0, self.monthly_quota - self.requests_this_month)

    @property
    def quota_percentage_used(self) -> Optional[float]:
        """Retorna % de quota usada."""
        if self.monthly_quota is None:
            return None  # Ilimitado

        if self.monthly_quota == 0:
            return 100.0

        return (self.requests_this_month / self.monthly_quota) * 100
