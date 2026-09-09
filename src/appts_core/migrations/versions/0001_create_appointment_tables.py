"""create appointment tables

The tables this library owns, in their final shape. This is a squash of five
pets-appts revisions -- the `create_appointments_table` half of
`b732937fb214`, then `a1f3c9d8e2b4` (surrogate id + scheduling columns),
`b94eca323053` (pet_id), `38488164cd7a` (cancellation), and `a26a66e8e83f`
(clinic_availability). The intermediate states are not reproducible from a
library that was never installed while they existed, so they are not
preserved; what is preserved exactly is the end state, down to constraint and
index names, because those are what a schema diff against a host database
compares.

PREREQUISITE TABLES -- the host must have migrated first
    users(id CHAR(36) PK)
    services(id CHAR(36) PK, clinic_id CHAR(36), duration_minutes INT)
    pet_profiles(id CHAR(36) PK)      -- the appointment's *subject*
    clinics(id CHAR(36) PK)           -- the tenant
The foreign keys below are the enforcement; there is no softer check. Running
this against a database without them fails loudly, which is the intent.

The host also needs `ix_services_clinic_id` on its own `services` table: the
overlap query joins through it on every create and every confirm. It is the
host's index on the host's table, so this library does not create it.

ALREADY HAVE THESE TABLES? Do not run this. `alembic -n appts_core stamp head`
adopts an existing schema instead -- see docs/migrations.md.

Revision ID: 0001_appts_core
Revises:
Create Date: 2026-09-06
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0001_appts_core"
down_revision = None
branch_labels = None
depends_on = None


def create_updated_at_trigger() -> None:
    """CREATE OR REPLACE, not CREATE: pets-appts already defines this exact
    function in its own first revision and every timestamped table in the host
    depends on it. Replacing it with an identical body is a no-op there, and
    creates it for a greenfield host that has no such function yet. Dropping
    it on downgrade would break the host's tables, so downgrade() leaves it."""
    op.execute(
        """
        CREATE OR REPLACE FUNCTION update_updated_at_column()
            RETURNS TRIGGER AS
        $$
        BEGIN
            NEW.updated_at = now();
            RETURN NEW;
        END;
        $$ language 'plpgsql';
        """
    )


def timestamps() -> tuple:
    return (
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def create_appointments_table() -> None:
    op.create_table(
        "appointments",
        sa.Column("id", sa.CHAR(36), nullable=False),
        sa.Column(
            "user_id",  # 'user' is a reserved word in postgres, so going with user_id instead
            sa.CHAR(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "service_id",  # going with `service_id` for consistency
            sa.CHAR(36),
            sa.ForeignKey("services.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        # The SUBJECT of the appointment. ondelete="RESTRICT" deliberately
        # blocks deleting a subject that has appointment history rather than
        # silently taking the appointments with it.
        # TODO think if a better approach is a soft delete instead
        sa.Column(
            "pet_id",
            sa.CHAR(36),
            sa.ForeignKey("pet_profiles.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("status", sa.Text, nullable=False, server_default="requested", index=True),
        sa.Column("start_time", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("end_time", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("cancellation_reason", sa.Text, nullable=True),
        # ON DELETE SET NULL, deliberately unlike the neighbouring FKs on this
        # table (user_id CASCADE, pet_id RESTRICT): deleting a staff account
        # must not delete the clinic's appointment history, nor be blocked by
        # it. Losing just the attribution is the right degradation.
        sa.Column(
            "cancelled_by",
            sa.CHAR(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        *timestamps(),
    )
    # Named explicitly rather than via primary_key=True, which would produce
    # `appointments_pkey`. The host's chain reaches `pk_appointments` through
    # create_primary_key, and a schema diff compares constraint names.
    op.create_primary_key("pk_appointments", "appointments", ["id"])
    op.create_index("ix_appointments_pet_id", "appointments", ["pet_id"])
    # Supports the overlap check.
    op.create_index("ix_appointments_service_id_start_time", "appointments", ["service_id", "start_time"])
    op.execute(
        """
        CREATE TRIGGER update_appointments_modtime
            BEFORE UPDATE
            ON appointments
            FOR EACH ROW
        EXECUTE PROCEDURE update_updated_at_column();
        """
    )


def create_clinic_availability_table() -> None:
    op.create_table(
        "clinic_availability",
        sa.Column("id", sa.CHAR(36), primary_key=True),
        sa.Column(
            "clinic_id",
            sa.CHAR(36),
            sa.ForeignKey("clinics.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Weekly recurring hours, keyed by lowercase weekday name, e.g.
        # {"monday": [{"start": "09:00:00", "end": "17:00:00"}], ...}.
        # JSONB rather than a slots-per-row table on purpose -- this is a
        # handful of ranges per day, read and replaced as one blob via
        # GET/PUT, not queried per-row or per-slot. This data's access
        # pattern doesn't earn a join.
        sa.Column("schedule", JSONB, nullable=False, server_default="{}"),
        sa.Column("timezone", sa.Text, nullable=False, server_default="UTC"),
        *timestamps(),
    )

    # One-to-one with clinics -- also what the repository's
    # ON CONFLICT (clinic_id) upsert relies on.
    op.create_unique_constraint(
        "uq_clinic_availability_clinic_id", "clinic_availability", ["clinic_id"]
    )

    op.execute(
        """
        CREATE TRIGGER update_clinic_availability_modtime
            BEFORE UPDATE
            ON clinic_availability
            FOR EACH ROW
        EXECUTE PROCEDURE update_updated_at_column();
        """
    )


def upgrade() -> None:
    create_updated_at_trigger()
    create_appointments_table()
    create_clinic_availability_table()


def downgrade() -> None:
    # update_updated_at_column() is intentionally left in place: the host's
    # own tables use it, and this migration may not have been what created it.
    op.drop_table("clinic_availability")
    op.drop_table("appointments")
