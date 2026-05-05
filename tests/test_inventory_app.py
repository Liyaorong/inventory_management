from __future__ import annotations

import unittest
from io import BytesIO

import pandas as pd

from inventory_app import create_app
from inventory_app.excel import parse_product_import
from inventory_app.extensions import db
from inventory_app.models import DeliveryNote, DeliveryNoteLine, InventoryMovement, LossRecord, Product, User
from inventory_app.services import build_report_data
from inventory_app.utils import parse_non_negative_integer


class InventoryAppTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app(
            {
                "TESTING": True,
                "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
                "LOGIN_DISABLED": True,
            }
        )
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()
        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        db.engine.dispose()
        self.app_context.pop()

    def _create_product(self, name="牛肉丸", category="丸类", unit="斤", profit="5.00"):
        product = Product(
            name=name,
            category=category,
            unit=unit,
            default_profit_per_unit=profit,
            is_active=True,
        )
        db.session.add(product)
        db.session.commit()
        return product

    def test_daily_report_rolls_inventory_and_profit(self):
        product = self._create_product()
        db.session.add_all(
            [
                InventoryMovement(
                    biz_date=pd.Timestamp("2026-04-20").date(),
                    product_id=product.id,
                    movement_type="INBOUND",
                    quantity="10.000",
                ),
                InventoryMovement(
                    biz_date=pd.Timestamp("2026-04-21").date(),
                    product_id=product.id,
                    movement_type="OUTPUT",
                    quantity="3.000",
                    profit_per_unit_override="4.50",
                ),
                LossRecord(
                    biz_date=pd.Timestamp("2026-04-21").date(),
                    product_id=product.id,
                    loss_quantity="1.000",
                    compensation_amount="2.00",
                ),
                LossRecord(
                    biz_date=pd.Timestamp("2026-04-21").date(),
                    product_id=None,
                    compensation_amount="5.00",
                ),
            ]
        )
        db.session.commit()

        report = build_report_data(
            start_date=pd.Timestamp("2026-04-21").date(),
            end_date=pd.Timestamp("2026-04-21").date(),
        )

        detail = report["detail_rows"][0]
        summary = report["summary_rows"][0]

        self.assertEqual(str(detail["opening_balance"]), "10.000")
        self.assertEqual(str(detail["closing_balance"]), "6.000")
        self.assertEqual(str(summary["estimated_profit"]), "13.50")
        self.assertEqual(str(summary["total_compensation"]), "7.00")
        self.assertEqual(str(summary["actual_profit"]), "6.50")

    def test_delivery_note_lines_flow_into_daily_report(self):
        product = self._create_product(name="三星8GEMMC", unit="PCS", profit="2.50")
        note = DeliveryNote(
            customer_name="芯展",
            contact_person="梁总",
            delivery_date=pd.Timestamp("2026-04-22").date(),
            delivery_no="XZ20260422-01",
        )
        db.session.add(note)
        db.session.flush()
        db.session.add(
            DeliveryNoteLine(
                delivery_note_id=note.id,
                product_id=product.id,
                serial_no="4",
                batch_no="16903批",
                product_name_snapshot=product.name,
                unit_snapshot="PCS",
                good_qty="100.000",
                defective_qty="5.000",
                misc_qty="2.000",
                incoming_short_qty="1.000",
                incoming_over_qty="3.000",
                remark="结单",
            )
        )
        db.session.commit()

        report = build_report_data(
            start_date=pd.Timestamp("2026-04-22").date(),
            end_date=pd.Timestamp("2026-04-22").date(),
        )
        detail = report["detail_rows"][0]
        summary = report["summary_rows"][0]

        self.assertEqual(str(detail["inbound_qty"]), "3.000")
        self.assertEqual(str(detail["output_qty"]), "100.000")
        self.assertEqual(str(detail["defective_qty"]), "5.000")
        self.assertEqual(str(detail["misc_qty"]), "2.000")
        self.assertEqual(str(detail["incoming_short_qty"]), "1.000")
        self.assertEqual(str(detail["loss_qty"]), "8.000")
        self.assertEqual(str(detail["closing_balance"]), "-105.000")
        self.assertEqual(str(summary["estimated_profit"]), "250.00")
        self.assertEqual(str(summary["total_incoming_over_qty"]), "3.000")

    def test_profit_override_falls_back_to_default(self):
        product = self._create_product(profit="6.00")
        db.session.add_all(
            [
                InventoryMovement(
                    biz_date=pd.Timestamp("2026-04-22").date(),
                    product_id=product.id,
                    movement_type="INBOUND",
                    quantity="10.000",
                ),
                InventoryMovement(
                    biz_date=pd.Timestamp("2026-04-22").date(),
                    product_id=product.id,
                    movement_type="OUTPUT",
                    quantity="2.000",
                ),
                InventoryMovement(
                    biz_date=pd.Timestamp("2026-04-22").date(),
                    product_id=product.id,
                    movement_type="OUTPUT",
                    quantity="1.000",
                    profit_per_unit_override="8.00",
                ),
            ]
        )
        db.session.commit()

        report = build_report_data(
            start_date=pd.Timestamp("2026-04-22").date(),
            end_date=pd.Timestamp("2026-04-22").date(),
        )
        summary = report["summary_rows"][0]
        self.assertEqual(str(summary["estimated_profit"]), "20.00")

    def test_product_import_rejects_duplicate_names(self):
        dataframe = pd.DataFrame(
            [
                {
                    "商品名称": "鱼豆腐",
                    "商品类别": "豆制品",
                    "单位": "袋",
                    "默认单件毛利润": 3,
                    "是否启用": "是",
                },
                {
                    "商品名称": "鱼豆腐",
                    "商品类别": "豆制品",
                    "单位": "袋",
                    "默认单件毛利润": 4,
                    "是否启用": "是",
                },
            ]
        )
        file_obj = BytesIO()
        with pd.ExcelWriter(file_obj, engine="openpyxl") as writer:
            dataframe.to_excel(writer, index=False)
        file_obj.seek(0)

        with self.assertRaises(ValueError):
            parse_product_import(file_obj)

    def test_report_export_route_returns_excel(self):
        product = self._create_product()
        db.session.add(
            InventoryMovement(
                biz_date=pd.Timestamp("2026-04-23").date(),
                product_id=product.id,
                movement_type="INBOUND",
                quantity="5.000",
            )
        )
        db.session.commit()

        response = self.client.get(
            "/reports/daily?start_date=2026-04-23&end_date=2026-04-23&format=xlsx"
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            response.content_type,
        )

    def test_delivery_notes_page_and_save_flow(self):
        product = self._create_product(name="三星8GEMMC", unit="PCS")
        response = self.client.post(
            "/delivery-notes",
            data={
                "customer_name": "芯展",
                "contact_person": "梁总",
                "delivery_date": "2026-04-22",
                "delivery_no": "XZ20260422-99",
                "note_remark": "送货完成",
                "serial_no[]": ["1"],
                "batch_no[]": ["16903批"],
                "product_id[]": [str(product.id)],
                "unit[]": ["PCS"],
                "good_qty[]": ["12"],
                "defective_qty[]": ["1"],
                "misc_qty[]": ["0"],
                "incoming_short_qty[]": ["0"],
                "incoming_over_qty[]": ["0"],
                "line_remark[]": ["样品"],
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(DeliveryNote.query.count(), 1)
        self.assertEqual(DeliveryNoteLine.query.count(), 1)

    def test_delivery_note_quantity_fields_reject_decimal_values(self):
        with self.assertRaises(ValueError):
            parse_non_negative_integer("1.5", "良品出货数")

    def test_product_edit_and_toggle_flow(self):
        product = self._create_product(name="虾滑")
        response = self.client.post(
            f"/products/{product.id}/edit",
            data={
                "name": "精品虾滑",
                "category": "海鲜",
                "unit": "盒",
                "default_profit_per_unit": "9.50",
                "is_active": "on",
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        updated = db.session.get(Product, product.id)
        self.assertEqual(updated.name, "精品虾滑")

        self.client.post(f"/products/{product.id}/toggle", follow_redirects=True)
        self.assertFalse(db.session.get(Product, product.id).is_active)

    def test_unused_product_can_be_deleted(self):
        product = self._create_product(name="测试删除商品")
        response = self.client.post(
            f"/products/{product.id}/delete",
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(db.session.get(Product, product.id))

    def test_referenced_product_cannot_be_deleted(self):
        product = self._create_product(name="已使用商品")
        db.session.add(
            InventoryMovement(
                biz_date=pd.Timestamp("2026-04-23").date(),
                product_id=product.id,
                movement_type="INBOUND",
                quantity="1.000",
            )
        )
        db.session.commit()

        response = self.client.post(
            f"/products/{product.id}/delete",
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(db.session.get(Product, product.id))


if __name__ == "__main__":
    unittest.main()



class AuthTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app(
            {
                "TESTING": True,
                "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
                "LOGIN_DISABLED": False,
            }
        )
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()
        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        db.engine.dispose()
        self.app_context.pop()

    def _user(self, username, role):
        user = User(username=username, role=role, is_active=True)
        user.set_password("secret")
        db.session.add(user)
        db.session.commit()
        return user

    def _login(self, username):
        return self.client.post(
            "/login",
            data={"username": username, "password": "secret"},
            follow_redirects=True,
        )

    def test_unauthenticated_user_is_redirected_to_login(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers["Location"])

    def test_viewer_cannot_post_write_routes(self):
        self._user("viewer", "viewer")
        self._login("viewer")
        response = self.client.post("/entries", data={}, follow_redirects=False)
        self.assertEqual(response.status_code, 403)

        response = self.client.get("/entries")
        self.assertEqual(response.status_code, 200)

    def test_operator_cannot_access_user_management(self):
        self._user("operator", "operator")
        self._login("operator")
        response = self.client.get("/users")
        self.assertEqual(response.status_code, 403)

    def test_admin_can_create_user(self):
        self._user("admin", "admin")
        self._login("admin")
        response = self.client.post(
            "/users",
            data={
                "username": "worker",
                "password": "secret",
                "role": "operator",
                "is_active": "on",
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(User.query.filter_by(username="worker").first())
