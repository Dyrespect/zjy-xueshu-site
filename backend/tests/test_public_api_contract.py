"""对外接口的返回里不许出现原图路径（docs/架构与技术栈.md 第七节第 6 条，运行时这一半）。

check.py 静态扫 schemas.py / router.py；这里从 OpenAPI 文档扫所有非 /api/admin 接口的返回结构，
不管返回模型定义在哪个文件都能抓到。
"""

from app.main import create_app
from tests._repo_check import load_check

FORBIDDEN = load_check().FORBIDDEN_RESPONSE_FIELDS


def _walk(schema, components, seen, found, where):
    if isinstance(schema, dict):
        ref = schema.get("$ref")
        if ref:
            name = ref.rsplit("/", 1)[-1]
            if name not in seen:
                seen.add(name)
                _walk(components.get(name, {}), components, seen, found, f"{where} -> {name}")
            return
        for prop in schema.get("properties", {}):
            if prop in FORBIDDEN:
                found.append(f"{where}.{prop}")
        for v in schema.values():
            _walk(v, components, seen, found, where)
    elif isinstance(schema, list):
        for v in schema:
            _walk(v, components, seen, found, where)


def public_response_violations(app) -> list[str]:
    spec = app.openapi()
    components = spec.get("components", {}).get("schemas", {})
    found: list[str] = []
    for path, ops in spec.get("paths", {}).items():
        if path.startswith("/api/admin"):
            continue
        for method, op in ops.items():
            for code, resp in op.get("responses", {}).items():
                _walk(resp, components, set(), found, f"{method.upper()} {path} [{code}]")
    return found


def test_no_original_path_in_public_responses(settings, notifier):
    assert public_response_violations(create_app(settings, notifier=notifier)) == []


def test_contract_check_catches_violation(settings, notifier):
    from pydantic import BaseModel

    class Leaky(BaseModel):
        thumb_url: str
        original_path: str

    app = create_app(settings, notifier=notifier)

    @app.get("/api/figures/_leaky", response_model=Leaky)
    def leaky():  # pragma: no cover
        ...

    assert any("original_path" in v for v in public_response_violations(app))
