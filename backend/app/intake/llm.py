"""按配置建模型：任何兼容 OpenAI chat/completions + tools 的入口都行（今晚 GPT 中转，上线 DeepSeek）。

- 地址、模型名、密钥、额外请求头（LLM_EXTRA_HEADERS）、额外请求体（LLM_EXTRA_BODY）全从配置读，代码里不写死哪一家。
- 只用 chat/completions + tools：不用 responses 接口；关掉 strict 工具定义（DeepSeek 只在 beta 地址支持 strict），
  参数由 PydanticAI 在我们这边校验，不对就让模型重来。
- 没配密钥返回 None：机器人不跑，后台能看到「模型没配」。
"""

from __future__ import annotations

import os

from app.core.config import Settings

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")


def build_model(settings: Settings):
    key = settings.LLM_API_KEY.get_secret_value()
    if not (settings.LLM_BASE_URL and settings.LLM_MODEL and key):
        return None
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.profiles.openai import OpenAIModelProfile
    from pydantic_ai.providers.openai_compatible import OpenAICompatibleProvider
    from pydantic_ai.settings import ModelSettings

    provider = OpenAICompatibleProvider("llm", base_url=settings.LLM_BASE_URL, api_key=key)
    model_settings = ModelSettings(timeout=60)
    if settings.LLM_EXTRA_BODY:
        model_settings["extra_body"] = dict(settings.LLM_EXTRA_BODY)
    if settings.LLM_EXTRA_HEADERS:
        model_settings["extra_headers"] = dict(settings.LLM_EXTRA_HEADERS)
    return OpenAIChatModel(
        settings.LLM_MODEL,
        provider=provider,
        profile=OpenAIModelProfile(openai_supports_strict_tool_definition=False),
        settings=model_settings,
    )


def model_label(model) -> str:
    if model is None:
        return ""
    return str(getattr(model, "model_name", "") or type(model).__name__)[:64]
