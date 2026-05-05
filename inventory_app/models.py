from __future__ import annotations

from datetime import datetime, timezone

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="viewer")
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)


class Product(db.Model):
    __tablename__ = "products"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    category = db.Column(db.String(120), nullable=False)
    unit = db.Column(db.String(50), nullable=False)
    default_profit_per_unit = db.Column(db.Numeric(14, 2), nullable=False, default=0)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    movements = db.relationship("InventoryMovement", back_populates="product")
    loss_records = db.relationship("LossRecord", back_populates="product")
    delivery_note_lines = db.relationship("DeliveryNoteLine", back_populates="product")


class InventoryMovement(db.Model):
    __tablename__ = "inventory_movements"

    id = db.Column(db.Integer, primary_key=True)
    biz_date = db.Column(db.Date, nullable=False, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    movement_type = db.Column(db.String(20), nullable=False)
    quantity = db.Column(db.Numeric(14, 3), nullable=False)
    profit_per_unit_override = db.Column(db.Numeric(14, 2), nullable=True)
    remark = db.Column(db.Text, nullable=True)
    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    product = db.relationship("Product", back_populates="movements")


class LossRecord(db.Model):
    __tablename__ = "loss_records"

    id = db.Column(db.Integer, primary_key=True)
    biz_date = db.Column(db.Date, nullable=False, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=True)
    loss_quantity = db.Column(db.Numeric(14, 3), nullable=True)
    compensation_amount = db.Column(db.Numeric(14, 2), nullable=False, default=0)
    remark = db.Column(db.Text, nullable=True)
    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    product = db.relationship("Product", back_populates="loss_records")


class DeliveryNote(db.Model):
    __tablename__ = "delivery_notes"

    id = db.Column(db.Integer, primary_key=True)
    customer_name = db.Column(db.String(120), nullable=False)
    contact_person = db.Column(db.String(120), nullable=True)
    delivery_date = db.Column(db.Date, nullable=False, index=True)
    delivery_no = db.Column(db.String(80), nullable=False, unique=True, index=True)
    note_remark = db.Column(db.Text, nullable=True)
    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    lines = db.relationship(
        "DeliveryNoteLine",
        back_populates="delivery_note",
        cascade="all, delete-orphan",
        order_by="DeliveryNoteLine.id.asc()",
    )


class DeliveryNoteLine(db.Model):
    __tablename__ = "delivery_note_lines"

    id = db.Column(db.Integer, primary_key=True)
    delivery_note_id = db.Column(
        db.Integer, db.ForeignKey("delivery_notes.id"), nullable=False, index=True
    )
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    serial_no = db.Column(db.String(50), nullable=True)
    batch_no = db.Column(db.String(120), nullable=True)
    product_name_snapshot = db.Column(db.String(120), nullable=False)
    unit_snapshot = db.Column(db.String(50), nullable=False)
    good_qty = db.Column(db.Numeric(14, 3), nullable=False, default=0)
    defective_qty = db.Column(db.Numeric(14, 3), nullable=False, default=0)
    misc_qty = db.Column(db.Numeric(14, 3), nullable=False, default=0)
    incoming_short_qty = db.Column(db.Numeric(14, 3), nullable=False, default=0)
    incoming_over_qty = db.Column(db.Numeric(14, 3), nullable=False, default=0)
    remark = db.Column(db.Text, nullable=True)
    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    delivery_note = db.relationship("DeliveryNote", back_populates="lines")
    product = db.relationship("Product", back_populates="delivery_note_lines")
