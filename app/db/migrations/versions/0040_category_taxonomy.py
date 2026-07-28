"""Category taxonomy: hierarchical categories for marketplace catalog

Revision ID: 0040_category_taxonomy
Revises: 0039_fts_trgm
"""
from alembic import op

revision = "0040_category_taxonomy"
down_revision = "0039_fts_trgm"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS catalog_categories (
            id          SERIAL PRIMARY KEY,
            parent_id   INTEGER REFERENCES catalog_categories(id) ON DELETE SET NULL,
            name        TEXT NOT NULL,
            slug        TEXT NOT NULL UNIQUE,
            icon        TEXT,
            sort_order  INTEGER NOT NULL DEFAULT 0,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_catalog_categories_parent ON catalog_categories(parent_id)")

    # Seed with common B2B categories (Russian)
    categories = [
        (1, None, "Сырьё и материалы", "raw-materials", "🏭", 10),
        (2, None, "Химия и реагенты", "chemicals", "⚗️", 20),
        (3, None, "Строительные материалы", "construction", "🧱", 30),
        (4, None, "Промышленное оборудование", "equipment", "⚙️", 40),
        (5, None, "Медикаменты и расходники", "medical", "💊", 50),
        (6, None, "Продукты питания оптом", "food", "🌾", 60),
        (7, None, "IT и электроника", "electronics", "💻", 70),
        (8, None, "Спецодежда и СИЗ", "ppe", "🦺", 80),
        (9, None, "Упаковка и тара", "packaging", "📦", 90),
        (10, None, "Другое", "other", "📋", 999),
    ]
    for cat_id, parent_id, name, slug, icon, sort_order in categories:
        parent_expr = f"{parent_id}" if parent_id else "NULL"
        op.execute(
            f"INSERT INTO catalog_categories (id, parent_id, name, slug, icon, sort_order) "
            f"VALUES ({cat_id}, {parent_expr}, $${name}$$, $${slug}$$, $${icon}$$, {sort_order}) "
            f"ON CONFLICT (id) DO NOTHING"
        )
    op.execute("SELECT setval('catalog_categories_id_seq', 100)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS catalog_categories")
