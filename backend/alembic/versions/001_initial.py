"""Initial schema - GreenGate MVP

Revision ID: 001_initial
Revises: 
Create Date: 2025-11-26

Este migration cria o schema inicial do GreenGate incluindo:
- Tabelas de organização, usuários, propriedades, talhões
- Tabelas de validação e checks
- Tabela de camadas de referência (PRODES, MapBiomas, etc)
- Índices espaciais PostGIS
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import geoalchemy2
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '001_initial'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create initial database schema."""
    
    # Habilitar extensões PostGIS (se não existirem)
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')
    op.execute('CREATE EXTENSION IF NOT EXISTS "postgis"')
    
    # ==========================================================================
    # ORGANIZATIONS
    # ==========================================================================
    op.create_table(
        'organizations',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('uuid_generate_v4()'), primary_key=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('document', sa.String(20), nullable=True),  # CNPJ
        sa.Column('plan', sa.String(20), server_default='free', nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('idx_org_document', 'organizations', ['document'], unique=True)
    
    # ==========================================================================
    # USERS
    # ==========================================================================
    op.create_table(
        'users',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('uuid_generate_v4()'), primary_key=True),
        sa.Column('email', sa.String(255), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('hashed_password', sa.String(255), nullable=False),
        sa.Column('role', sa.String(50), server_default='user', nullable=False),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('organizations.id'), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('last_login', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('idx_users_email', 'users', ['email'], unique=True)
    op.create_index('idx_users_org', 'users', ['organization_id'])
    
    # ==========================================================================
    # PROPERTIES
    # ==========================================================================
    op.create_table(
        'properties',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('uuid_generate_v4()'), primary_key=True),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('organizations.id'), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('car_code', sa.String(50), nullable=True),
        sa.Column('state', sa.String(2), nullable=False),
        sa.Column('city', sa.String(255), nullable=True),
        sa.Column('geom', geoalchemy2.Geometry('MULTIPOLYGON', srid=4326), nullable=True),
        sa.Column('area_ha', sa.Numeric(14, 4), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('idx_properties_org', 'properties', ['organization_id'])
    op.create_index('idx_properties_car', 'properties', ['car_code'])
    op.create_index('idx_properties_geom', 'properties', ['geom'], postgresql_using='gist')
    
    # ==========================================================================
    # PLOTS (Talhões)
    # ==========================================================================
    op.create_table(
        'plots',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('uuid_generate_v4()'), primary_key=True),
        sa.Column('property_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('properties.id'), nullable=False),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('code', sa.String(50), nullable=True),
        sa.Column('crop_type', sa.String(100), nullable=True),
        sa.Column('planting_year', sa.Integer(), nullable=True),
        sa.Column('geom', geoalchemy2.Geometry('MULTIPOLYGON', srid=4326), nullable=False),
        sa.Column('area_ha', sa.Numeric(14, 4), nullable=False),
        sa.Column('centroid', geoalchemy2.Geometry('POINT', srid=4326), nullable=True),
        sa.Column('compliance_status', sa.String(20), server_default='pending', nullable=False),
        sa.Column('risk_score', sa.Integer(), nullable=True),
        sa.Column('last_validation_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('idx_plots_property', 'plots', ['property_id'])
    op.create_index('idx_plots_status', 'plots', ['compliance_status'])
    op.create_index('idx_plots_geom', 'plots', ['geom'], postgresql_using='gist')
    
    # ==========================================================================
    # VALIDATIONS
    # ==========================================================================
    op.create_table(
        'validations',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('uuid_generate_v4()'), primary_key=True),
        sa.Column('plot_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('plots.id'), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('risk_score', sa.Integer(), nullable=False),
        sa.Column('validated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('geom_snapshot', geoalchemy2.Geometry('MULTIPOLYGON', srid=4326), nullable=True),
        sa.Column('reference_data_version', postgresql.JSONB(), server_default='{}'),
        sa.Column('created_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=True),
    )
    op.create_index('idx_validations_plot', 'validations', ['plot_id'])
    op.create_index('idx_validations_date', 'validations', ['validated_at'])
    
    # ==========================================================================
    # VALIDATION_CHECKS
    # ==========================================================================
    op.create_table(
        'validation_checks',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('uuid_generate_v4()'), primary_key=True),
        sa.Column('validation_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('validations.id'), nullable=False),
        sa.Column('check_type', sa.String(50), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('score', sa.Integer(), nullable=True),
        sa.Column('message', sa.Text(), nullable=True),
        sa.Column('details', postgresql.JSONB(), server_default='{}'),
        sa.Column('evidence', postgresql.JSONB(), server_default='{}'),
    )
    op.create_index('idx_checks_validation', 'validation_checks', ['validation_id'])
    op.create_index('idx_checks_type', 'validation_checks', ['check_type'])
    
    # ==========================================================================
    # REFERENCE_LAYERS (PRODES, MapBiomas, TI, UC, etc)
    # ==========================================================================
    op.create_table(
        'reference_layers',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('uuid_generate_v4()'), primary_key=True),
        sa.Column('layer_type', sa.String(50), nullable=False),
        sa.Column('source_id', sa.String(100), nullable=True),
        sa.Column('source_name', sa.String(255), nullable=True),
        sa.Column('geom', geoalchemy2.Geometry('MULTIPOLYGON', srid=4326), nullable=False),
        sa.Column('area_ha', sa.Numeric(14, 4), nullable=True),
        sa.Column('extra_data', postgresql.JSONB(), server_default='{}'),
        sa.Column('reference_date', sa.Date(), nullable=True),
        sa.Column('ingested_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
    )
    op.create_index('idx_reflayers_type', 'reference_layers', ['layer_type'])
    op.create_index('idx_reflayers_geom', 'reference_layers', ['geom'], postgresql_using='gist')
    
    # ==========================================================================
    # REPORTS
    # ==========================================================================
    op.create_table(
        'reports',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('uuid_generate_v4()'), primary_key=True),
        sa.Column('validation_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('validations.id'), nullable=True),
        sa.Column('property_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('properties.id'), nullable=True),
        sa.Column('report_type', sa.String(50), nullable=False),
        sa.Column('format', sa.String(10), server_default='pdf', nullable=False),
        sa.Column('title', sa.String(255), nullable=True),
        sa.Column('file_path', sa.String(500), nullable=True),
        sa.Column('file_hash', sa.String(64), nullable=True),
        sa.Column('generated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('generated_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=True),
    )
    op.create_index('idx_reports_validation', 'reports', ['validation_id'])
    op.create_index('idx_reports_property', 'reports', ['property_id'])


def downgrade() -> None:
    """Drop all tables."""
    op.drop_table('reports')
    op.drop_table('validation_checks')
    op.drop_table('validations')
    op.drop_table('plots')
    op.drop_table('properties')
    op.drop_table('users')
    op.drop_table('organizations')
    op.drop_table('reference_layers')
