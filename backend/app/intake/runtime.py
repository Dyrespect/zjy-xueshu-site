"""接单在一个 app 里的运行时：业务上下文（Ctx）+ 机器人（BotRunner）+ 库。

第一次用到时按 app.state 建（底座的存储、通知、配置），挂在 app.state.intake。
测试里在进 lifespan 之前设 `app.state.intake_settings`（FACTORY_INBOX 指临时目录）和
`app.state.intake_model`（假模型），这里会用它们。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI, Request

from app.core.db import Database
from app.intake import clock
from app.intake.bot import BotRunner
from app.intake.llm import build_model
from app.intake.service import Ctx
from app.intake.settings import IntakeSettings

_UNSET = object()


@dataclass
class IntakeRuntime:
    ctx: Ctx
    runner: BotRunner
    database: Database


def get_runtime(app: FastAPI) -> IntakeRuntime:
    rt = getattr(app.state, "intake", None)
    if rt is None:
        isettings: IntakeSettings = getattr(app.state, "intake_settings", None) or IntakeSettings()
        clock.set_timezone(isettings.INTAKE_TIMEZONE)
        model: Any = getattr(app.state, "intake_model", _UNSET)
        if model is _UNSET:
            model = build_model(app.state.settings)
            classifier = model  # 判断意图用同一个入口（接待机器人第四节；一个小调用）
        else:  # 测试注入的假模型：判断默认只用规则，不打乱剧本；要测判断就另注入 intake_classifier_model
            classifier = getattr(app.state, "intake_classifier_model", None)
        ctx = Ctx(isettings, app.state.storage, app.state.notifier, app.state.settings.PUBLIC_BASE_URL)
        rt = IntakeRuntime(ctx, BotRunner(model, classifier=classifier), app.state.db)
        app.state.intake = rt
    return rt


def get_ctx(request: Request) -> Ctx:
    return get_runtime(request.app).ctx


def get_intake_runtime(request: Request) -> IntakeRuntime:
    return get_runtime(request.app)
