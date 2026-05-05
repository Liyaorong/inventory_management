from __future__ import annotations

from io import BytesIO

import pandas as pd

from .models import Product
from .utils import (
    MONEY_PLACES,
    QTY_PLACES,
    normalize_movement_type,
    parse_bool,
    parse_date,
    parse_non_negative_decimal,
    parse_optional_decimal,
)


PRODUCT_TEMPLATE_COLUMNS = [
    "商品名称",
    "商品类别",
    "单位",
    "默认单件毛利润",
    "是否启用",
]

MOVEMENT_TEMPLATE_COLUMNS = [
    "日期",
    "商品名称",
    "流水类型",
    "数量",
    "毛利润单价覆盖",
    "备注",
]


def create_workbook_bytes(sheets: dict[str, pd.DataFrame]) -> BytesIO:
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        for sheet_name, dataframe in sheets.items():
            dataframe.to_excel(writer, index=False, sheet_name=sheet_name[:31] or "Sheet1")
    output.seek(0)
    return output


def build_product_template() -> BytesIO:
    dataframe = pd.DataFrame(columns=PRODUCT_TEMPLATE_COLUMNS)
    return create_workbook_bytes({"products_template": dataframe})


def build_movement_template() -> BytesIO:
    dataframe = pd.DataFrame(columns=MOVEMENT_TEMPLATE_COLUMNS)
    return create_workbook_bytes({"movements_template": dataframe})


def parse_product_import(file_storage):
    dataframe = pd.read_excel(file_storage)
    dataframe = dataframe.dropna(how="all")
    missing_columns = [col for col in PRODUCT_TEMPLATE_COLUMNS if col not in dataframe.columns]
    if missing_columns:
        raise ValueError(f"商品导入缺少列: {', '.join(missing_columns)}")

    if dataframe["商品名称"].duplicated().any():
        duplicates = dataframe.loc[dataframe["商品名称"].duplicated(), "商品名称"].astype(str)
        raise ValueError(f"导入文件存在重复商品: {', '.join(sorted(set(duplicates)))}")

    existing_names = {product.name for product in Product.query.all()}
    records = []
    for index, row in dataframe.iterrows():
        line_no = index + 2
        name = str(row["商品名称"]).strip()
        category = str(row["商品类别"]).strip()
        unit = str(row["单位"]).strip()
        if not name or name.lower() == "nan":
            raise ValueError(f"第 {line_no} 行商品名称不能为空")
        if name in existing_names:
            raise ValueError(f"第 {line_no} 行商品名称已存在: {name}")
        if not category or category.lower() == "nan":
            raise ValueError(f"第 {line_no} 行商品类别不能为空")
        if not unit or unit.lower() == "nan":
            raise ValueError(f"第 {line_no} 行单位不能为空")

        profit = parse_non_negative_decimal(
            row["默认单件毛利润"], f"第 {line_no} 行默认单件毛利润", MONEY_PLACES
        )
        is_active = True
        if "是否启用" in row and str(row["是否启用"]).strip().lower() != "nan":
            is_active = parse_bool(row["是否启用"])

        records.append(
            {
                "name": name,
                "category": category,
                "unit": unit,
                "default_profit_per_unit": profit,
                "is_active": is_active,
            }
        )
    return records


def parse_movement_import(file_storage):
    dataframe = pd.read_excel(file_storage)
    dataframe = dataframe.dropna(how="all")
    missing_columns = [col for col in MOVEMENT_TEMPLATE_COLUMNS if col not in dataframe.columns]
    if missing_columns:
        raise ValueError(f"流水导入缺少列: {', '.join(missing_columns)}")

    products = {product.name: product for product in Product.query.all()}
    if not products:
        raise ValueError("请先创建商品，再导入流水")

    records = []
    for index, row in dataframe.iterrows():
        line_no = index + 2
        product_name = str(row["商品名称"]).strip()
        if product_name not in products:
            raise ValueError(f"第 {line_no} 行商品不存在: {product_name}")

        records.append(
            {
                "biz_date": parse_date(row["日期"]),
                "product": products[product_name],
                "movement_type": normalize_movement_type(row["流水类型"]),
                "quantity": parse_non_negative_decimal(
                    row["数量"], f"第 {line_no} 行数量", QTY_PLACES
                ),
                "profit_per_unit_override": parse_optional_decimal(
                    row["毛利润单价覆盖"],
                    f"第 {line_no} 行毛利润单价覆盖",
                    MONEY_PLACES,
                ),
                "remark": "" if pd.isna(row["备注"]) else str(row["备注"]).strip(),
            }
        )
    return records
