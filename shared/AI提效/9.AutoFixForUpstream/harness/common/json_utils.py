"""JSON 读写与 schema 校验(仿 patch-merge-workflow 的 common 层)。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

try:
    import jsonschema
except ImportError:  # pragma: no cover - 环境缺依赖时降级为不校验
    jsonschema = None

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCHEMA_DIR = REPO_ROOT / "schemas"


def read_json(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def update_json(path: Path, **fields: Any) -> Any:
    data = read_json(path)
    data.update(fields)
    write_json(path, data)
    return data


def validate(data: Any, schema_name: str) -> list[str]:
    """按 schemas/<name>.schema.json 校验,返回错误列表(空 = 通过)。"""
    if jsonschema is None:  # pragma: no cover
        return []
    schema = json.loads((SCHEMA_DIR / f"{schema_name}.schema.json").read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    return [e.message for e in sorted(validator.iter_errors(data), key=lambda e: e.json_path)]
