"""init_baseline

Revision ID: 6f66885e0588
Revises: 
Create Date: 2026-02-26 04:25:12.984748

"""
from typing import Sequence, Union

from alembic import op

from ainern2d_shared.ainer_db_models import Base


# revision identifiers, used by Alembic.
revision: str = '6f66885e0588'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(
        """
        DO $$
        DECLARE
            row RECORD;
        BEGIN
            FOR row IN
                SELECT tablename
                FROM pg_tables
                WHERE schemaname = 'public'
                  AND tablename <> 'alembic_version'
            LOOP
                EXECUTE format('DROP TABLE IF EXISTS public.%I CASCADE', row.tablename);
            END LOOP;
        END$$;
        """
    )
