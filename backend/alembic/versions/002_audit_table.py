"""create validation_reports audit table

Revision ID: 002_audit_table
Revises: 001_initial
Create Date: 2025-11-26
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

# revision identifiers
revision = '002_audit_table'
down_revision = '001_initial'
branch_labels = None
depends_on = None


def upgrade():
    # Tabela de auditoria de validações/laudos (CAIXA PRETA)
    op.create_table(
        'validation_reports',
        
        # Identificação
        sa.Column('id', UUID(as_uuid=True), primary_key=True, 
                  server_default=sa.text('uuid_generate_v4()')),
        sa.Column('report_code', sa.String(20), unique=True, nullable=False,
                  comment='Código único do laudo (ex: GG-ABC12345)'),
        
        # Resultado da validação
        sa.Column('status', sa.String(20), nullable=False,
                  comment='approved, rejected, warning'),
        sa.Column('risk_score', sa.Integer, nullable=False,
                  comment='Score de risco 0-100'),
        
        # Geometria COMPLETA (reprodutibilidade)
        sa.Column('geometry_geojson', JSONB, nullable=False,
                  comment='Geometria COMPLETA em GeoJSON'),
        sa.Column('geometry_hash', sa.String(64), nullable=False,
                  comment='SHA256 do GeoJSON para verificação'),
        sa.Column('geometry_area_ha', sa.Numeric(12, 4), nullable=True),
        sa.Column('geometry_centroid', sa.String(100), nullable=True,
                  comment='Centróide (lat, lon)'),
        sa.Column('geometry_bbox', JSONB, nullable=True,
                  comment='Bounding box [minx, miny, maxx, maxy]'),
        
        # PDF gerado
        sa.Column('pdf_hash', sa.String(64), nullable=True,
                  comment='SHA256 do PDF gerado'),
        sa.Column('pdf_size_bytes', sa.Integer, nullable=True),
        sa.Column('pdf_signature', sa.Text, nullable=True,
                  comment='Assinatura digital do PDF (futuro)'),
        
        # Versões para reprodutibilidade EXATA
        sa.Column('datasets_version', JSONB, nullable=False, server_default='{}',
                  comment='Snapshot das versões de cada dataset'),
        sa.Column('ruleset_version', sa.String(20), nullable=False, server_default='v1.0',
                  comment='Versão das regras EUDR aplicadas'),
        sa.Column('api_version', sa.String(20), nullable=False,
                  comment='Versão da API que gerou o laudo'),
        
        # Detalhes da validação
        sa.Column('checks_summary', JSONB, nullable=False, server_default='{}',
                  comment='Detalhes: {check_type: {status, score, overlap_ha, message}}'),
        sa.Column('processing_time_ms', sa.Integer, nullable=True),
        
        # Metadata do request (QUEM consultou)
        sa.Column('request_ip', sa.String(45), nullable=True,
                  comment='IP do cliente'),
        sa.Column('api_key_hash', sa.String(64), nullable=True,
                  comment='Hash da API key usada'),
        sa.Column('user_agent', sa.Text, nullable=True,
                  comment='User-Agent do cliente'),
        
        # Informações opcionais do talhão/propriedade
        sa.Column('plot_name', sa.String(255), nullable=True),
        sa.Column('crop_type', sa.String(100), nullable=True),
        sa.Column('property_name', sa.String(255), nullable=True),
        sa.Column('state', sa.String(2), nullable=True),
        
        # Timestamps
        sa.Column('created_at', sa.DateTime(timezone=True), 
                  server_default=sa.text('NOW()'), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True,
                  comment='Data de expiração do laudo (90 dias)'),
    )
    
    # Índices para consultas frequentes
    op.create_index('idx_validation_reports_code', 'validation_reports', ['report_code'])
    op.create_index('idx_validation_reports_status', 'validation_reports', ['status'])
    op.create_index('idx_validation_reports_created', 'validation_reports', ['created_at'])
    op.create_index('idx_validation_reports_geom_hash', 'validation_reports', ['geometry_hash'])


def downgrade():
    op.drop_index('idx_validation_reports_geom_hash')
    op.drop_index('idx_validation_reports_created')
    op.drop_index('idx_validation_reports_status')
    op.drop_index('idx_validation_reports_code')
    op.drop_table('validation_reports')
