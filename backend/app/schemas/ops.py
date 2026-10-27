"""运维页的请求/响应结构

运行时配置是一组键值，字段元数据由后端给（services/runtime_config.FIELDS），
前端只按分组渲染，不自己维护一份字段表 —— 加一项配置只需要改后端一处。
"""

from datetime import datetime

from pydantic import BaseModel, Field


class OpsConfigField(BaseModel):
    key: str
    label: str
    group: str
    kind: str
    """text / int / secret / choice"""
    help: str = ""
    choices: list[str] = Field(default_factory=list)
    min: int | None = None
    max: int | None = None
    value: str = ""
    """当前生效值；密文项为 ******** """
    source: str = "default"
    """database / environment / default —— 这个值现在是从哪来的"""
    updated_at: datetime | None = None
    updated_by_name: str = ""


class OpsEnvOnly(BaseModel):
    keys: str
    label: str
    reason: str


class OpsVersionInfo(BaseModel):
    app_version: str
    app_name: str


class OpsConfigResponse(BaseModel):
    groups: list[str]
    fields: list[OpsConfigField]
    env_only: list[OpsEnvOnly]
    version: OpsVersionInfo


class OpsConfigUpdate(BaseModel):
    values: dict[str, str | int | None] = Field(default_factory=dict)


class OpsConfigSaved(BaseModel):
    message: str
    changed: list[str]


class UpdateCheckResponse(BaseModel):
    current_version: str
    current_parsed: bool
    """当前版本能不能按语义化解析；False = 开发版，不做新旧判断"""
    latest_version: str = ""
    latest_tag: str = ""
    published_at: str = ""
    release_url: str = ""
    update_available: bool = False
    checked_at: str = ""
    cached: bool = False
    error: str = ""
    """unreachable = 查不到（静默，不弹错误）"""
