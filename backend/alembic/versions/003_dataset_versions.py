"""003_dataset_versions

Revision ID: 003
Revises: 002
Create Date: 2024-11-27

Cria tabela dataset_versions para rastrear versões dos datasets de referência.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision: str = '003_dataset_versions'
down_revision: Union[str, None] = '002_audit_table'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Criar tabela dataset_versions
    op.create_table(
        'dataset_versions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, 
                  server_default=sa.text('uuid_generate_v4()')),
        sa.Column('layer_type', sa.String(50), nullable=False, index=True),
        sa.Column('version', sa.String(50), nullable=False),
        sa.Column('source_url', sa.Text, nullable=True),
        sa.Column('source_date', sa.Date, nullable=True),
        sa.Column('record_count', sa.Integer, nullable=True),
        sa.Column('checksum', sa.String(64), nullable=True),
        sa.Column('extra_info', postgresql.JSONB, nullable=True, server_default='{}'),
        sa.Column('ingested_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('NOW()')),
        sa.Column('ingested_by', sa.String(100), nullable=True),
        sa.Column('notes', sa.Text, nullable=True),
        sa.Column('is_active', sa.Boolean, nullable=False, server_default='true', index=True),
        
        # Unique constraint
        sa.UniqueConstraint('layer_type', 'version', name='uq_layer_version'),
    )
    
    # Índice composto para busca de versão ativa
    op.create_index('ix_active_layer', 'dataset_versions', ['layer_type', 'is_active'])
    
    # Comentários
    op.execute("""
        COMMENT ON TABLE dataset_versions IS 
        'Versionamento de datasets de referência para auditoria EUDR';
    """)
    
    # Inserir versões iniciais baseadas nos dados existentes
    op.execute("""
        INSERT INTO dataset_versions (layer_type, version, record_count, ingested_by, notes, is_active)
        SELECT 
            layer_type, 
            '2024.1', 
            COUNT(*),
            'migration_003',
            'Versão inicial criada automaticamente pela migration',
            TRUE
        FROM reference_layers 
        WHERE is_active = true
        GROUP BY layer_type
        ON CONFLICT (layer_type, version) DO NOTHING;
    """)


def downgrade() -> None:
    op.drop_index('ix_active_layer', 'dataset_versions')
    op.drop_table('dataset_versions')
