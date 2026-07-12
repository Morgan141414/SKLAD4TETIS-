"""Merge supplier offers and marketplace inquiry source migration branches.

Revision ID: 0046_merge_supplier_offers_marketplace_inquiry_source
Revises: 0018_supplier_offers, 0045_marketplace_inquiry_source
"""

revision = "0046_merge_supplier_offers_marketplace_inquiry_source"
down_revision = ("0018_supplier_offers", "0045_marketplace_inquiry_source")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
