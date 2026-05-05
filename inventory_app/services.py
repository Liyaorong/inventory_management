from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select

from .extensions import db
from .models import DeliveryNote, DeliveryNoteLine, InventoryMovement, LossRecord, Product
from .utils import MONEY_PLACES, QTY_PLACES, format_decimal, to_decimal


def _default_product_day():
    return {
        "inbound_qty": Decimal("0"),
        "output_qty": Decimal("0"),
        "loss_qty": Decimal("0"),
        "defective_qty": Decimal("0"),
        "misc_qty": Decimal("0"),
        "incoming_short_qty": Decimal("0"),
        "incoming_over_qty": Decimal("0"),
        "estimated_profit": Decimal("0"),
        "product_loss_compensation": Decimal("0"),
    }


def _daterange(start_date: date, end_date: date):
    current = start_date
    while current <= end_date:
        yield current
        current += timedelta(days=1)


def get_categories() -> list[str]:
    rows = db.session.execute(
        select(Product.category).distinct().order_by(Product.category)
    ).scalars()
    return [row for row in rows if row]


def get_active_products() -> list[Product]:
    return Product.query.filter_by(is_active=True).order_by(Product.name).all()


def get_recent_movements(limit: int = 10) -> list[InventoryMovement]:
    return (
        InventoryMovement.query.order_by(
            InventoryMovement.biz_date.desc(), InventoryMovement.id.desc()
        )
        .limit(limit)
        .all()
    )


def get_recent_losses(limit: int = 10) -> list[LossRecord]:
    return (
        LossRecord.query.order_by(LossRecord.biz_date.desc(), LossRecord.id.desc())
        .limit(limit)
        .all()
    )


def get_recent_delivery_notes(limit: int = 8) -> list[DeliveryNote]:
    return (
        DeliveryNote.query.order_by(
            DeliveryNote.delivery_date.desc(), DeliveryNote.id.desc()
        )
        .limit(limit)
        .all()
    )


def build_report_data(
    start_date: date,
    end_date: date,
    product_id: int | None = None,
    category: str | None = None,
):
    product_query = Product.query.order_by(Product.name)
    if product_id:
        product_query = product_query.filter(Product.id == product_id)
    elif category:
        product_query = product_query.filter(Product.category == category)

    products = product_query.all()
    product_ids = [product.id for product in products]
    product_map = {product.id: product for product in products}

    if not products:
        return {"summary_rows": [], "detail_rows": [], "products": []}

    movements = (
        InventoryMovement.query.filter(
            InventoryMovement.product_id.in_(product_ids),
            InventoryMovement.biz_date <= end_date,
        )
        .order_by(
            InventoryMovement.biz_date.asc(),
            InventoryMovement.product_id.asc(),
            InventoryMovement.id.asc(),
        )
        .all()
    )

    product_losses = (
        LossRecord.query.filter(
            LossRecord.product_id.isnot(None),
            LossRecord.product_id.in_(product_ids),
            LossRecord.biz_date <= end_date,
        )
        .order_by(LossRecord.biz_date.asc(), LossRecord.id.asc())
        .all()
    )

    global_losses = (
        LossRecord.query.filter(
            LossRecord.product_id.is_(None),
            LossRecord.biz_date >= start_date,
            LossRecord.biz_date <= end_date,
        )
        .order_by(LossRecord.biz_date.asc(), LossRecord.id.asc())
        .all()
    )

    delivery_note_lines = (
        DeliveryNoteLine.query.join(DeliveryNote)
        .filter(
            DeliveryNoteLine.product_id.in_(product_ids),
            DeliveryNote.delivery_date <= end_date,
        )
        .order_by(
            DeliveryNote.delivery_date.asc(),
            DeliveryNoteLine.product_id.asc(),
            DeliveryNoteLine.id.asc(),
        )
        .all()
    )

    by_product_day = defaultdict(_default_product_day)
    opening_balances = defaultdict(lambda: Decimal("0"))

    for movement in movements:
        key = (movement.biz_date, movement.product_id)
        bucket = by_product_day[key]
        quantity = to_decimal(movement.quantity)
        if movement.biz_date < start_date:
            if movement.movement_type == "INBOUND":
                opening_balances[movement.product_id] += quantity
            else:
                opening_balances[movement.product_id] -= quantity
            continue

        if movement.movement_type == "INBOUND":
            bucket["inbound_qty"] += quantity
        else:
            bucket["output_qty"] += quantity
            effective_profit = (
                to_decimal(movement.profit_per_unit_override)
                if movement.profit_per_unit_override is not None
                else to_decimal(product_map[movement.product_id].default_profit_per_unit)
            )
            bucket["estimated_profit"] += quantity * effective_profit

    for loss in product_losses:
        key = (loss.biz_date, loss.product_id)
        loss_qty = to_decimal(loss.loss_quantity) if loss.loss_quantity is not None else Decimal("0")
        compensation = to_decimal(loss.compensation_amount)
        if loss.biz_date < start_date:
            opening_balances[loss.product_id] -= loss_qty
            continue

        bucket = by_product_day[key]
        bucket["loss_qty"] += loss_qty
        bucket["product_loss_compensation"] += compensation

    for line in delivery_note_lines:
        biz_date = line.delivery_note.delivery_date
        key = (biz_date, line.product_id)
        bucket = by_product_day[key]

        good_qty = to_decimal(line.good_qty)
        defective_qty = to_decimal(line.defective_qty)
        misc_qty = to_decimal(line.misc_qty)
        incoming_short_qty = to_decimal(line.incoming_short_qty)
        incoming_over_qty = to_decimal(line.incoming_over_qty)
        derived_loss_qty = defective_qty + misc_qty + incoming_short_qty

        if biz_date < start_date:
            opening_balances[line.product_id] += incoming_over_qty
            opening_balances[line.product_id] -= good_qty + derived_loss_qty
            continue

        bucket["incoming_over_qty"] += incoming_over_qty
        bucket["inbound_qty"] += incoming_over_qty
        bucket["output_qty"] += good_qty
        bucket["defective_qty"] += defective_qty
        bucket["misc_qty"] += misc_qty
        bucket["incoming_short_qty"] += incoming_short_qty
        bucket["loss_qty"] += derived_loss_qty
        bucket["estimated_profit"] += (
            good_qty * to_decimal(product_map[line.product_id].default_profit_per_unit)
        )

    global_loss_by_day = defaultdict(lambda: Decimal("0"))
    for loss in global_losses:
        global_loss_by_day[loss.biz_date] += to_decimal(loss.compensation_amount)

    detail_rows = []
    summary_rows = []

    running_balances = defaultdict(lambda: Decimal("0"))
    running_balances.update(opening_balances)

    for current_date in _daterange(start_date, end_date):
        summary = {
            "biz_date": current_date.isoformat(),
            "total_inbound_qty": Decimal("0"),
            "total_output_qty": Decimal("0"),
            "total_loss_qty": Decimal("0"),
            "total_defective_qty": Decimal("0"),
            "total_misc_qty": Decimal("0"),
            "total_incoming_short_qty": Decimal("0"),
            "total_incoming_over_qty": Decimal("0"),
            "total_closing_balance": Decimal("0"),
            "estimated_profit": Decimal("0"),
            "product_loss_compensation": Decimal("0"),
            "global_loss_compensation": global_loss_by_day[current_date],
        }

        day_has_product_data = False
        for product in products:
            key = (current_date, product.id)
            bucket = by_product_day[key]
            opening_balance = running_balances[product.id]
            closing_balance = (
                opening_balance
                + bucket["inbound_qty"]
                - bucket["output_qty"]
                - bucket["loss_qty"]
            )

            if any(
                value != Decimal("0")
                for value in (
                    opening_balance,
                    bucket["inbound_qty"],
                    bucket["output_qty"],
                    bucket["loss_qty"],
                    bucket["defective_qty"],
                    bucket["misc_qty"],
                    bucket["incoming_short_qty"],
                    bucket["incoming_over_qty"],
                    closing_balance,
                    bucket["estimated_profit"],
                    bucket["product_loss_compensation"],
                )
            ):
                day_has_product_data = True
                detail_rows.append(
                    {
                        "biz_date": current_date.isoformat(),
                        "product_name": product.name,
                        "category": product.category,
                        "unit": product.unit,
                        "opening_balance": opening_balance.quantize(QTY_PLACES),
                        "inbound_qty": bucket["inbound_qty"].quantize(QTY_PLACES),
                        "output_qty": bucket["output_qty"].quantize(QTY_PLACES),
                        "loss_qty": bucket["loss_qty"].quantize(QTY_PLACES),
                        "defective_qty": bucket["defective_qty"].quantize(QTY_PLACES),
                        "misc_qty": bucket["misc_qty"].quantize(QTY_PLACES),
                        "incoming_short_qty": bucket["incoming_short_qty"].quantize(
                            QTY_PLACES
                        ),
                        "incoming_over_qty": bucket["incoming_over_qty"].quantize(
                            QTY_PLACES
                        ),
                        "closing_balance": closing_balance.quantize(QTY_PLACES),
                        "estimated_profit": bucket["estimated_profit"].quantize(
                            MONEY_PLACES
                        ),
                        "product_loss_compensation": bucket[
                            "product_loss_compensation"
                        ].quantize(MONEY_PLACES),
                        "net_profit_after_product_loss": (
                            bucket["estimated_profit"]
                            - bucket["product_loss_compensation"]
                        ).quantize(MONEY_PLACES),
                    }
                )

            summary["total_inbound_qty"] += bucket["inbound_qty"]
            summary["total_output_qty"] += bucket["output_qty"]
            summary["total_loss_qty"] += bucket["loss_qty"]
            summary["total_defective_qty"] += bucket["defective_qty"]
            summary["total_misc_qty"] += bucket["misc_qty"]
            summary["total_incoming_short_qty"] += bucket["incoming_short_qty"]
            summary["total_incoming_over_qty"] += bucket["incoming_over_qty"]
            summary["total_closing_balance"] += closing_balance
            summary["estimated_profit"] += bucket["estimated_profit"]
            summary["product_loss_compensation"] += bucket["product_loss_compensation"]

            running_balances[product.id] = closing_balance

        total_compensation = (
            summary["product_loss_compensation"] + summary["global_loss_compensation"]
        )
        summary["actual_profit"] = summary["estimated_profit"] - total_compensation

        if day_has_product_data or summary["global_loss_compensation"] != Decimal("0"):
            summary_rows.append(
                {
                    "biz_date": summary["biz_date"],
                    "total_inbound_qty": summary["total_inbound_qty"].quantize(
                        QTY_PLACES
                    ),
                    "total_output_qty": summary["total_output_qty"].quantize(
                        QTY_PLACES
                    ),
                    "total_loss_qty": summary["total_loss_qty"].quantize(QTY_PLACES),
                    "total_defective_qty": summary["total_defective_qty"].quantize(
                        QTY_PLACES
                    ),
                    "total_misc_qty": summary["total_misc_qty"].quantize(QTY_PLACES),
                    "total_incoming_short_qty": summary[
                        "total_incoming_short_qty"
                    ].quantize(QTY_PLACES),
                    "total_incoming_over_qty": summary[
                        "total_incoming_over_qty"
                    ].quantize(QTY_PLACES),
                    "total_closing_balance": summary["total_closing_balance"].quantize(
                        QTY_PLACES
                    ),
                    "estimated_profit": summary["estimated_profit"].quantize(
                        MONEY_PLACES
                    ),
                    "product_loss_compensation": summary[
                        "product_loss_compensation"
                    ].quantize(MONEY_PLACES),
                    "global_loss_compensation": summary[
                        "global_loss_compensation"
                    ].quantize(MONEY_PLACES),
                    "total_compensation": total_compensation.quantize(MONEY_PLACES),
                    "actual_profit": summary["actual_profit"].quantize(MONEY_PLACES),
                }
            )

    return {"summary_rows": summary_rows, "detail_rows": detail_rows, "products": products}


def build_dashboard(target_date: date):
    report = build_report_data(target_date, target_date)
    if report["summary_rows"]:
        summary = report["summary_rows"][0]
    else:
        summary = {
            "total_inbound_qty": Decimal("0"),
            "total_output_qty": Decimal("0"),
            "total_closing_balance": Decimal("0"),
            "estimated_profit": Decimal("0"),
            "total_compensation": Decimal("0"),
            "actual_profit": Decimal("0"),
        }

    return {
        "biz_date": target_date.isoformat(),
        "total_inbound_qty": summary["total_inbound_qty"],
        "total_output_qty": summary["total_output_qty"],
        "total_closing_balance": summary["total_closing_balance"],
        "estimated_profit": summary["estimated_profit"],
        "total_compensation": summary["total_compensation"],
        "actual_profit": summary["actual_profit"],
        "active_product_count": Product.query.filter_by(is_active=True).count(),
        "recent_movements": get_recent_movements(),
        "recent_losses": get_recent_losses(),
        "recent_delivery_notes": get_recent_delivery_notes(),
    }


def serialize_for_export(rows: list[dict]) -> list[dict]:
    integer_qty_keys = {
        "defective_qty",
        "misc_qty",
        "incoming_short_qty",
        "incoming_over_qty",
        "total_defective_qty",
        "total_misc_qty",
        "total_incoming_short_qty",
        "total_incoming_over_qty",
    }
    serialized = []
    for row in rows:
        item = {}
        for key, value in row.items():
            if isinstance(value, Decimal):
                if key in integer_qty_keys:
                    item[key] = format_decimal(value, 0)
                else:
                    item[key] = format_decimal(
                        value, 3 if "qty" in key or "balance" in key else 2
                    )
            else:
                item[key] = value
        serialized.append(item)
    return serialized
