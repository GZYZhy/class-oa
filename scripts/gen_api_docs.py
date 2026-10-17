#!/usr/bin/env python3
"""从 FastAPI 的 OpenAPI 描述生成 docs/api.md

用法（仓库根目录）：

    python scripts/gen_api_docs.py

接口改了之后重跑一遍即可，文档里的路径、参数、字段全都取自代码本身，不会手抄走样。

**不 import app.main**：它在 import 时就会启动生日/日程两个后台线程（还会连一次库），
而生成文档不该有任何副作用。api_router 是纯声明，单独挂到一个空 app 上就能出 schema。
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from fastapi import FastAPI  # noqa: E402

from app.api import api_router  # noqa: E402
from app.config import settings  # noqa: E402

OUT = ROOT / "docs" / "api.md"

# 全局都会出现的错误码，不在每个接口下面重复占篇幅
_COMMON_RESPONSES = {
    "422": "参数校验失败（字段缺失 / 类型不对 / 超出范围）",
}

# FastAPI 自带的英文描述换成中文；没有 schema 的接口只剩这一行，能看懂最重要
_RESPONSE_TEXT = {"Successful Response": "成功"}

_METHOD_ORDER = ["get", "post", "put", "patch", "delete"]


def _ref_name(schema: dict) -> str | None:
    ref = schema.get("$ref")
    return ref.rsplit("/", 1)[-1] if ref else None


def _num(value) -> str:
    """1.0 显示成 1：Pydantic 的约束有时是浮点，直接打进文档很别扭"""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _type_of(schema: dict | None) -> str:
    """把一个 JSON Schema 说成人话：string / integer / object / string[] / X，可空……"""
    if not schema:
        return "—"

    name = _ref_name(schema)
    if name:
        return name

    if "anyOf" in schema:
        parts = [s for s in schema["anyOf"]]
        nullable = any(s.get("type") == "null" for s in parts)
        rest = [s for s in parts if s.get("type") != "null"]
        text = " / ".join(_type_of(s) for s in rest) or "—"
        return f"{text}，可空" if nullable else text

    if "enum" in schema:
        values = " / ".join(str(v) for v in schema["enum"])
        return f"{schema.get('type', 'string')}（{values}）"

    kind = schema.get("type")
    if kind == "array":
        return f"{_type_of(schema.get('items'))}[]"
    if kind == "string" and schema.get("format") == "date-time":
        return "string（日期时间）"

    extras = []
    if "minimum" in schema:
        extras.append(f"≥{_num(schema['minimum'])}")
    if "maximum" in schema:
        extras.append(f"≤{_num(schema['maximum'])}")
    if "default" in schema and schema["default"] not in (None, "", []):
        extras.append(f"默认 {_num(schema['default'])}")
    suffix = f"（{'，'.join(extras)}）" if extras and kind in ("integer", "number") else ""
    return f"{kind or '—'}{suffix}"


def _properties(schema: dict) -> tuple[dict, set]:
    """取对象的字段表和必填集合；不是对象就返回空"""
    if not schema:
        return {}, set()
    if "$ref" in schema:
        return {}, set()  # 调用方已经解析过 $ref 了
    return schema.get("properties", {}), set(schema.get("required", []))


def _nested_lines(schema: dict, schemas: dict, indent: int = 1) -> list[str]:
    """把嵌套对象/数组里的字段摊成缩进列表（最多三层，够看清结构了）

    indent=1 就是两个空格 —— Markdown 里四个空格会被当成代码块，排版正好坏掉。
    """
    if indent > 3 or not schema:
        return []
    name = _ref_name(schema)
    if name:
        schema = schemas.get(name, {})

    kind = schema.get("type")
    if kind == "array":
        inner = schema.get("items") or {}
        inner = schemas.get(_ref_name(inner), {}) if _ref_name(inner) else inner
        return _nested_lines(inner, schemas, indent)

    props, required = _properties(schema)
    lines = []
    for field, prop in props.items():
        mark = "（必填）" if field in required else ""
        lines.append(f"{'  ' * indent}- `{field}`：{_type_of(prop)}{mark}")
        lines.extend(_nested_lines(prop, schemas, indent + 1))
    return lines


def _resolve(schema: dict | None, schemas: dict) -> dict:
    if not schema:
        return {}
    name = _ref_name(schema)
    return schemas.get(name, {}) if name else schema


def _params_table(params: list[dict], schemas: dict) -> list[str]:
    if not params:
        return []
    lines = [
        "**参数**",
        "",
        "| 名称 | 位置 | 必填 | 类型 | 说明 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for p in params:
        schema = p.get("schema", {})
        note = p.get("description", "")
        if schema.get("default") not in (None, "", []):
            note = (note + " " if note else "") + f"默认 `{_num(schema['default'])}`"
        lines.append(
            f"| `{p['name']}` | {p.get('in', '')} | {'是' if p.get('required') else '否'} "
            f"| {_type_of(schema)} | {note} |"
        )
    lines.append("")
    return lines


def _body_lines(body: dict, schemas: dict) -> list[str]:
    if not body:
        return []

    content = body.get("content", {})
    media, spec = next(iter(content.items()), (None, {}))
    if media is None:
        return []

    schema = _resolve(spec.get("schema"), schemas)
    props, required = _properties(schema)
    label = "文件上传" if media.startswith("multipart/") else "JSON"
    lines = [f"**请求体**（`{media}`，{label}）", ""]

    if not props:
        lines.append(f"类型：{_type_of(spec.get('schema'))}")
        lines.append("")
        return lines

    lines += ["| 字段 | 类型 | 必填 | 说明 |", "| --- | --- | --- | --- |"]
    for field, prop in props.items():
        note = prop.get("description", "")
        lines.append(
            f"| `{field}` | {_type_of(prop)} | {'是' if field in required else '否'} | {note} |"
        )
    lines.append("")

    # 嵌套结构单独摊开，表格里只要一行
    for field, prop in props.items():
        nested = _nested_lines(prop, schemas)
        if nested:
            lines.append(f"`{field}` 的字段：")
            lines.append("")
            lines += nested
            lines.append("")

    return lines


def _response_lines(responses: dict, schemas: dict) -> list[str]:
    lines = ["**响应**", ""]
    for code in sorted(responses):
        if code in _COMMON_RESPONSES:
            continue
        resp = responses[code]
        desc = _RESPONSE_TEXT.get(resp.get("description", ""), resp.get("description", ""))
        content = resp.get("content", {})
        spec = content.get("application/json", {}).get("schema")
        name = _ref_name(spec or {})

        if not spec:
            lines.append(f"- `{code}` — {desc}")
            continue

        resolved = _resolve(spec, schemas)
        props, _ = _properties(resolved)
        fields = "、".join(f"`{k}`" for k in props) if props else _type_of(spec)
        title = f"`{name}` " if name else ""
        lines.append(f"- `{code}` {title}— {desc}".rstrip())
        if fields:
            lines.append(f"  - 字段：{fields}")

    lines.append("")
    return lines


def _clean(text: str | None) -> str:
    """docstring 会带缩进和多余空行，压成一行给 Markdown 用"""
    if not text:
        return ""
    return " ".join(line.strip() for line in text.strip().splitlines() if line.strip())


def main() -> None:
    app = FastAPI(title=settings.app_name, version=settings.app_version)
    app.include_router(api_router)
    spec = app.openapi()
    schemas = spec.get("components", {}).get("schemas", {})

    # 按 tag 归组，tag 的出现顺序就是接口注册顺序（和代码里的模块顺序一致）
    groups: dict[str, list[tuple[str, str, dict]]] = {}
    for path, ops in spec["paths"].items():
        for method in _METHOD_ORDER:
            op = ops.get(method)
            if not op:
                continue
            for tag in op.get("tags") or ["其他"]:
                groups.setdefault(tag, []).append((path, method, op))

    total = sum(len(v) for v in groups.values()) + 1  # +1 是 main.py 里的 /api/health
    out: list[str] = [
        "# API 参考",
        "",
        f"> 版本 {settings.app_version}，共 {total} 个接口。",
        "> 本文由 `scripts/gen_api_docs.py` 从 FastAPI 的 OpenAPI 描述自动生成，"
        "接口变动后重新运行该脚本即可。",
        "",
        "## 通用约定",
        "",
        "- **基础地址**：下文路径都带 `/api` 前缀，直接拼在站点域名后，"
        "例如 `https://oa.example.com/api/inbox`。",
        "- **认证（浏览器）**：调用 `POST /api/auth/login` 登录，服务端会种下 HttpOnly "
        "会话 Cookie，之后的请求带上它即可；「保持登录」决定关闭浏览器后是否失效。",
        "- **认证（脚本）**：在「账号安全 → 访问令牌」里创建 `oa_pat_` 开头的令牌，"
        "请求头写 `Authorization: Bearer <令牌>`。**令牌一律按学生身份处理** —— "
        "班委 / 管理员专属接口用令牌调用会返回 403；创建、吊销令牌以及改密码等操作"
        "也只允许网页会话调用。令牌有调用频率限制，超限返回 429。",
        "- **失败格式**：出错时返回 `{\"detail\": \"原因\"}`，`detail` 是可直接展示给用户的中文。"
        "401 = 未登录或会话失效，403 = 权限不足，404 = 不存在或无权查看。",
        "- **参数校验失败**：一律 422，`detail` 里逐条列出是哪个字段、错在哪。",
        "- **分页**：需要分页的列表接口接受 `page`（从 1 开始）和 `page_size`，"
        "返回里带 `total` / `page` / `page_size`。",
        "- **时间**：响应里是北京时间，形如 `2026-10-17T08:30:00`；"
        "传日期参数用 `YYYY-MM-DD`，传日期时间用同样的 ISO 格式。",
        "- **权限**：每个接口需要什么身份，写在它下方的「说明」里；"
        "没写「需登录」的公开接口，未登录也能调用。",
        "",
        "## 目录",
        "",
    ]
    for tag, items in groups.items():
        out.append(f"- {tag}（{len(items)}）")
    out.append("- 健康检查（1）")
    out.append("")

    for tag, items in groups.items():
        out += [f"## {tag}", ""]
        for path, method, op in items:
            summary = op.get("summary") or op.get("operationId", "")
            out += [f"### {summary}", ""]
            out.append(f"`{method.upper()} {path}`")
            out.append("")
            desc = _clean(op.get("description"))
            if desc and desc != summary:
                out += [desc, ""]
            if op.get("deprecated"):
                out += ["> 已废弃。", ""]

            params = op.get("parameters") or []
            # 文件上传/请求体模型里的字段由 openapi 放进 requestBody，不会重复出现在 parameters
            out += _params_table(params, schemas)
            out += _body_lines(op.get("requestBody") or {}, schemas)
            out += _response_lines(op.get("responses") or {}, schemas)

    # 唯一一个不在 api_router 里的接口（定义在 main.py），单独补在最后
    out += [
        "## 健康检查",
        "",
        "### 健康检查",
        "",
        "`GET /api/health`",
        "",
        "不需要登录。部署脚本与容器健康检查用它确认后端活着，同时取出当前版本号。",
        "",
        "**响应**",
        "",
        "```json",
        '{"status": "ok", "app": "班级信息管理系统", "version": "%s"}' % settings.app_version,
        "```",
        "",
    ]

    OUT.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
    print(f"已生成 {OUT.relative_to(ROOT)}：{total} 个接口，{len(groups)} 个分组")


if __name__ == "__main__":
    main()
