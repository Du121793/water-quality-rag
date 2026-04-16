import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any


def to_jsonable(value: Any):
    if isinstance(value, dict):
        return {key: to_jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [to_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [to_jsonable(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value



def row_to_jsonable(row: Any):
    if row is None:
        return None
    if isinstance(row, dict):
        return to_jsonable(row)

    if hasattr(row, "items"):
        try:
            return to_jsonable({key: value for key, value in row.items()})
        except Exception:
            pass

    if hasattr(row, "keys"):
        try:
            return to_jsonable({key: row[key] for key in row.keys()})
        except Exception:
            pass

    try:
        return to_jsonable(dict(row))
    except Exception as err:
        raise ValueError(f"無法將資料列轉成可序列化 dict: {type(row).__name__}") from err

def dumps_json(value: Any) -> str:
    return json.dumps(to_jsonable(value), ensure_ascii=False)


