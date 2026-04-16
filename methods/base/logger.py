import json
import sys
import traceback
from datetime import datetime
from typing import Any


def get_formatted_date() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def safe_json(data: Any) -> str:
    try:
        return json.dumps(data, ensure_ascii=False, default=str)
    except Exception:
        return str(data)


def info(actor: str, action: str, ip: str = "") -> None:
    ip_part = f"[{ip}]" if ip else ""
    print(f"[INFO][{actor}]{ip_part}[{get_formatted_date()}] {action}")


def warn(actor: str, action: str, ip: str = "") -> None:
    ip_part = f"[{ip}]" if ip else ""
    print(f"[WARN][{actor}]{ip_part}[{get_formatted_date()}] {action}")


def error(actor: str, err: Exception, req: Any = None, extra: Any = None) -> None:
    ip = ""
    if req is not None and getattr(req, "client", None) and getattr(req.client, "host", None):
        ip = f"[{req.client.host}]"

    extra_part = f"[額外資料: {safe_json(extra)}]" if extra is not None else ""
    message = (
        f"\n[ERROR][{actor}]{ip}[{get_formatted_date()}]{extra_part}\n"
        f"錯誤簡述: \"{str(err)}\"\n"
        "詳細錯誤:\n"
    )
    print(message, file=sys.stderr)
    traceback.print_exception(type(err), err, err.__traceback__, file=sys.stderr)
