"""Add label_needs_reprint to products, supplier_reviews table"""
from alembic import op
import sqlalchemy as sa

revision = "0020_label_reprint_supplier_rating"
down_revision = "0019_auctions"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("products", sa.Column("label_needs_reprint", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("products", sa.Column("last_label_price", sa.Numeric(18, 2), nullable=True))

    op.create_table(
        "supplier_reviews",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("supplier_id", sa.BigInteger(), sa.ForeignKey("suppliers.id"), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("reviewer_id", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="'pending'"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_supplier_reviews_supplier", "supplier_reviews", ["supplier_id"])
    op.create_check_constraint("supplier_reviews_rating_range", "supplier_reviews", "rating >= 1 AND rating <= 5")
    op.create_check_constraint("supplier_reviews_status_check", "supplier_reviews",
                               "status IN ('pending','approved','rejected')")


def downgrade():
    op.drop_table("supplier_reviews")
    op.drop_column("products", "last_label_price")
    op.drop_column("products", "label_needs_reprint")
