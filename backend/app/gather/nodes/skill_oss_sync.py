"""skill.oss_sync 开源仓库同步：只登记说明卡，服务器上不跑（Mac 上 scripts/skill_export.py）。"""

from __future__ import annotations

from app.core.nodes import NodeCard, NodeExit, register
from app.gather.models_io import SyncIn, SyncOut

CARD = NodeCard(
    id="skill.oss_sync",
    name="开源仓库同步",
    description="把内部的科研绘图 skill 导出成公开版（白名单 + 去掉客户名字、本机路径、PPT 工厂的东西、图片和数据），只放代码和文字；"
                "脱敏检查不过就不推。代码 MIT、文档 CC BY 4.0、标签随网盘包 CC BY-NC 4.0。第一次推送前给 Edison 看清单。",
    category="运营",
    tech=["Mac 上的脚本 scripts/skill_export.py（标准库）：白名单 scripts/skill_export/白名单.txt + 脱敏检查 + 替换（Edison → 负责人）",
          "公开版模板 scripts/skill_export/模板/（README、LICENSE、CONTRIBUTING、Issue 模板、在线查图.py）",
          "git + gh（还没接：这一版只导出到本机目录，不推送）"],
    input_model=SyncIn,
    output_model=SyncOut,
    exits=[
        NodeExit(key="exported", label="导出了（没推送）", kind="ok"),
        NodeExit(key="dry_run", label="只列清单", kind="ok"),
        NodeExit(key="blocked", label="脱敏检查没过，不导出", kind="fail"),
    ],
    config=["SKILL_EXPORT_DIR：本机公开仓库目录", "SKILL_EXPORT_DENYLIST：客户名词表（只在本机，不进任何仓库）"],
    emits=["无（脚本在 Mac 上跑，打印清单）"],
    listens=["无"],
    replaceable=["GitHub（默认）", "加 Gitee 镜像（国内访问快）"],
    failure="脱敏任何一条不过就不导出、退出码 1；外部 PR 不自动合进内部；推送这一步没做（要 Edison 定 GitHub 账号、看过清单）。",
    owner="L",
    status="要新做",
)
register(CARD, None)
