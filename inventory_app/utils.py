from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


QTY_PLACES = Decimal("0.001")
MONEY_PLACES = Decimal("0.01")


def to_decimal(value, default: str = "0") -> Decimal:
    if value in (None, ""):
        return Decimal(default)
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, ValueError, AttributeError) as exc:
        raise ValueError(f"无法解析数值: {value}") from exc


def parse_non_negative_decimal(value, field_name: str, places: Decimal) -> Decimal:
    decimal_value = to_decimal(value)
    if decimal_value < 0:
        raise ValueError(f"{field_name}不能为负数")
    return decimal_value.quantize(places, rounding=ROUND_HALF_UP)


def parse_non_negative_integer(value, field_name: str) -> int:
    decimal_value = to_decimal(value)
    if decimal_value < 0:
        raise ValueError(f"{field_name}不能为负数")
    if decimal_value != decimal_value.to_integral_value():
        raise ValueError(f"{field_name}必须为整数")
    return int(decimal_value)


def parse_optional_decimal(value, field_name: str, places: Decimal) -> Decimal | None:
    if value in (None, ""):
        return None
    return parse_non_negative_decimal(value, field_name, places)


def parse_date(value) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if not value:
        raise ValueError("日期不能为空")
    try:
        return datetime.strptime(str(value).strip(), "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError("日期格式必须为 YYYY-MM-DD") from exc


def normalize_movement_type(value: str) -> str:
    mapping = {
        "INBOUND": "INBOUND",
        "INPUT": "INBOUND",
        "输入": "INBOUND",
        "入库": "INBOUND",
        "接货": "INBOUND",
        "OUTPUT": "OUTPUT",
        "输出": "OUTPUT",
        "出库": "OUTPUT",
        "完成": "OUTPUT",
        "加工完成": "OUTPUT",
    }
    if value is None:
        raise ValueError("流水类型不能为空")
    normalized = mapping.get(str(value).strip().upper(), None)
    if normalized:
        return normalized
    normalized = mapping.get(str(value).strip(), None)
    if normalized:
        return normalized
    raise ValueError("流水类型仅支持 INBOUND/OUTPUT（或 输入/输出）")


def parse_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    return normalized in {"1", "true", "yes", "y", "是", "启用"}


def format_decimal(value, places: int = 2) -> str:
    decimal_value = to_decimal(value)
    if places == 0:
        quantized = decimal_value.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    elif places == 3:
        quantized = decimal_value.quantize(QTY_PLACES, rounding=ROUND_HALF_UP)
    else:
        quantized = decimal_value.quantize(MONEY_PLACES, rounding=ROUND_HALF_UP)
    text = f"{quantized:f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"
