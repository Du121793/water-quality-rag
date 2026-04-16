from methods.base.serializer import dumps_json


def format_sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {dumps_json(data)}\n\n"
