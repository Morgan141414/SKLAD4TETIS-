"""Grant the marketplace moderator role to current moderators.

Marketplace moderation used to be gated on Role.WAREHOUSE_MANAGER, so the
public storefront had to hand out a token carrying every permission in the
system. Moderation now runs on Permission.MARKETPLACE_MODERATE, held by the new
Role.MODERATOR (marketplace only) and by Role.WAREHOUSE_MANAGER (which holds
every permission, so sklad-side access is unchanged).

Accounts that moderate today are exactly those holding warehouse_manager. They
keep that role — this only adds 'moderator' alongside it, so they can sign in on
marqet.kz and moderate without the storefront minting a warehouse token.

Revision ID: 0060_marketplace_moderator_role
Revises: 0059_marketplace_auth_throttle
Create Date: 2026-08-07
"""

from alembic import op


revision = "0060_marketplace_moderator_role"
down_revision = "0059_marketplace_auth_throttle"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        UPDATE sklad_users
           SET roles = roles || ',moderator'
         WHERE roles ~ '(^|,)(warehouse_manager|admin)(,|$)'
           AND roles !~ '(^|,)moderator(,|$)'
        """
    )


def downgrade():
    op.execute(
        """
        UPDATE sklad_users
           SET roles = regexp_replace(roles, '(^|,)moderator(,|$)', '\\1')
         WHERE roles ~ '(^|,)moderator(,|$)'
        """
    )
    # Collapse any separator left behind by the removal.
    op.execute("UPDATE sklad_users SET roles = trim(both ',' from regexp_replace(roles, ',,+', ',', 'g'))")
