"""Add performance indexes

Revision ID: 005_performance_indexes
Revises: 004_api_keys
Create Date: 2025-12-18

Adds critical indexes identified in performance audit:
- API Keys: key_prefix, client_name
- Plots: property_id (FK), compliance_status
- Validations: plot_id (FK)
- Validation Checks: validation_id (FK)

Expected performance improvement: 10-50% on queries with JOINs and WHERE clauses
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '005_performance_indexes'
down_revision = '004_api_keys'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add performance indexes."""

    # API Keys indexes
    op.create_index(
        'idx_api_keys_key_prefix',
        'api_keys',
        ['key_prefix'],
        unique=False
    )
    op.create_index(
        'idx_api_keys_client_name',
        'api_keys',
        ['client_name'],
        unique=False
    )

    # Plots indexes
    # Note: property_id FK index is critical for JOINs
    op.create_index(
        'idx_plots_property_id',
        'plots',
        ['property_id'],
        unique=False
    )
    op.create_index(
        'idx_plots_compliance_status',
        'plots',
        ['compliance_status'],
        unique=False
    )

    # Validations indexes
    op.create_index(
        'idx_validations_plot_id',
        'validations',
        ['plot_id'],
        unique=False
    )

    # Validation Checks indexes
    op.create_index(
        'idx_validation_checks_validation_id',
        'validation_checks',
        ['validation_id'],
        unique=False
    )


def downgrade() -> None:
    """Remove performance indexes."""

    # Validation Checks
    op.drop_index('idx_validation_checks_validation_id', table_name='validation_checks')

    # Validations
    op.drop_index('idx_validations_plot_id', table_name='validations')

    # Plots
    op.drop_index('idx_plots_compliance_status', table_name='plots')
    op.drop_index('idx_plots_property_id', table_name='plots')

    # API Keys
    op.drop_index('idx_api_keys_client_name', table_name='api_keys')
    op.drop_index('idx_api_keys_key_prefix', table_name='api_keys')
