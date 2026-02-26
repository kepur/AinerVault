"""align_skill_21_22_schema

Revision ID: 0f2b6c9b0c7f
Revises: 6f66885e0588
Create Date: 2026-02-26 12:10:00.000000

"""
from typing import Sequence, Union

from alembic import op

from ainern2d_shared.ainer_db_models.preview_models import (
    CharacterVoiceBinding,
    EntityContinuityProfile,
    EntityInstanceLink,
    EntityPreviewVariant,
    PersonaDatasetBinding,
    PersonaIndexBinding,
    PersonaLineageEdge,
    PersonaRuntimeManifest,
)

# revision identifiers, used by Alembic.
revision: str = "0f2b6c9b0c7f"
down_revision: Union[str, Sequence[str], None] = "6f66885e0588"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _upgrade_postgres_enum_jobtype() -> None:
    """Add missing SKILL 21/22 enum values on existing PostgreSQL clusters."""
    ctx = op.get_context()
    with ctx.autocommit_block():
        op.execute(
            """
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM pg_type WHERE typname = 'jobtype') THEN
                    IF NOT EXISTS (
                        SELECT 1
                        FROM pg_enum e
                        JOIN pg_type t ON t.oid = e.enumtypid
                        WHERE t.typname = 'jobtype'
                          AND e.enumlabel = 'resolve_entity_continuity'
                    ) THEN
                        ALTER TYPE jobtype ADD VALUE 'resolve_entity_continuity';
                    END IF;

                    IF NOT EXISTS (
                        SELECT 1
                        FROM pg_enum e
                        JOIN pg_type t ON t.oid = e.enumtypid
                        WHERE t.typname = 'jobtype'
                          AND e.enumlabel = 'manage_persona_dataset_index'
                    ) THEN
                        ALTER TYPE jobtype ADD VALUE 'manage_persona_dataset_index';
                    END IF;
                END IF;
            END$$;
            """
        )


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()

    if bind.dialect.name == "postgresql":
        _upgrade_postgres_enum_jobtype()

    # SKILL 21 tables
    EntityInstanceLink.__table__.create(bind=bind, checkfirst=True)
    EntityPreviewVariant.__table__.create(bind=bind, checkfirst=True)
    EntityContinuityProfile.__table__.create(bind=bind, checkfirst=True)
    CharacterVoiceBinding.__table__.create(bind=bind, checkfirst=True)

    # SKILL 22 tables
    PersonaDatasetBinding.__table__.create(bind=bind, checkfirst=True)
    PersonaIndexBinding.__table__.create(bind=bind, checkfirst=True)
    PersonaLineageEdge.__table__.create(bind=bind, checkfirst=True)
    PersonaRuntimeManifest.__table__.create(bind=bind, checkfirst=True)


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()

    PersonaRuntimeManifest.__table__.drop(bind=bind, checkfirst=True)
    PersonaLineageEdge.__table__.drop(bind=bind, checkfirst=True)
    PersonaIndexBinding.__table__.drop(bind=bind, checkfirst=True)
    PersonaDatasetBinding.__table__.drop(bind=bind, checkfirst=True)
    CharacterVoiceBinding.__table__.drop(bind=bind, checkfirst=True)
    EntityContinuityProfile.__table__.drop(bind=bind, checkfirst=True)
    EntityPreviewVariant.__table__.drop(bind=bind, checkfirst=True)
    EntityInstanceLink.__table__.drop(bind=bind, checkfirst=True)

    # PostgreSQL enum value removal is intentionally skipped because
    # dropping enum labels is unsafe and non-trivial on populated systems.
