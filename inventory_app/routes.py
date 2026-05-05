from __future__ import annotations

from datetime import date
from io import BytesIO

import pandas as pd
from flask import (
    Blueprint,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from sqlalchemy.orm import selectinload

from flask_login import current_user

from .auth import ROLE_ADMIN, ROLE_OPERATOR, admin_required, login_disabled, role_required
from .excel import (
    build_movement_template,
    build_product_template,
    create_workbook_bytes,
    parse_movement_import,
    parse_product_import,
)
from .extensions import db
from .models import (
    DeliveryNote,
    DeliveryNoteLine,
    InventoryMovement,
    LossRecord,
    Product,
)
from .services import build_dashboard, build_report_data, get_active_products, get_categories
from .utils import (
    MONEY_PLACES,
    QTY_PLACES,
    normalize_movement_type,
    parse_date,
    parse_non_negative_decimal,
    parse_non_negative_integer,
    parse_optional_decimal,
)


bp = Blueprint("main", __name__)


def _send_workbook(workbook: BytesIO, filename: str):
    return send_file(
        workbook,
        as_attachment=True,
        download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def _parse_int(value, field_name: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name}无效") from exc


def _ensure_product_exists(product_id: int) -> Product:
    product = db.session.get(Product, product_id)
    if not product:
        raise ValueError("商品不存在")
    return product


def _product_is_referenced(product_id: int) -> bool:
    has_movement = (
        db.session.query(InventoryMovement.id).filter_by(product_id=product_id).first()
        is not None
    )
    has_loss = (
        db.session.query(LossRecord.id).filter_by(product_id=product_id).first()
        is not None
    )
    has_delivery_line = (
        db.session.query(DeliveryNoteLine.id).filter_by(product_id=product_id).first()
        is not None
    )
    return has_movement or has_loss or has_delivery_line


def _parse_delivery_note_lines(form) -> list[dict]:
    serial_nos = form.getlist("serial_no[]")
    batch_nos = form.getlist("batch_no[]")
    product_ids = form.getlist("product_id[]")
    units = form.getlist("unit[]")
    good_qtys = form.getlist("good_qty[]")
    defective_qtys = form.getlist("defective_qty[]")
    misc_qtys = form.getlist("misc_qty[]")
    incoming_short_qtys = form.getlist("incoming_short_qty[]")
    incoming_over_qtys = form.getlist("incoming_over_qty[]")
    remarks = form.getlist("line_remark[]")

    line_count = max(
        len(serial_nos),
        len(batch_nos),
        len(product_ids),
        len(units),
        len(good_qtys),
        len(defective_qtys),
        len(misc_qtys),
        len(incoming_short_qtys),
        len(incoming_over_qtys),
        len(remarks),
    )

    parsed_lines = []
    for index in range(line_count):
        serial_no = serial_nos[index].strip() if index < len(serial_nos) else ""
        batch_no = batch_nos[index].strip() if index < len(batch_nos) else ""
        product_id_raw = product_ids[index].strip() if index < len(product_ids) else ""
        unit = units[index].strip() if index < len(units) else ""
        remark = remarks[index].strip() if index < len(remarks) else ""

        good_qty = parse_non_negative_integer(
            good_qtys[index] if index < len(good_qtys) else "0",
            f"第 {index + 1} 行良品出货数",
        )
        defective_qty = parse_non_negative_integer(
            defective_qtys[index] if index < len(defective_qtys) else "0",
            f"第 {index + 1} 行不良品数",
        )
        misc_qty = parse_non_negative_integer(
            misc_qtys[index] if index < len(misc_qtys) else "0",
            f"第 {index + 1} 行杂料",
        )
        incoming_short_qty = parse_non_negative_integer(
            incoming_short_qtys[index] if index < len(incoming_short_qtys) else "0",
            f"第 {index + 1} 行来料少数",
        )
        incoming_over_qty = parse_non_negative_integer(
            incoming_over_qtys[index] if index < len(incoming_over_qtys) else "0",
            f"第 {index + 1} 行来料多数",
        )

        is_blank_row = (
            not serial_no
            and not batch_no
            and not product_id_raw
            and not unit
            and good_qty == 0
            and defective_qty == 0
            and misc_qty == 0
            and incoming_short_qty == 0
            and incoming_over_qty == 0
            and not remark
        )
        if is_blank_row:
            continue

        if not product_id_raw:
            raise ValueError(f"第 {index + 1} 行产品名称不能为空")

        product = _ensure_product_exists(_parse_int(product_id_raw, "产品名称"))
        if (
            good_qty == 0
            and defective_qty == 0
            and misc_qty == 0
            and incoming_short_qty == 0
            and incoming_over_qty == 0
        ):
            raise ValueError(f"第 {index + 1} 行至少填写一个数量")

        parsed_lines.append(
            {
                "product_id": product.id,
                "serial_no": serial_no,
                "batch_no": batch_no,
                "product_name_snapshot": product.name,
                "unit_snapshot": unit or product.unit,
                "good_qty": good_qty,
                "defective_qty": defective_qty,
                "misc_qty": misc_qty,
                "incoming_short_qty": incoming_short_qty,
                "incoming_over_qty": incoming_over_qty,
                "remark": remark,
            }
        )

    if not parsed_lines:
        raise ValueError("至少录入一行送货单明细")

    return parsed_lines


@bp.route("/")
def dashboard():
    target_date = parse_date(request.args.get("biz_date") or date.today().isoformat())
    metrics = build_dashboard(target_date)
    return render_template("dashboard.html", metrics=metrics)


@bp.route("/products", methods=["GET", "POST"])
def products():
    if request.method == "POST":
        if not login_disabled() and current_user.role != ROLE_ADMIN:
            return role_required(ROLE_ADMIN)(lambda: None)()
        try:
            name = request.form["name"].strip()
            if Product.query.filter_by(name=name).first():
                raise ValueError("商品名称已存在")

            product = Product(
                name=name,
                category=request.form["category"].strip(),
                unit=request.form["unit"].strip(),
                default_profit_per_unit=parse_non_negative_decimal(
                    request.form["default_profit_per_unit"], "默认单件毛利润", MONEY_PLACES
                ),
                is_active=request.form.get("is_active") == "on",
            )

            if not product.name or not product.category or not product.unit:
                raise ValueError("商品名称、类别、单位不能为空")

            db.session.add(product)
            db.session.commit()
            flash("商品已创建", "success")
            return redirect(url_for("main.products"))
        except Exception as exc:
            db.session.rollback()
            flash(str(exc), "danger")

    product_list = Product.query.order_by(Product.is_active.desc(), Product.name.asc()).all()
    return render_template("products.html", products=product_list)


@bp.route("/products/<int:product_id>/edit", methods=["GET", "POST"])
@admin_required
def edit_product(product_id: int):
    product = db.get_or_404(Product, product_id)
    if request.method == "POST":
        try:
            duplicate = Product.query.filter(
                Product.name == request.form["name"].strip(),
                Product.id != product.id,
            ).first()
            if duplicate:
                raise ValueError("商品名称已存在")

            product.name = request.form["name"].strip()
            product.category = request.form["category"].strip()
            product.unit = request.form["unit"].strip()
            product.default_profit_per_unit = parse_non_negative_decimal(
                request.form["default_profit_per_unit"], "默认单件毛利润", MONEY_PLACES
            )
            product.is_active = request.form.get("is_active") == "on"

            if not product.name or not product.category or not product.unit:
                raise ValueError("商品名称、类别、单位不能为空")

            db.session.commit()
            flash("商品已更新", "success")
            return redirect(url_for("main.products"))
        except Exception as exc:
            db.session.rollback()
            flash(str(exc), "danger")

    return render_template("product_edit.html", product=product)


@bp.route("/products/<int:product_id>/toggle", methods=["POST"])
@admin_required
def toggle_product(product_id: int):
    product = db.get_or_404(Product, product_id)
    product.is_active = not product.is_active
    db.session.commit()
    flash("商品状态已更新", "success")
    return redirect(url_for("main.products"))


@bp.route("/products/<int:product_id>/delete", methods=["POST"])
@admin_required
def delete_product(product_id: int):
    product = db.get_or_404(Product, product_id)
    if _product_is_referenced(product_id):
        flash("该商品已经被流水、亏损或送货单使用，不能删除，只能停用", "warning")
        return redirect(url_for("main.products"))

    db.session.delete(product)
    db.session.commit()
    flash("商品已删除", "success")
    return redirect(url_for("main.products"))


@bp.route("/products/template")
@admin_required
def products_template():
    return _send_workbook(build_product_template(), "商品导入模板.xlsx")


@bp.route("/products/import", methods=["POST"])
@admin_required
def products_import():
    file_storage = request.files.get("file")
    if not file_storage or not file_storage.filename:
        flash("请选择 Excel 文件", "warning")
        return redirect(url_for("main.products"))

    try:
        records = parse_product_import(file_storage)
        for record in records:
            db.session.add(Product(**record))
        db.session.commit()
        flash(f"成功导入 {len(records)} 个商品", "success")
    except Exception as exc:
        db.session.rollback()
        flash(str(exc), "danger")
    return redirect(url_for("main.products"))


@bp.route("/products/export")
@admin_required
def products_export():
    rows = []
    for product in Product.query.order_by(Product.name.asc()).all():
        rows.append(
            {
                "商品名称": product.name,
                "商品类别": product.category,
                "单位": product.unit,
                "默认单件毛利润": product.default_profit_per_unit,
                "是否启用": "是" if product.is_active else "否",
                "创建时间": product.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            }
        )
    workbook = create_workbook_bytes({"products": pd.DataFrame(rows)})
    return _send_workbook(workbook, "商品主数据.xlsx")


@bp.route("/delivery-notes", methods=["GET", "POST"])
def delivery_notes():
    if (
        request.method == "POST"
        and not login_disabled()
        and current_user.role not in (ROLE_ADMIN, ROLE_OPERATOR)
    ):
        return role_required(ROLE_ADMIN, ROLE_OPERATOR)(lambda: None)()
    selected_date = parse_date(request.args.get("delivery_date") or date.today().isoformat())
    if request.method == "POST":
        try:
            delivery_no = request.form["delivery_no"].strip()
            if not delivery_no:
                raise ValueError("送货单号不能为空")
            if DeliveryNote.query.filter_by(delivery_no=delivery_no).first():
                raise ValueError("送货单号已存在")

            lines = _parse_delivery_note_lines(request.form)
            note = DeliveryNote(
                customer_name=request.form["customer_name"].strip(),
                contact_person=request.form.get("contact_person", "").strip(),
                delivery_date=parse_date(request.form["delivery_date"]),
                delivery_no=delivery_no,
                note_remark=request.form.get("note_remark", "").strip(),
            )
            if not note.customer_name:
                raise ValueError("顾客不能为空")

            db.session.add(note)
            db.session.flush()

            for line in lines:
                db.session.add(DeliveryNoteLine(delivery_note_id=note.id, **line))

            db.session.commit()
            flash("送货单已保存，并已纳入库存日报统计", "success")
            return redirect(
                url_for("main.delivery_notes", delivery_date=note.delivery_date.isoformat())
            )
        except Exception as exc:
            db.session.rollback()
            flash(str(exc), "danger")

    notes = (
        DeliveryNote.query.options(
            selectinload(DeliveryNote.lines).selectinload(DeliveryNoteLine.product)
        )
        .order_by(DeliveryNote.delivery_date.desc(), DeliveryNote.id.desc())
        .limit(20)
        .all()
    )
    return render_template(
        "delivery_notes.html",
        selected_date=selected_date.isoformat(),
        products=Product.query.filter_by(is_active=True).order_by(Product.name.asc()).all(),
        notes=notes,
    )


@bp.route("/delivery-notes/<int:note_id>/delete", methods=["POST"])
@admin_required
def delete_delivery_note(note_id: int):
    note = db.get_or_404(DeliveryNote, note_id)
    redirect_date = note.delivery_date.isoformat()
    db.session.delete(note)
    db.session.commit()
    flash("送货单已删除", "success")
    return redirect(url_for("main.delivery_notes", delivery_date=redirect_date))


@bp.route("/entries", methods=["GET", "POST"])
def entries():
    if (
        request.method == "POST"
        and not login_disabled()
        and current_user.role not in (ROLE_ADMIN, ROLE_OPERATOR)
    ):
        return role_required(ROLE_ADMIN, ROLE_OPERATOR)(lambda: None)()
    selected_date = parse_date(request.args.get("biz_date") or date.today().isoformat())
    if request.method == "POST":
        try:
            product_id = _parse_int(request.form["product_id"], "商品")
            _ensure_product_exists(product_id)
            movement = InventoryMovement(
                biz_date=parse_date(request.form["biz_date"]),
                product_id=product_id,
                movement_type=normalize_movement_type(request.form["movement_type"]),
                quantity=parse_non_negative_decimal(request.form["quantity"], "数量", QTY_PLACES),
                profit_per_unit_override=parse_optional_decimal(
                    request.form.get("profit_per_unit_override"),
                    "毛利润单价覆盖",
                    MONEY_PLACES,
                ),
                remark=request.form.get("remark", "").strip(),
            )
            db.session.add(movement)
            db.session.commit()
            flash("流水已记录", "success")
            return redirect(url_for("main.entries", biz_date=movement.biz_date.isoformat()))
        except Exception as exc:
            db.session.rollback()
            flash(str(exc), "danger")

    entry_rows = (
        InventoryMovement.query.filter_by(biz_date=selected_date)
        .order_by(InventoryMovement.created_at.desc(), InventoryMovement.id.desc())
        .all()
    )
    inbound_entries = [row for row in entry_rows if row.movement_type == "INBOUND"]
    outbound_entries = [row for row in entry_rows if row.movement_type == "OUTPUT"]
    return render_template(
        "entries.html",
        selected_date=selected_date.isoformat(),
        products=get_active_products(),
        inbound_entries=inbound_entries,
        outbound_entries=outbound_entries,
    )


@bp.route("/entries/<int:movement_id>/delete", methods=["POST"])
@admin_required
def delete_entry(movement_id: int):
    movement = db.get_or_404(InventoryMovement, movement_id)
    biz_date = movement.biz_date.isoformat()
    db.session.delete(movement)
    db.session.commit()
    flash("流水已删除", "success")
    return redirect(url_for("main.entries", biz_date=biz_date))


@bp.route("/entries/template")
@role_required(ROLE_ADMIN, ROLE_OPERATOR)
def entries_template():
    return _send_workbook(build_movement_template(), "流水导入模板.xlsx")


@bp.route("/entries/import", methods=["POST"])
@role_required(ROLE_ADMIN, ROLE_OPERATOR)
def entries_import():
    file_storage = request.files.get("file")
    if not file_storage or not file_storage.filename:
        flash("请选择 Excel 文件", "warning")
        return redirect(url_for("main.entries"))

    try:
        records = parse_movement_import(file_storage)
        for record in records:
            db.session.add(
                InventoryMovement(
                    biz_date=record["biz_date"],
                    product_id=record["product"].id,
                    movement_type=record["movement_type"],
                    quantity=record["quantity"],
                    profit_per_unit_override=record["profit_per_unit_override"],
                    remark=record["remark"],
                )
            )
        db.session.commit()
        flash(f"成功导入 {len(records)} 条流水", "success")
    except Exception as exc:
        db.session.rollback()
        flash(str(exc), "danger")

    return redirect(url_for("main.entries"))


@bp.route("/entries/export")
@role_required(ROLE_ADMIN, ROLE_OPERATOR)
def entries_export():
    biz_date_value = request.args.get("biz_date")
    query = InventoryMovement.query.order_by(
        InventoryMovement.biz_date.desc(), InventoryMovement.id.desc()
    )
    filename = "流水明细.xlsx"
    if biz_date_value:
        selected_date = parse_date(biz_date_value)
        query = query.filter(InventoryMovement.biz_date == selected_date)
        filename = f"流水明细_{selected_date.isoformat()}.xlsx"

    rows = []
    for movement in query.all():
        rows.append(
            {
                "日期": movement.biz_date.isoformat(),
                "商品名称": movement.product.name,
                "流水类型": movement.movement_type,
                "数量": movement.quantity,
                "毛利润单价覆盖": movement.profit_per_unit_override,
                "备注": movement.remark or "",
                "录入时间": movement.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            }
        )
    workbook = create_workbook_bytes({"movements": pd.DataFrame(rows)})
    return _send_workbook(workbook, filename)


@bp.route("/losses", methods=["GET", "POST"])
def losses():
    if (
        request.method == "POST"
        and not login_disabled()
        and current_user.role not in (ROLE_ADMIN, ROLE_OPERATOR)
    ):
        return role_required(ROLE_ADMIN, ROLE_OPERATOR)(lambda: None)()
    selected_date = parse_date(request.args.get("biz_date") or date.today().isoformat())
    if request.method == "POST":
        try:
            product_id_raw = request.form.get("product_id") or None
            product_id = _parse_int(product_id_raw, "商品") if product_id_raw else None
            if product_id:
                _ensure_product_exists(product_id)

            loss = LossRecord(
                biz_date=parse_date(request.form["biz_date"]),
                product_id=product_id,
                loss_quantity=parse_optional_decimal(
                    request.form.get("loss_quantity"), "坏货数量", QTY_PLACES
                ),
                compensation_amount=parse_non_negative_decimal(
                    request.form["compensation_amount"], "赔偿金额", MONEY_PLACES
                ),
                remark=request.form.get("remark", "").strip(),
            )
            db.session.add(loss)
            db.session.commit()
            flash("亏损记录已保存", "success")
            return redirect(url_for("main.losses", biz_date=loss.biz_date.isoformat()))
        except Exception as exc:
            db.session.rollback()
            flash(str(exc), "danger")

    loss_rows = (
        LossRecord.query.filter_by(biz_date=selected_date)
        .order_by(LossRecord.created_at.desc(), LossRecord.id.desc())
        .all()
    )
    return render_template(
        "losses.html",
        selected_date=selected_date.isoformat(),
        products=get_active_products(),
        losses=loss_rows,
    )


@bp.route("/losses/<int:loss_id>/delete", methods=["POST"])
@admin_required
def delete_loss(loss_id: int):
    loss = db.get_or_404(LossRecord, loss_id)
    biz_date = loss.biz_date.isoformat()
    db.session.delete(loss)
    db.session.commit()
    flash("亏损记录已删除", "success")
    return redirect(url_for("main.losses", biz_date=biz_date))


@bp.route("/reports/daily")
def daily_report():
    start_date = parse_date(request.args.get("start_date") or date.today().isoformat())
    end_date = parse_date(request.args.get("end_date") or start_date.isoformat())
    if end_date < start_date:
        flash("结束日期不能早于开始日期", "danger")
        return redirect(url_for("main.daily_report", start_date=start_date.isoformat()))

    product_id_raw = request.args.get("product_id")
    product_id = None if product_id_raw in ("", "None", None) else int(product_id_raw)
    category = request.args.get("category") or None

    report = build_report_data(
        start_date=start_date,
        end_date=end_date,
        product_id=product_id,
        category=category,
    )

    if request.args.get("format") == "xlsx":
        summary_df = pd.DataFrame(report["summary_rows"])
        detail_df = pd.DataFrame(report["detail_rows"])
        workbook = create_workbook_bytes(
            {
                "daily_summary": summary_df,
                "product_details": detail_df,
            }
        )
        return _send_workbook(
            workbook, f"日报_{start_date.isoformat()}_{end_date.isoformat()}.xlsx"
        )

    return render_template(
        "daily_report.html",
        start_date=start_date.isoformat(),
        end_date=end_date.isoformat(),
        selected_product_id=product_id,
        selected_category=category or "",
        products=Product.query.order_by(Product.name.asc()).all(),
        categories=get_categories(),
        summary_rows=report["summary_rows"],
        detail_rows=report["detail_rows"],
    )
