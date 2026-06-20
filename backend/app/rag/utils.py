import hashlib
import json
from typing import Any


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def normalize_query(query: str) -> str:
    return " ".join(query.strip().split())


def content_preview(content: str, limit: int = 180) -> str:
    text = normalize_query(content)
    if len(text) <= limit:
        return text
    return f"{text[:limit]}..."


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def json_loads(value: str) -> Any:
    return json.loads(value)
