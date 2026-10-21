"""Allow publication image waits without holding the global active slot.

Revision ID: f190a1b2c3d4
Revises: e5002f042c48
"""

import sqlalchemy as sa
from alembic import op

revision = "f190a1b2c3d4"
down_revision = "e5002f042c48"
branch_labels = None
depends_on = None
WORKFLOW_RUN_STATUS_VALUES = (
    "queued",
    "running",
    "succeeded",
    "failed",
    "cancelled",
    "interrupted",
    "waiting_for_image",
)

WORKFLOW_RUN_QUEUEABLE_STATUSES = ("queued", "running")


def upgrade():
    checks = {
        c["name"]: c["sqltext"]
        for c in sa.inspect(op.get_bind()).get_check_constraints("workflow_runs")
    }
    with op.batch_alter_table("workflow_runs") as batch:
        if "waiting_for_image" not in checks.get("ck_workflow_runs_status", ""):
            batch.drop_constraint("ck_workflow_runs_status", type_="check")
            batch.create_check_constraint(
                "ck_workflow_runs_status",
                "status IN ("
                + ", ".join(repr(s) for s in WORKFLOW_RUN_STATUS_VALUES)
                + ")",
            )
        if "ck_workflow_runs_image_wait_publication" not in checks:
            batch.create_check_constraint(
                "ck_workflow_runs_image_wait_publication",
                "status != 'waiting_for_image' OR run_type = 'publication'",
            )


def downgrade():
    bind = op.get_bind()
    if bind.execute(
        sa.text("SELECT COUNT(*) FROM workflow_runs WHERE status='waiting_for_image'")
    ).scalar_one():
        raise NotImplementedError(
            "Resolve or interrupt image waits before downgrade; checkpoints must be preserved"
        )
    with op.batch_alter_table("workflow_runs") as batch:
        batch.drop_constraint("ck_workflow_runs_image_wait_publication", type_="check")
        batch.drop_constraint("ck_workflow_runs_status", type_="check")
        batch.create_check_constraint(
            "ck_workflow_runs_status",
            "status IN ("
            + ", ".join(repr(s) for s in WORKFLOW_RUN_STATUS_VALUES[:-1])
            + ")",
        )
