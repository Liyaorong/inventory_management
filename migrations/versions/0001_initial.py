"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-04-25
"""
from alembic import op
import sqlalchemy as sa


revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(length=80), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_users_username"), "users", ["username"], unique=True)
    op.create_table(
        "products",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("category", sa.String(length=120), nullable=False),
        sa.Column("unit", sa.String(length=50), nullable=False),
        sa.Column("default_profit_per_unit", sa.Numeric(14, 2), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "delivery_notes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("customer_name", sa.String(length=120), nullable=False),
        sa.Column("contact_person", sa.String(length=120), nullable=True),
        sa.Column("delivery_date", sa.Date(), nullable=False),
        sa.Column("delivery_no", sa.String(length=80), nullable=False),
        sa.Column("note_remark", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_delivery_notes_delivery_date"), "delivery_notes", ["delivery_date"], unique=False)
    op.create_index(op.f("ix_delivery_notes_delivery_no"), "delivery_notes", ["delivery_no"], unique=True)
    op.create_table(
        "inventory_movements",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("biz_date", sa.Date(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("movement_type", sa.String(length=20), nullable=False),
        sa.Column("quantity", sa.Numeric(14, 3), nullable=False),
        sa.Column("profit_per_unit_override", sa.Numeric(14, 2), nullable=True),
        sa.Column("remark", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_inventory_movements_biz_date"), "inventory_movements", ["biz_date"], unique=False)
    op.create_table(
        "loss_records",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("biz_date", sa.Date(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=True),
        sa.Column("loss_quantity", sa.Numeric(14, 3), nullable=True),
        sa.Column("compensation_amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("remark", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_loss_records_biz_date"), "loss_records", ["biz_date"], unique=False)
    op.create_table(
        "delivery_note_lines",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("delivery_note_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("serial_no", sa.String(length=50), nullable=True),
        sa.Column("batch_no", sa.String(length=120), nullable=True),
        sa.Column("product_name_snapshot", sa.String(length=120), nullable=False),
        sa.Column("unit_snapshot", sa.String(length=50), nullable=False),
        sa.Column("good_qty", sa.Numeric(14, 3), nullable=False),
        sa.Column("defective_qty", sa.Numeric(14, 3), nullable=False),
        sa.Column("misc_qty", sa.Numeric(14, 3), nullable=False),
        sa.Column("incoming_short_qty", sa.Numeric(14, 3), nullable=False),
        sa.Column("incoming_over_qty", sa.Numeric(14, 3), nullable=False),
        sa.Column("remark", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["delivery_note_id"], ["delivery_notes.id"]),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_delivery_note_lines_delivery_note_id"), "delivery_note_lines", ["delivery_note_id"], unique=False)


def downgrade():
    op.drop_index(op.f("ix_delivery_note_lines_delivery_note_id"), table_name="delivery_note_lines")
    op.drop_table("delivery_note_lines")
    op.drop_index(op.f("ix_loss_records_biz_date"), table_name="loss_records")
    op.drop_table("loss_records")
    op.drop_index(op.f("ix_inventory_movements_biz_date"), table_name="inventory_movements")
    op.drop_table("inventory_movements")
    op.drop_index(op.f("ix_delivery_notes_delivery_no"), table_name="delivery_notes")
    op.drop_index(op.f("ix_delivery_notes_delivery_date"), table_name="delivery_notes")
    op.drop_table("delivery_notes")
    op.drop_table("products")
    op.drop_index(op.f("ix_users_username"), table_name="users")
    op.drop_table("users")
