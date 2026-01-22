"""
GreenGate - Modelos SQLAlchemy (ORM)
"""
from datetime import datetime
from typing import Optional
import uuid

from sqlalchemy import (
    Boolean, Column, DateTime, Enum, ForeignKey, Integer, 
    Numeric, String, Text, Index
)
from sqlalchemy.dialects.postgresql import UUID, JSONB, INET
from sqlalchemy.orm import DeclarativeBase, relationship
from geoalchemy2 import Geometry


class Base(DeclarativeBase):
    """Base class para todos os modelos"""
    pass


# =============================================================================
# ENUMS
# =============================================================================

class PlanType(str):
    FREE = "free"
    PRO = "pro"
    BUSINESS = "business"
    ENTERPRISE = "enterprise"


class ComplianceStatus(str):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    WARNING = "warning"


class ValidationStatus(str):
    APPROVED = "approved"
    REJECTED = "rejected"
    WARNING = "warning"


class CheckStatus(str):
    PASS = "pass"
    FAIL = "fail"
    WARNING = "warning"
    SKIP = "skip"


class LayerType(str):
    PRODES = "prodes"
    MAPBIOMAS_ALERT = "mapbiomas_alert"
    TERRA_INDIGENA = "terra_indigena"
    QUILOMBOLA = "quilombola"
    UC = "uc"
    EMBARGO_IBAMA = "embargo_ibama"
    # HIDROGRAFIA = "hidrografia"  # Removido - dados insatisfatórios


# =============================================================================
# MODELS
# =============================================================================

class Organization(Base):
    __tablename__ = "organizations"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    document = Column(String(20), unique=True)  # CNPJ
    plan = Column(String(50), default=PlanType.FREE)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    users = relationship("User", back_populates="organization", cascade="all, delete-orphan")
    properties = relationship("Property", back_populates="organization", cascade="all, delete-orphan")


class User(Base):
    __tablename__ = "users"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"))
    email = Column(String(255), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    name = Column(String(255), nullable=False)
    role = Column(String(50), default="member")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    organization = relationship("Organization", back_populates="users")


class Property(Base):
    __tablename__ = "properties"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    
    name = Column(String(255), nullable=False)
    car_code = Column(String(50))
    state = Column(String(2), nullable=False)
    city = Column(String(255))
    
    geom = Column(Geometry("MULTIPOLYGON", srid=4326))
    area_ha = Column(Numeric(12, 4))
    
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    organization = relationship("Organization", back_populates="properties")
    plots = relationship("Plot", back_populates="property", cascade="all, delete-orphan")
    
    __table_args__ = (
        Index("idx_properties_geom", "geom", postgresql_using="gist"),
    )


class Plot(Base):
    __tablename__ = "plots"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    property_id = Column(UUID(as_uuid=True), ForeignKey("properties.id", ondelete="CASCADE"), nullable=False)
    
    name = Column(String(100), nullable=False)
    code = Column(String(50))
    
    geom = Column(Geometry("POLYGON", srid=4326), nullable=False)
    area_ha = Column(Numeric(10, 4), nullable=False)
    centroid = Column(Geometry("POINT", srid=4326))
    
    crop_type = Column(String(100))
    planting_year = Column(Integer)
    
    compliance_status = Column(String(20), default=ComplianceStatus.PENDING)
    last_validation_at = Column(DateTime(timezone=True))
    risk_score = Column(Integer)
    
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    property = relationship("Property", back_populates="plots")
    validations = relationship("Validation", back_populates="plot", cascade="all, delete-orphan")
    
    __table_args__ = (
        Index("idx_plots_geom", "geom", postgresql_using="gist"),
    )


class ReferenceLayer(Base):
    __tablename__ = "reference_layers"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    layer_type = Column(String(50), nullable=False)
    source_id = Column(String(100))
    source_name = Column(String(255))
    
    geom = Column(Geometry("MULTIPOLYGON", srid=4326), nullable=False)
    area_ha = Column(Numeric(14, 4))
    
    extra_data = Column(JSONB, default={})  # Renamed from 'metadata' (reserved word)
    reference_date = Column(DateTime)
    ingested_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    is_active = Column(Boolean, default=True)
    
    __table_args__ = (
        Index("idx_reflayers_geom", "geom", postgresql_using="gist"),
        Index("idx_reflayers_type", "layer_type"),
    )


class Validation(Base):
    __tablename__ = "validations"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    plot_id = Column(UUID(as_uuid=True), ForeignKey("plots.id", ondelete="CASCADE"), nullable=False)
    
    status = Column(String(20), nullable=False)
    risk_score = Column(Integer, nullable=False)
    
    validated_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    validated_by = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    
    geom_snapshot = Column(Geometry("POLYGON", srid=4326), nullable=False)
    reference_data_version = Column(JSONB, default={})
    
    expires_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    
    # Relationships
    plot = relationship("Plot", back_populates="validations")
    checks = relationship("ValidationCheck", back_populates="validation", cascade="all, delete-orphan")


class ValidationCheck(Base):
    __tablename__ = "validation_checks"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    validation_id = Column(UUID(as_uuid=True), ForeignKey("validations.id", ondelete="CASCADE"), nullable=False)
    
    check_type = Column(String(50), nullable=False)
    status = Column(String(20), nullable=False)
    score = Column(Integer)
    
    message = Column(Text)
    details = Column(JSONB, default={})
    evidence = Column(JSONB, default={})
    
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    
    # Relationships
    validation = relationship("Validation", back_populates="checks")


class Report(Base):
    __tablename__ = "reports"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    plot_id = Column(UUID(as_uuid=True), ForeignKey("plots.id", ondelete="SET NULL"))
    property_id = Column(UUID(as_uuid=True), ForeignKey("properties.id", ondelete="SET NULL"))
    validation_id = Column(UUID(as_uuid=True), ForeignKey("validations.id", ondelete="SET NULL"))
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    
    report_type = Column(String(50), nullable=False)
    format = Column(String(10), default="pdf")
    
    file_path = Column(String(500))
    file_hash = Column(String(64))
    file_size_bytes = Column(Integer)
    
    title = Column(String(255))
    extra_data = Column(JSONB, default={})  # Renamed from 'metadata' (reserved word)
    
    generated_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    generated_by = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    download_count = Column(Integer, default=0)
    expires_at = Column(DateTime(timezone=True))


class Alert(Base):
    __tablename__ = "alerts"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    plot_id = Column(UUID(as_uuid=True), ForeignKey("plots.id", ondelete="CASCADE"))
    property_id = Column(UUID(as_uuid=True), ForeignKey("properties.id", ondelete="CASCADE"))
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    
    alert_type = Column(String(50), nullable=False)
    severity = Column(String(20), nullable=False)
    
    title = Column(String(255), nullable=False)
    message = Column(Text)
    details = Column(JSONB, default={})
    
    status = Column(String(20), default="unread")
    
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    read_at = Column(DateTime(timezone=True))
    resolved_at = Column(DateTime(timezone=True))


class AuditLog(Base):
    __tablename__ = "audit_logs"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="SET NULL"))
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    
    action = Column(String(100), nullable=False)
    entity_type = Column(String(50))
    entity_id = Column(UUID(as_uuid=True))
    
    old_data = Column(JSONB)
    new_data = Column(JSONB)
    
    ip_address = Column(INET)
    user_agent = Column(Text)
    
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)


# =============================================================================
# AUDITORIA DE LAUDOS (CAIXA PRETA)
# =============================================================================

class ValidationReport(Base):
    """
    Registro de auditoria para cada laudo de due diligence gerado.
    
    CAIXA PRETA - Permite:
    - Rastrear QUEM consultou (ip, api_key_hash, user_agent)
    - Rastrear O QUE foi consultado (geometry_geojson completo)
    - Registrar RESULTADO entregue (status, score, checks_summary)
    - Registrar VERSÕES dos datasets (reprodutibilidade)
    - Verificar INTEGRIDADE (geometry_hash, pdf_hash, pdf_signature)
    - REPRODUZIR validação com dados exatos
    """
    __tablename__ = "validation_reports"
    
    # Identificação
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    report_code = Column(String(20), unique=True, nullable=False, 
                        comment="Código único do laudo (ex: GG-ABC12345)")
    
    # Resultado da validação
    status = Column(String(20), nullable=False, comment="approved, rejected, warning")
    risk_score = Column(Integer, nullable=False, comment="Score de risco 0-100")
    
    # Geometria COMPLETA (reprodutibilidade)
    geometry_geojson = Column(JSONB, nullable=False, 
                             comment="Geometria COMPLETA em GeoJSON")
    geometry_hash = Column(String(64), nullable=False, 
                          comment="SHA256 do GeoJSON para verificação")
    geometry_area_ha = Column(Numeric(12, 4), nullable=True)
    geometry_centroid = Column(String(100), nullable=True, comment="lat, lon")
    geometry_bbox = Column(JSONB, nullable=True,
                          comment="Bounding box [minx, miny, maxx, maxy]")
    
    # PDF gerado
    pdf_hash = Column(String(64), nullable=True, comment="SHA256 do PDF")
    pdf_size_bytes = Column(Integer, nullable=True)
    pdf_signature = Column(Text, nullable=True, comment="Assinatura digital (futuro)")
    
    # Versões para reprodutibilidade EXATA
    datasets_version = Column(JSONB, nullable=False, default=dict,
                             comment="Snapshot das versões de cada dataset")
    ruleset_version = Column(String(20), nullable=False, default="v1.0",
                            comment="Versão das regras EUDR")
    api_version = Column(String(20), nullable=False, comment="Versão da API")
    
    # Detalhes da validação
    checks_summary = Column(JSONB, nullable=False, default=dict,
                           comment="Detalhes: {check_type: {status, score, overlap_ha, message}}")
    processing_time_ms = Column(Integer, nullable=True)
    
    # Metadata do request (QUEM consultou)
    request_ip = Column(String(45), nullable=True)
    api_key_hash = Column(String(64), nullable=True, 
                         comment="Hash da API key usada")
    user_agent = Column(Text, nullable=True, comment="Browser/client info")
    
    # Info do talhão/propriedade
    plot_name = Column(String(255), nullable=True)
    crop_type = Column(String(100), nullable=True)
    property_name = Column(String(255), nullable=True)
    state = Column(String(2), nullable=True)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=True,
                       comment="Data de expiração (90 dias)")
    
    # Índices
    __table_args__ = (
        Index('idx_validation_reports_code', 'report_code'),
        Index('idx_validation_reports_status', 'status'),
        Index('idx_validation_reports_created', 'created_at'),
        Index('idx_validation_reports_geom_hash', 'geometry_hash'),
    )
