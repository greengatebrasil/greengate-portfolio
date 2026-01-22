"""Add API Keys table

Revision ID: 004_api_keys
Revises: 003_dataset_versions
Create Date: 2025-12-17

Tabela para gerenciar API Keys com controle de quotas e rastreamento de uso.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '004_api_keys'
down_revision: Union[str, None] = '003_dataset_versions'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create api_keys table."""

    op.create_table(
        'api_keys',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('uuid_generate_v4()'), primary_key=True),

        # API Key (hash SHA256)
        sa.Column('key_hash', sa.String(64), nullable=False, unique=True),
        sa.Column('key_prefix', sa.String(20), nullable=False),

        # Cliente
        sa.Column('client_name', sa.String(255), nullable=False),
        sa.Column('client_email', sa.String(255), nullable=True),
        sa.Column('client_document', sa.String(20), nullable=True),

        # Plano e quotas
        sa.Column('plan', sa.String(50), server_default='free', nullable=False),
        sa.Column('monthly_quota', sa.Integer(), nullable=True),  # null = ilimitado

        # Contadores
        sa.Column('total_requests', sa.BigInteger(), server_default='0', nullable=False),
        sa.Column('requests_this_month', sa.Integer(), server_default='0', nullable=False),
        sa.Column('last_reset_at', sa.DateTime(timezone=True), nullable=True),

        # Status
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('is_revoked', sa.Boolean(), server_default='false', nullable=False),

        # Datas
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),

        # Metadados
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_by', sa.String(255), nullable=True),
    )

    # Índices para performance
    op.create_index('idx_api_keys_hash', 'api_keys', ['key_hash'])
    op.create_index('idx_api_keys_prefix', 'api_keys', ['key_prefix'])
    op.create_index('idx_api_keys_active', 'api_keys', ['is_active'])
    op.create_index('idx_api_keys_plan', 'api_keys', ['plan'])
    op.create_index('idx_api_keys_client_email', 'api_keys', ['client_email'])


def downgrade() -> None:
    """Drop api_keys table."""
    op.drop_table('api_keys')
