"""scripts/check.py 的每条规矩：好例子过、坏例子必须报错（会失败的检查得真会失败）。

每个测试在临时目录里搭一个迷你仓库，只放这条规矩关心的文件。
"""

from pathlib import Path

import pytest

from tests._repo_check import load_check

check = load_check()


def write(root: Path, rel: str, text: str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def rules_hit(problems) -> set[str]:
    return {p.rule.split()[0] for p in problems}


def test_every_problem_explains_itself(tmp_path):
    write(tmp_path, "frontend/src/blocks/x/X.tsx", 'export const X = () => <div style={{color: "#ff0000"}} />\n')
    (p,) = check.check_hardcoded_colors(tmp_path)
    assert p.what and p.why and p.fix and ":1" in p.where


# ---- 规矩 1 依赖方向 ----

@pytest.mark.parametrize(
    "rel,code,bad",
    [
        ("backend/app/core/x.py", "from app.figures import search\n", True),
        ("backend/app/core/x.py", "import app.intake.models\n", True),
        ("backend/app/figures/x.py", "from app.intake.models import Order\n", True),
        ("backend/app/figures/x.py", "from ..intake import models\n", True),
        ("backend/app/figures/x.py", "from app import intake\n", True),
        ("backend/app/figures/x.py", "import importlib\nimportlib.import_module('app.intake.models')\n", True),
        ("backend/app/intake/x.py", "from app.channels.web import send\n", True),
        ("backend/app/intake/x.py", "from app.main import create_app\n", True),
        ("backend/app/figures/x.py", "from app.core.db import Base\nfrom . import search\n", False),
        ("backend/app/channels/x.py", "from app.intake.models import Order\n", False),
        ("backend/app/delivery/x.py", "from app.intake import orders\n", False),
        ("backend/app/admin/x.py", "from app.figures import a\nfrom app.intake import b\n", False),
        ("backend/app/main.py", "from app.figures import router\n", False),
    ],
)
def test_python_dependency_direction(tmp_path, rel, code, bad):
    write(tmp_path, rel, code)
    assert bool(check.check_dependencies(tmp_path)) is bad


def test_frontend_fetch_only_in_api(tmp_path):
    write(tmp_path, "frontend/src/lib/api.ts", "export const x = () => fetch('/api/x')\n")
    assert check.check_dependencies(tmp_path) == []
    write(tmp_path, "frontend/src/pages/Home.tsx", "fetch('/api/x')\n")
    assert len(check.check_dependencies(tmp_path)) == 1


def test_block_component_cannot_import_api(tmp_path):
    write(tmp_path, "frontend/src/lib/api.ts", "export const apiGet = () => 1\n")
    write(tmp_path, "frontend/src/blocks/hero/load.ts", "import { apiGet } from '@/lib/api'\n")
    assert check.check_dependencies(tmp_path) == []
    write(tmp_path, "frontend/src/blocks/hero/Hero.tsx", "import { apiGet } from '../../lib/api'\n")
    assert len(check.check_dependencies(tmp_path)) == 1


def test_block_component_cannot_import_data_module(tmp_path):
    """lib/figures.ts 包了一层 api，区块组件 import 它也算绕过 load.ts。"""
    write(tmp_path, "frontend/src/lib/api.ts", "export const apiGet = () => 1\n")
    write(tmp_path, "frontend/src/lib/figures.ts", "import { apiGet } from './api'\nexport const f = apiGet\n")
    write(tmp_path, "frontend/src/lib/utils.ts", "export const cn = () => ''\n")
    write(tmp_path, "frontend/src/blocks/hero/Hero.tsx", "import { cn } from '@/lib/utils'\n")
    assert check.check_dependencies(tmp_path) == []
    write(tmp_path, "frontend/src/blocks/hero/Hero.tsx", "import { f } from '@/lib/figures'\n")
    assert len(check.check_dependencies(tmp_path)) == 1


# ---- 规矩 2 不许写死颜色 ----

@pytest.mark.parametrize(
    "code,bad",
    [
        ('<div className="text-[#ff0000]" />', True),
        ("color: #1F4E9C;", True),
        ("background: rgb(0 0 0 / 0.5);", True),
        ("color: oklch(0.5 0.1 200);", True),
        ('<div className="bg-black/50" />', True),
        ('<div className="text-gray-500" />', True),
        ('<div className="text-foreground bg-card border-border" />', False),
        ('<a href="#top">回到顶部</a>', False),
        ("const s = '&#123;'", False),
    ],
)
def test_hardcoded_colors(tmp_path, code, bad):
    write(tmp_path, "frontend/src/blocks/x/X.tsx", code + "\n")
    assert bool(check.check_hardcoded_colors(tmp_path)) is bad


def test_tokens_file_may_hold_colors(tmp_path):
    write(tmp_path, "frontend/src/styles/tokens.css", ":root { --primary: #1F4E9C; }\n")
    assert check.check_hardcoded_colors(tmp_path) == []


# ---- 规矩 3 不许 emoji ----

@pytest.mark.parametrize("text,bad", [("找到了 \U0001F389", True), ("完成 ✓", True), ("⭐ 收藏", True), ("A → B，正常中文。", False)])
def test_emoji(tmp_path, text, bad):
    write(tmp_path, "frontend/src/pages/P.tsx", f"<p>{text}</p>\n")
    assert bool(check.check_emoji(tmp_path)) is bad


# ---- 规矩 4 不许有密钥 ----

@pytest.mark.parametrize(
    "text,bad",
    [
        ("KEY=" + "sk-" + "a1B2c3D4e5F6g7H8i9J0k1L2", True),
        ("token " + "oc_" + "sk_" + "abcdef123456", True),
        ("url?corp" + "secret=" + "AbCdEf123456", True),
        ("-----BEGIN RSA " + "PRIVATE KEY-----", True),
        ("文档里提到 `sk-` 和 `corpsecret=` 这类前缀不算", False),
        ("LLM_API_KEY=\n", False),
    ],
)
def test_secrets(tmp_path, text, bad):
    write(tmp_path, "docs/x.md", text + "\n")
    assert bool(check.check_secrets(tmp_path)) is bad


def test_dotenv_skipped_in_fallback_walk(tmp_path):
    """不是 git 仓库时退回扫目录：.env 被跳过不读（不读密钥），但 .env.example 照扫。"""
    write(tmp_path, ".env", "LLM_API_KEY=" + "sk-" + "x" * 30 + "\n")
    write(tmp_path, ".env.example", "LLM_API_KEY=\n")
    assert check.check_secrets(tmp_path) == []


# ---- 规矩 5 提示词字数 ----

def test_prompt_length(tmp_path):
    assert check.check_prompt_length(tmp_path) == []  # 没有提示词文件也要能过
    write(tmp_path, "backend/app/intake/prompts/规矩.md", "字" * 2000)
    write(tmp_path, "backend/app/intake/prompts/语气.md", "字 " * 900)  # 空白不计
    assert check.check_prompt_length(tmp_path) == []
    write(tmp_path, "backend/app/intake/prompts/问答.md", "字" * 200)
    (p,) = check.check_prompt_length(tmp_path)
    assert "3100" in p.what


# ---- 规矩 6 原图路径不出站 ----

@pytest.mark.parametrize(
    "rel,code,bad",
    [
        ("backend/app/figures/schemas.py", "class Fig(BaseModel):\n    original_path: str\n", True),
        ("backend/app/figures/schemas.py", "class Fig(BaseModel):\n    原图: str\n", True),
        ("backend/app/figures/schemas.py", "class Fig(BaseModel):\n    p: str = Field(alias='file_path')\n", True),
        ("backend/app/figures/router.py", "def get():\n    return {'id': 1, 'file_path': 'x'}\n", True),
        ("backend/app/delivery/routers/dl.py", "class Out(BaseModel):\n    local_path: str\n", True),
        ("backend/app/figures/schemas.py", "class Fig(BaseModel):\n    thumb_url: str\n    preview_url: str\n", False),
        ("backend/app/figures/engine.py", "class Rec:\n    file_path: str\n", False),  # 内部文件不扫
        ("backend/app/admin/figures_router.py", "def get():\n    return {'file_path': 'x'}\n", False),  # 后台不对外
    ],
)
def test_original_path_fields(tmp_path, rel, code, bad):
    write(tmp_path, rel, code)
    assert bool(check.check_original_path_fields(tmp_path)) is bad


# ---- 规矩 7 AGENTS.md 和 docs 头部 ----

GOOD_HEAD = "---\nlast_updated: 2026-11-15\nstatus: draft\n---\n\n# 标题\n"


def test_agents_and_docs(tmp_path):
    assert "7" in rules_hit(check.check_agents_and_docs(tmp_path))  # 没有 AGENTS.md
    write(tmp_path, "AGENTS.md", "# 地图\n" * 100)
    write(tmp_path, "docs/a.md", GOOD_HEAD)
    assert check.check_agents_and_docs(tmp_path) == []
    write(tmp_path, "AGENTS.md", "# 地图\n" * 101)
    assert len(check.check_agents_and_docs(tmp_path)) == 1


@pytest.mark.parametrize(
    "text",
    [
        "# 没有头部\n",
        "---\nstatus: draft\n---\n",
        "---\nlast_updated: 2026-11-15\n---\n",
        "---\nlast_updated: 11月15日\nstatus: draft\n---\n",
    ],
)
def test_docs_head_missing(tmp_path, text):
    write(tmp_path, "AGENTS.md", "# 地图\n")
    write(tmp_path, "docs/任务单/x.md", text)
    assert len(check.check_agents_and_docs(tmp_path)) == 1


# ---- 规矩 8 不许小戴 ----

@pytest.mark.parametrize(
    "rel,text,bad",
    [
        ("backend/app/intake/prompts/规矩.md", "价格问题说「这个我让小戴本人回你」", True),
        ("frontend/src/pages/chat/WebChat.tsx", "const t = '小戴会看每一单'\n", True),
        ("backend/app/delivery/router.py", "msg = '再改我让小戴看一下'\n", True),
        ("backend/app/intake/prompts/规矩.md", "解决不了的发负责人微信", False),
        ("backend/tests/test_x.py", "assert '小戴' not in reply\n", False),  # 测试里可以提（断言它不出现）
    ],
)
def test_no_old_handoff_name(tmp_path, rel, text, bad):
    write(tmp_path, rel, text)
    problems = check.check_no_old_handoff_name(tmp_path)
    assert bool(problems) is bad
    if bad:
        assert problems[0].rule.startswith("8") and ":1" in problems[0].where


# ---- 规矩 1 补：shop、platforms 从 intake 只许拿适配器接口、发货文案、价目 ----

@pytest.mark.parametrize(
    "rel,code,bad",
    [
        ("backend/app/platforms/xy.py", "from app.intake.adapters import PaidIn\nfrom app.intake import pricing\n", False),
        ("backend/app/shop/adapter.py", "from app.intake.platform_texts import delivery_text\n", False),
        ("backend/app/platforms/xy.py", "from app.intake.orders import receive_paid\n", True),
        ("backend/app/shop/x.py", "from app.intake.models import Order\n", True),
        ("backend/app/admin/x.py", "from app.platforms import redline\nfrom app.shop import x\n", False),
    ],
)
def test_channels_only_use_intake_interfaces(tmp_path, rel, code, bad):
    write(tmp_path, rel, code)
    assert bool(check.check_dependencies(tmp_path)) is bad


# ---- 规矩 9 状态只按流程走 ----

def _flow_files(root: Path, *, test_ok: bool = True):
    write(root, "backend/app/intake/flow.py", "def emit(): obj.stage = 'x'\n")
    write(root, "backend/tests/intake/test_flow.py",
          "def test_illegal_manual_push_rejected():\n    pass\n" if test_ok else "def test_other():\n    pass\n")


def test_stage_written_outside_engine(tmp_path):
    _flow_files(tmp_path)
    assert check.check_stage_only_by_flow(tmp_path) == []  # 引擎自己写可以
    write(tmp_path, "backend/app/intake/service.py", "if order.stage == 'x':\n    order.stage = 'making'\n")
    (p,) = check.check_stage_only_by_flow(tmp_path)
    assert p.rule.startswith("9") and ":2" in p.where and p.see


def test_flow_backward_edge_needs_loop_and_test_must_exist(tmp_path):
    _flow_files(tmp_path, test_ok=False)
    flow = {"stages": [{"key": "a"}, {"key": "b"}], "steps": [
        {"id": "a", "stage": "a", "edges": [{"on": "go", "to": "b"}]},
        {"id": "b", "stage": "b", "edges": [{"on": "back", "to": "a"}]}]}
    import json

    write(tmp_path, "backend/app/intake/flows/x.json", json.dumps(flow))
    whats = [p.what for p in check.check_stage_only_by_flow(tmp_path)]
    assert any("没标 loop" in w for w in whats) and any("test_illegal_manual_push_rejected" in w for w in whats)
    flow["steps"][1]["edges"][0]["loop"] = True
    write(tmp_path, "backend/app/intake/flows/x.json", json.dumps(flow))
    _flow_files(tmp_path)
    assert check.check_stage_only_by_flow(tmp_path) == []


# ---- 规矩 10 价格只在设置里 ----

@pytest.mark.parametrize(
    "rel,text,bad",
    [
        ("backend/app/intake/bot.py", 'x = "常规档 29.9 元"\n', True),
        ("backend/app/intake/prompts/规矩.md", "加急加 9.9 元\n", True),
        ("frontend/src/blocks/x/X.tsx", "const p = '24.9';\n", True),
        ("backend/app/intake/config_store.py", '"p1": "29.9"\n', False),  # 设置默认值里可以
        ("frontend/src/blocks/x/example.ts", "price: '29.9'\n", False),  # 区块示例数据
        ("backend/app/intake/watermark.py", "size = w * 0.019  # 1.9% 图宽\n", False),
        ("backend/app/intake/x.py", 'f"{a.price} 元"\n', False),
    ],
)
def test_price_numbers(tmp_path, rel, text, bad):
    write(tmp_path, rel, text)
    assert bool(check.check_price_numbers(tmp_path)) is bad


# ---- 规矩 11 平台文案不导流 ----

REDLINE_SRC = 'TIERS = {"all": ("微信", "vx", "二维码"), "platform": ("公众号",)}\nPATTERNS = {"手机号": r"1[3-9]\\d{9}"}\n'


def test_platform_texts_redline(tmp_path):
    write(tmp_path, "backend/app/intake/platform_texts.py", '"""文档里提到微信没关系"""\nT = "激活码：{code}"\n')
    assert [p.what for p in check.check_platform_texts(tmp_path)] == ["红线词表不见了（或读不出 TIERS）"]
    write(tmp_path, "backend/app/platforms/redline.py", REDLINE_SRC)
    assert check.check_platform_texts(tmp_path) == []
    write(tmp_path, "backend/app/intake/platform_texts.py", 'T = "激活码：{code}，有问题加 vx 13812345678"\n')
    whats = {p.what for p in check.check_platform_texts(tmp_path)}
    assert any("vx" in w for w in whats) and any("1[3-9]" in w for w in whats)
    write(tmp_path, "backend/app/platforms/xhs.py", 'MSG = "关注公众号领取"\n')
    assert any("xhs.py" in p.where for p in check.check_platform_texts(tmp_path))


# ---- 规矩 12 最终版关口 ----

def test_final_gate(tmp_path):
    write(tmp_path, "backend/app/intake/orders.py", "def release_final(db, order):\n    require_completed(order)\n")
    assert check.check_final_gate(tmp_path) == []
    write(tmp_path, "backend/app/intake/orders.py", "def release_final(db, order):\n    send(order)\n")
    assert [p.rule for p in check.check_final_gate(tmp_path)] == ["12 最终版关口"]
    write(tmp_path, "backend/app/intake/orders.py", "def release_final(db, order):\n    require_completed(order)\n")
    write(tmp_path, "backend/app/delivery/router.py", 'q = select(FileRecord).where(FileRecord.role == "deliverable")\n')
    (p,) = check.check_final_gate(tmp_path)
    assert "deliverables_for_customer" in p.fix


# ---- 规矩 13 节点说明卡、14 节点不互相 import ----

FULL_CARD = """from app.core.nodes import NodeCard, NodeExit, register
CARD = NodeCard(id="x.y", name="名字", description="一句话说清做什么", category="订单", tech=["Python"],
    input_model=In, output_model=Out, exits=[NodeExit(key="ok", label="好", kind="ok")], config=["无"], emits=["无"],
    listens=["无"], replaceable=["暂无"], failure="随便重试", owner="A", status="要新做")
register(CARD)
"""


def test_node_cards(tmp_path):
    write(tmp_path, "backend/app/intake/nodes/x_y.py", FULL_CARD)
    write(tmp_path, "backend/app/intake/nodes/__init__.py", "import importlib\n")
    assert check.check_node_cards(tmp_path) == []
    write(tmp_path, "backend/app/intake/nodes/x_y.py", FULL_CARD.replace('tech=["Python"],', "tech=[],").replace(
        'failure="随便重试", ', ""))
    (p,) = check.check_node_cards(tmp_path)
    assert "failure" in p.what and "tech" in p.what
    write(tmp_path, "backend/app/intake/nodes/x_y.py", FULL_CARD.replace("register(CARD)\n", ""))
    assert "register" in check.check_node_cards(tmp_path)[0].what


def test_nodes_do_not_import_each_other(tmp_path):
    write(tmp_path, "backend/app/intake/nodes/a.py", "from app.core.nodes import run_node\nfrom app.intake import orders\n")
    assert check.check_nodes_no_cross_import(tmp_path) == []
    write(tmp_path, "backend/app/intake/nodes/b.py", "from app.intake.nodes.a import handler\n")
    write(tmp_path, "backend/app/delivery/nodes/c.py", "from . import d\n")
    assert len(check.check_nodes_no_cross_import(tmp_path)) == 2


def test_problem_render_has_see_line():
    p = check.Problem("9 x", "a.py:1", "错", "因为", "这么改", "看契约")
    assert p.render().endswith("看哪份：看契约")


INVOICE_TESTS = "\n".join(f"def {n}():\n    pass\n" for n in (
    "test_download_requires_order_owner", "test_tax_id_format_rules", "test_amount_cannot_exceed_paid",
    "test_refunded_order_cannot_issue", "test_gate_waits_until_completed", "test_one_active_request_per_order",
    "test_invoice_file_type_and_size"))


def test_invoice_rules(tmp_path):
    """规矩 16：invoices 从 intake 只读、走引擎；下载接口要校验归属；K1–K7 的测试要在。"""
    write(tmp_path, "backend/app/invoices/service.py",
          "from app.intake import flow\nfrom app.intake.models import Order\nfrom app.intake.service import create_outbox\n")
    write(tmp_path, "backend/app/invoices/router.py",
          '@router.get("/order/{t}/files/{f}")\ndef f():\n    require_owner(invoice_order_id=1, order_id=1, issued=True)\n')
    write(tmp_path, "backend/tests/invoices/test_x.py", INVOICE_TESTS)
    assert check.check_invoice_rules(tmp_path) == []
    # 从 intake 多拿了（订单中枢的写函数）
    write(tmp_path, "backend/app/invoices/bad.py", "from app.intake import orders\nfrom app.intake.service import update_order\n")
    probs = check.check_invoice_rules(tmp_path)
    assert len(probs) == 2 and all(p.rule.startswith("16") and p.see for p in probs)
    (tmp_path / "backend/app/invoices/bad.py").unlink()
    # 下载接口不校验归属
    write(tmp_path, "backend/app/invoices/router.py", '@router.get("/order/{t}/files/{f}")\ndef f():\n    return 1\n')
    (p,) = check.check_invoice_rules(tmp_path)
    assert "require_owner" in p.what
    # 测试被删了
    write(tmp_path, "backend/app/invoices/router.py", "")
    write(tmp_path, "backend/tests/invoices/test_x.py", INVOICE_TESTS.replace("def test_tax_id_format_rules", "def renamed"))
    (p,) = check.check_invoice_rules(tmp_path)
    assert "test_tax_id_format_rules" in p.what


# ---- 规矩 S1–S3 底座可扩展 ----

@pytest.mark.parametrize(
    "rel,code,bad",
    [
        ("backend/app/intake/x.py", 'db.execute(text("INSERT OR IGNORE INTO t VALUES (1)"))\n', True),
        ("backend/app/shop/x.py", 'db.execute(text("SELECT * FROM t FOR UPDATE SKIP LOCKED"))\n', True),
        ("backend/app/shop/x.py", 'conn.execute(text("PRAGMA journal_mode"))\n', True),
        ("backend/app/intake/x.py", "from sqlalchemy.dialects.postgresql import insert\n", True),
        ("backend/app/intake/x.py", "if db.bind.dialect.name == 'sqlite':\n    pass\n", True),
        ("backend/app/intake/x.py", "Index('ix', 'a', postgresql_where=x)\n", True),
        ("backend/app/intake/x.py", "q = select(func.julianday(Order.created_at))\n", True),
        ("backend/app/intake/x.py", '"""文档里说 PRAGMA、ON CONFLICT 没关系"""\nx = select(Order).with_for_update()\n', False),
        ("backend/app/core/db.py", 'cur.execute("PRAGMA busy_timeout=1")\n', False),
        ("backend/app/core/dbbackup.py", "import sqlite3\nc.execute('PRAGMA integrity_check')\n", False),
    ],
)
def test_dialect_sql_only_in_core_db(tmp_path, rel, code, bad):
    write(tmp_path, rel, code)
    probs = check.check_dialect_sql(tmp_path)
    assert bool(probs) == bad
    if bad:
        assert probs[0].see and "core/db" in probs[0].fix


def test_background_tasks_must_use_scheduler(tmp_path):
    write(tmp_path, "backend/app/intake/router.py", "async def lifespan(app):\n    t = asyncio.create_task(loop(app))\n")
    write(tmp_path, "backend/app/core/tasks.py", "")
    probs = check.check_background_tasks(tmp_path)
    assert any("create_task" in p.what for p in probs)
    assert any("test_many_workers_each_task_once" in p.what for p in probs)  # 并发测试不在也报
    write(tmp_path, "backend/app/intake/router.py", "async def lifespan(app):\n    app.state.scheduler.every('x', 1, f)\n")
    write(tmp_path, "backend/tests/scale/test_x.py", "".join(f"def {n}(): pass\n" for n in check.SCALE_REQUIRED_TESTS))
    assert check.check_background_tasks(tmp_path) == []


@pytest.mark.parametrize(
    "code,bad",
    [
        ("from collections import deque\nhits = {}\n", True),
        ("from limits.storage import MemoryStorage\n_STORE = MemoryStorage()\n", True),
        ("def f(request):\n    request.app.state.hits = {}\n", True),
        ("_FAILS: dict[str, list[float]] = {}\n", True),
        ("_seen = defaultdict(list)\n", True),
        ("NAMES = {'xhs': '小红书'}\n", False),
        ("def f():\n    hits = {}\n    return hits\n", False),
    ],
)
def test_stateless_web(tmp_path, code, bad):
    write(tmp_path, "backend/app/shop/x.py", code)
    assert bool(check.check_stateless_web(tmp_path)) == bad


def test_get_that_writes_must_use_write_session(tmp_path):
    bad = ("@router.get('/x')\ndef x(db: Session = Depends(get_db)):\n    record(db)\n    db.commit()\n")
    write(tmp_path, "backend/app/shop/router.py", bad)
    (p,) = check.check_stateless_web(tmp_path)
    assert "get_write_db" in p.fix
    write(tmp_path, "backend/app/shop/router.py", bad.replace("get_db", "get_write_db"))
    assert check.check_stateless_web(tmp_path) == []


def test_site_links(tmp_path):
    """规矩 18：官网站内链接要有路由、锚点要在、页面清单每页有路由、外链 https、新窗口带 noopener、tel: 格式对。"""
    write(tmp_path, "frontend/src/lib/site-pages.ts",
          'export const SITE_PAGES = [\n  { path: "/", title: "首页", group: "服务" },\n  { path: "/privacy", title: "隐私政策", group: "协议" },\n];\n')
    write(tmp_path, "frontend/src/pages/site/routes.tsx", 'const r = [{ path: "/" }, { path: "/privacy" }, { path: "/d/:token" }];\n')
    write(tmp_path, "frontend/src/pages/site/legal/privacy.md", "## AI 处理和出境 {#ai}\n\n见[首页](/)。\n")
    write(tmp_path, "frontend/src/pages/site/HomePage.tsx",
          '<Link to="/privacy#ai">隐私</Link>\n<Link to="/d/abc">交付</Link>\n'
          '<a href="https://www.12315.cn/" target="_blank" rel="noopener noreferrer">12315</a>\n<a href="tel:15068998671">电话</a>\n')
    assert check.check_site_links(tmp_path) == []
    # 坏例子：没有路由的站内链接、不存在的锚点、http 外链、新窗口没 noopener、tel 写成中文
    write(tmp_path, "frontend/src/pages/site/Bad.tsx",
          '<Link to="/nope">x</Link>\n<Link to="/privacy#rights">y</Link>\n'
          '<a href="http://example.com" target="_blank">z</a>\n<a href="tel:打电话">t</a>\n')
    probs = check.check_site_links(tmp_path)
    whats = " | ".join(p.what for p in probs)
    assert all(p.rule.startswith("18") and p.see and p.fix for p in probs)
    assert "/nope" in whats and "#rights" in whats and "http://example.com" in whats and "noopener" in whats and "tel:" in whats
    # 清单里有、路由没挂
    (tmp_path / "frontend/src/pages/site/Bad.tsx").unlink()
    write(tmp_path, "frontend/src/lib/site-pages.ts",
          'export const SITE_PAGES = [\n  { path: "/", title: "首页", group: "服务" },\n  { path: "/help", title: "帮助中心", group: "服务" },\n];\n')
    (p,) = check.check_site_links(tmp_path)
    assert "帮助中心" in p.what and "没有路由" in p.what


def _ops_ok_tree(root: Path) -> None:
    for nid in check.OPS_REQUIRED_NODES:
        write(root, f"backend/app/ops/nodes/{nid.replace('.', '_')}.py", f'CARD = NodeCard(id="{nid}")\nregister(CARD)\n')
    write(root, "backend/app/ops/settings.py", "class OpsSettings:\n    OPS_BACKUP_COS_ENABLED: bool = False\n")
    write(root, "backend/app/ops/config.py", "class Retention:\n" + "".join(f"    {f}: int = 1\n" for f in check.OPS_RETENTION_FIELDS))
    write(root, "backend/app/ops/retention.py", "def purge(cfg):\n    return timedelta(days=cfg.retention.raw_days)\n")
    write(root, "backend/app/ops/report.json", '{"sections": [{"key": "problems"}, {"key": "site"}]}')
    write(root, "backend/app/ops/alerts.json", '{"rules": [{"id": "http_5xx", "link": "/admin/ops"}]}')
    write(root, "backend/app/ops/sender.py", 'def send(self):\n    log.warning("没发出去：%s", why)\n')
    write(root, "deploy/ops/日志样例.jsonl", '{"msg": "客人手机号 <手机号>", "phone": "***"}\n')
    write(root, "backend/tests/ops/test_x.py", "\n".join(f"def {n}():\n    pass\n" for n in check.OPS_REQUIRED_TESTS))


def test_ops_rules(tmp_path):
    """规矩 19：运维节点齐全；日志样例不含敏感字段；备份推送默认关；保留期在设置里；webhook 不进日志和事件；日报第一段；告警带链接；测试要在。"""
    _ops_ok_tree(tmp_path)
    assert check.check_ops_rules(tmp_path) == []
    cases = [
        ("backend/app/ops/nodes/ops_backup_run.py", "", "ops.backup_run"),
        ("deploy/ops/日志样例.jsonl", '{"msg": "电话 13812345678"}\n', "手机号"),
        ("deploy/ops/日志样例.jsonl", '{"msg": "码 PSY-ABCDEFGH9"}\n', "激活码"),
        ("backend/app/ops/settings.py", "class S:\n    OPS_BACKUP_COS_ENABLED: bool = True\n", "OPS_BACKUP_COS_ENABLED"),
        ("backend/app/ops/backup.py", 'import os\nkey = os.environ.get("COS_SECRET_KEY")\n', "COS_SECRET_KEY"),
        ("backend/app/ops/config.py", "class Retention:\n    raw_days: int = 1\n", "hourly_days"),
        ("backend/app/ops/retention.py", "def purge():\n    return timedelta(days=30)\n", "timedelta(days=30)"),
        ("backend/app/ops/sender.py", 'def send(self):\n    log.info("发到 %s", self.webhook_url)\n', "webhook_url"),
        ("backend/app/ops/alerts.py", 'record_event(db, "ops.sent", "", {"to": webhook})\n', "webhook"),
        ("backend/app/ops/report.json", '{"sections": [{"key": "site"}, {"key": "problems"}]}', "problems"),
        ("backend/app/ops/alerts.json", '{"rules": [{"id": "disk_usage", "link": "https://x"}]}', "disk_usage"),
        ("backend/tests/ops/test_x.py", "def renamed():\n    pass\n", "test_log_sample_has_no_sensitive_fields"),
    ]
    for i, (rel, text, needle) in enumerate(cases):
        root = tmp_path / f"case{i}"
        _ops_ok_tree(root)
        if text:
            write(root, rel, text)
        else:
            (root / rel).unlink()
        probs = check.check_ops_rules(root)
        assert probs and all(x.rule.startswith("19") and x.see for x in probs), rel
        assert any(needle in x.what for x in probs), (rel, [x.what for x in probs])
    # webhook 只是「配没配」的布尔名字不算
    root = tmp_path / "flag"
    _ops_ok_tree(root)
    write(root, "backend/app/ops/sender.py", 'def s():\n    log.info("配了吗 %s", webhook_configured)\n')
    assert check.check_ops_rules(root) == []


ENTRY_TESTS = "\n".join(f"def {n}():\n    pass\n" for n in check.ENTRY_REQUIRED_TESTS)
GOOD_CALLBACK = '''from app.channels.wecom import parse_xml
from app.channels.wecom_inbox import enqueue_callback


@router.post("/callback")
async def notify(request, rt=Depends(channels_dep)):
    plain = _crypto(rt).decrypt_message((await request.body()).decode("utf-8"), "s", "t", "n")
    enqueue_callback(rt, parse_xml(plain))
    return PlainTextResponse("success")
'''


def test_entry_rules(tmp_path):
    """规矩 20：微信客服回调只入队；不转会话状态；收发消息的入口节点要登记 EntrySpec；第九节的测试要在。"""
    write(tmp_path, "backend/app/channels/wecom_router.py", GOOD_CALLBACK)
    write(tmp_path, "backend/app/channels/nodes/entry_x.py",
          "CARD = NodeCard(input_model=OutboundMessage)\nregister(CARD)\nregister_entry(EntrySpec())\n")
    write(tmp_path, "backend/tests/channels/test_x.py", ENTRY_TESTS)
    assert check.check_entry_rules(tmp_path) == []
    # 回调里拉消息、碰订单
    write(tmp_path, "backend/app/channels/wecom_router.py",
          GOOD_CALLBACK.replace("enqueue_callback(rt, parse_xml(plain))", "await sync_messages(rt, 'k')")
          + "from app.intake import service\n")
    probs = check.check_entry_rules(tmp_path)
    assert {p.what.split("（")[0][:12] for p in probs} and len(probs) == 2 and all(p.rule.startswith("20") for p in probs)
    write(tmp_path, "backend/app/channels/wecom_router.py", GOOD_CALLBACK)
    # 把会话转人工
    write(tmp_path, "backend/app/admin/x_router.py", "await ch.wecom.service_state_trans(kfid, user, 3, 'edison')\n")
    (p,) = check.check_entry_rules(tmp_path)
    assert "service_state_trans" in p.what
    (tmp_path / "backend/app/admin/x_router.py").unlink()
    # 入口节点没登记 EntrySpec
    write(tmp_path, "backend/app/channels/nodes/entry_x.py", "CARD = NodeCard(input_model=OutboundMessage)\nregister(CARD)\n")
    (p,) = check.check_entry_rules(tmp_path)
    assert "EntrySpec" in p.what
    write(tmp_path, "backend/app/channels/nodes/entry_x.py", "")
    # 测试被删了
    write(tmp_path, "backend/tests/channels/test_x.py", ENTRY_TESTS.replace("def test_merge_rules", "def renamed"))
    (p,) = check.check_entry_rules(tmp_path)
    assert "test_merge_rules" in p.what


# ---- 规矩 21 需求引导 ----

BRIEF_TESTS = "\n".join(f"def {n}():\n    pass\n" for n in (
    "test_no_making_without_brief_confirmed", "test_proxy_confirm_needs_reason_and_is_marked",
    "test_card_built_by_code_template_without_model", "test_options_and_defaults_come_from_settings",
    "test_reminds_once_after_two_hours_never_auto_starts"))
BRIEF_DEFAULTS = ('{"questions": [{"key": "occasion", "title": "这次是什么场合", "options": [{"key": "group", "label": "组会读文献"}]}],'
                  ' "style": {"samples": [{"key": "n01", "title": "图解为主"}], "none_label": "都不像"},'
                  ' "texts": {"confirm_label": "对，开工"}}')


def _flow(edges_to_making_from: str) -> str:
    import json

    steps = [
        {"id": "collecting", "stage": "collecting", "node": "intake.collect", "edges": [
            {"on": "changed", "to": "brief"}, {"on": "start_now", "to": edges_to_making_from}]},
        {"id": "brief", "stage": "collecting", "node": "gate.brief_confirmed", "enter": "gate.brief_confirmed",
         "edges": [{"on": "exit:confirmed", "to": "gate"}, {"on": "exit:wait", "to": "collecting"}]},
        {"id": "gate", "stage": "collecting", "node": "gate.ready", "enter": "gate.ready", "edges": [{"on": "exit:start", "to": "making"}]},
        {"id": "making", "stage": "making", "node": "factory.handoff", "edges": []},
    ]
    return json.dumps({"key": "paid_custom", "stages": [{"key": "collecting"}, {"key": "making"}], "start": "collecting", "steps": steps})


def test_brief_rules(tmp_path):
    """规矩 21：制作中之前必须过需求卡闸口；需求卡前端不写死选项文字；确认卡链路不调模型；测试要在。"""
    write(tmp_path, "backend/app/intake/brief_defaults.json", BRIEF_DEFAULTS)
    write(tmp_path, "backend/app/intake/flows/paid_custom.json", _flow("brief"))
    write(tmp_path, "backend/app/intake/brief.py", "from app.intake import config_store\n")
    write(tmp_path, "frontend/src/blocks/brief-card/BriefCard.tsx",
          "/** 「对，开工」之前不开工（注释里提到没关系） */\nexport const B = ({ t }) => <b>{t.confirm_label}</b>;\n")
    write(tmp_path, "frontend/src/blocks/brief-card/example.ts", 'export default { label: "组会读文献" };\n')
    write(tmp_path, "backend/tests/intake/test_brief.py", BRIEF_TESTS)
    assert check.check_brief_rules(tmp_path) == []
    # 「现在开工」直接进制作中，绕过了闸口
    write(tmp_path, "backend/app/intake/flows/paid_custom.json", _flow("making"))
    (p,) = check.check_brief_rules(tmp_path)
    assert p.rule.startswith("21") and "不经过需求卡闸口" in p.what and p.see.endswith("09_需求引导_方案.md")
    write(tmp_path, "backend/app/intake/flows/paid_custom.json", _flow("brief"))
    # 前端写死选项文字（跨行的 JSX 也算）
    write(tmp_path, "frontend/src/blocks/brief-card/BriefCard.tsx", "export const B = () => (\n  <b>\n    组会读文献\n  </b>\n);\n")
    (p,) = check.check_brief_rules(tmp_path)
    assert "组会读文献" in p.what and p.where.endswith(":3")
    write(tmp_path, "frontend/src/blocks/brief-card/BriefCard.tsx", "export const B = () => null;\n")
    # 确认卡链路调模型、排助手
    write(tmp_path, "backend/app/intake/brief.py", "from pydantic_ai import Agent\nrun_node('assistant.sales', c, {})\n")
    probs = check.check_brief_rules(tmp_path)
    assert len(probs) == 2 and {"import 了 pydantic_ai" in probs[0].what, "assistant.sales" in probs[1].what} == {True}
    write(tmp_path, "backend/app/intake/brief.py", "")
    # 测试被删了
    write(tmp_path, "backend/tests/intake/test_brief.py", BRIEF_TESTS.replace("def test_options_and_defaults_come_from_settings", "def x"))
    (p,) = check.check_brief_rules(tmp_path)
    assert "test_options_and_defaults_come_from_settings" in p.what


# ---- 规矩 22 手机微信支付 ----

WXPAY_TESTS = "".join(f"def {n}():\n    pass\n" for n in (
    "test_jsapi_hidden_without_appsecret", "test_jsapi_flow_oauth_prepay_and_paid_only_by_notify", "test_oauth_state_must_match",
    "test_h5_flow_url_fresh_and_redirect", "test_unfinished_wechat_checkout_expires_without_gateway_calls"))


def test_mobile_pay_rules(tmp_path):
    write(tmp_path, "backend/app/shop/service.py",
          "def _apply_paid(row):\n    row.status = 'paid'\n\ndef _expire(row):\n    row.status, row.closed_at = 'closed', 1\n")
    write(tmp_path, "backend/app/shop/router.py", "def poll(row):\n    return row\n")
    write(tmp_path, "backend/app/core/headers.py", 'TOKEN_PAGE_PREFIXES = ("/d", "/chat", "/c", "/me")\n')
    write(tmp_path, "frontend/src/lib/wxpay.ts", "export const pay = (p) => WeixinJSBridge.invoke('getBrandWCPayRequest', p, () => 0);\n")
    write(tmp_path, "backend/tests/shop/test_mobile_wechat.py", WXPAY_TESTS)
    assert check.check_mobile_pay_rules(tmp_path) == []
    # 别的函数把单子改成已付（比如前端说付了就改）
    write(tmp_path, "backend/app/shop/service.py",
          "def _apply_paid(row):\n    row.status = 'paid'\n\ndef jsapi_ok(row):\n    row.status, row.code = 'paid', 'x'\n")
    (p,) = check.check_mobile_pay_rules(tmp_path)
    assert p.rule.startswith("22") and "jsapi_ok" in p.what and p.where.endswith(":5") and p.see.endswith("11_手机微信支付_设计.md 第十二节")
    write(tmp_path, "backend/app/shop/service.py", "def _apply_paid(row):\n    row.status = 'paid'\n")
    # 路由里写状态
    write(tmp_path, "backend/app/shop/router.py", "def poll(row):\n    row.status = 'closed'\n")
    (p,) = check.check_mobile_pay_rules(tmp_path)
    assert "router" in p.where
    write(tmp_path, "backend/app/shop/router.py", "def poll(row):\n    return row\n")
    # 调起支付的文件里把结果发给后端；后端收 err_msg
    write(tmp_path, "frontend/src/lib/wxpay.ts", "import { apiPost } from './api';\n"
          "WeixinJSBridge.invoke('getBrandWCPayRequest', p, (r) => apiPost('/shop/paid', r));\n")
    write(tmp_path, "backend/app/shop/models_io.py", "class Paid:\n    err_msg: str = ''\n")
    probs = check.check_mobile_pay_rules(tmp_path)
    assert len(probs) == 2 and "发了请求" in probs[0].what and "err_msg" in probs[1].what
    write(tmp_path, "frontend/src/lib/wxpay.ts", "export const pay = () => WeixinJSBridge.invoke('getBrandWCPayRequest', {}, () => 0);\n")
    write(tmp_path, "backend/app/shop/models_io.py", "")
    # openid / AppSecret 进日志、事件（格式串里提到这个词不算，带上值才算）
    write(tmp_path, "backend/app/shop/wxoauth.py", "import logging\nlog = logging.getLogger('x')\n"
          "def f(openid, s):\n    log.info('没拿到 openid')\n    log.info('got %s', openid)\n"
          "    record_event(db, 'shop.x', 'c:1', {'secret': s.mp_appsecret()})\n    print(f'{openid}')\n")
    probs = check.check_mobile_pay_rules(tmp_path)
    assert [p.where.rsplit(":", 1)[1] for p in probs] == ["5", "6", "7"] and "openid" in probs[0].what
    write(tmp_path, "backend/app/shop/wxoauth.py", "")
    # 付款页加了 no-referrer（H5 要 Referer）
    write(tmp_path, "backend/app/core/headers.py", 'TOKEN_PAGE_PREFIXES = ("/d", "/order", "/c")\n')
    (p,) = check.check_mobile_pay_rules(tmp_path)
    assert "Referrer" in p.what or "TOKEN_PAGE_PREFIXES" in p.what
    write(tmp_path, "backend/app/core/headers.py", 'TOKEN_PAGE_PREFIXES = ("/d",)\n')
    # 测试被删了
    write(tmp_path, "backend/tests/shop/test_mobile_wechat.py", WXPAY_TESTS.replace("def test_oauth_state_must_match", "def x"))
    (p,) = check.check_mobile_pay_rules(tmp_path)
    assert "test_oauth_state_must_match" in p.what


# ---- 规矩 23 登录与短信 ----

LOGIN_TESTS = "\n".join(f"def {n}():\n    pass\n" for n in (
    "test_sms_off_hides_everything", "test_sms_rate_limits", "test_sms_code_expiry_and_attempts",
    "test_wx_login_state_and_no_openid_logged", "test_qr_login_scan_flow", "test_mp_callback_signature",
    "test_claim_requires_login_and_binds_order_to_account"))
SMS_OK = ("def send_code(request, sender, phone, ip, lim):\n"
          "    lim.hit('sms.phone_60s', phone, limit=1, window=60)\n    lim.hit('sms.phone_daily', phone, limit=5, window=86400)\n"
          "    lim.hit('sms.ip_hourly', ip, limit=10, window=3600)\n    lim.hit('sms.daily_total', 'all', limit=300, window=86400)\n"
          "    return sender.send(phone, ['1', '5'])\n")


def test_login_sms_rules(tmp_path):
    write(tmp_path, "backend/app/channels/sms.py", SMS_OK)
    write(tmp_path, "backend/app/channels/models.py", "class SmsCode(Base):\n    code_mac: Mapped[str]\n")
    write(tmp_path, "backend/tests/channels/test_login.py", LOGIN_TESTS)
    write(tmp_path, "frontend/src/pages/me/Me.tsx", "export const A = ({ s }) => <div>{s.sms && <PhoneLogin onStart={f} />}</div>;\n")
    write(tmp_path, "backend/app/channels/login.py",
          "def f(db, phone, sms_code):\n    record_event(db, 'customer.x', '', {'phone': mask_phone(phone)})\n    log.info('手机号格式不对')\n")
    assert check.check_login_rules(tmp_path) == []
    # 手机号明文、验证码进了事件 / 日志
    write(tmp_path, "backend/app/channels/login.py",
          "def f(db, phone, sms_code):\n    record_event(db, 'customer.x', '', {'phone': phone})\n    log.info('code %s', sms_code)\n")
    probs = check.check_login_rules(tmp_path)
    assert [p.where.rsplit(":", 1)[1] for p in probs] == ["2", "3"] and all(p.rule.startswith("23") for p in probs)
    assert "phone" in probs[0].what and "sms_code" in probs[1].what
    write(tmp_path, "backend/app/channels/login.py", "")
    # 发之前少了一道限流；别处直接调网关
    write(tmp_path, "backend/app/channels/sms.py", SMS_OK.replace("    lim.hit('sms.ip_hourly', ip, limit=10, window=3600)\n", ""))
    (p,) = check.check_login_rules(tmp_path)
    assert "sms.ip_hourly" in p.what
    write(tmp_path, "backend/app/channels/sms.py", SMS_OK + "\ndef resend(sms_sender, phone):\n    return sms_sender.send(phone, ['1'])\n")
    (p,) = check.check_login_rules(tmp_path)
    assert "resend" in p.what
    write(tmp_path, "backend/app/channels/sms.py", SMS_OK)
    # 前端手机号组件没挂在短信开关后面
    write(tmp_path, "frontend/src/pages/me/Me.tsx", "export const A = () => <div><PhoneBind onStart={f} /></div>;\n")
    (p,) = check.check_login_rules(tmp_path)
    assert "PhoneBind" in p.what and p.where.endswith("Me.tsx:1")
    write(tmp_path, "frontend/src/pages/me/Me.tsx", "export const A = ({ s }) => (s.methods.includes(\"sms\") ? <PhoneLogin /> : null);\n")
    assert check.check_login_rules(tmp_path) == []
    # 验证码表存了明文
    write(tmp_path, "backend/app/channels/models.py", "class SmsCode(Base):\n    code: Mapped[str]\n    code_mac: Mapped[str]\n")
    (p,) = check.check_login_rules(tmp_path)
    assert "明文" in p.what
    write(tmp_path, "backend/app/channels/models.py", "class SmsCode(Base):\n    code_mac: Mapped[str]\n")
    # 测试被删了
    write(tmp_path, "backend/tests/channels/test_login.py", LOGIN_TESTS.replace("def test_sms_rate_limits", "def x"))
    (p,) = check.check_login_rules(tmp_path)
    assert "test_sms_rate_limits" in p.what


# ---- 规矩 24 数据隔离 ----

ISO_TESTS = "def test_idor_other_customer_gets_404():\n    pass\n\ndef test_token_routes_only_own_subresources():\n    pass\n"


def test_isolation_rules(tmp_path):
    write(tmp_path, "backend/tests/channels/test_isolation.py", ISO_TESTS)
    write(tmp_path, "backend/app/channels/x.py",
          "router = APIRouter(dependencies=[Depends(access.by_token)])\n\n@router.get('/a/{t}')\ndef a(t):\n    pass\n")
    write(tmp_path, "backend/app/shop/router.py",
          "router = APIRouter()\n\n@router.get('/catalog', dependencies=[Depends(access.public)])\ndef c():\n    pass\n\n"
          "@router.get('/mine')\ndef m(me=Depends(access.require_customer)):\n    pass\n\n"
          "@router.get('/o/{no}')\ndef o(order=Depends(owned_order)):\n    pass\n")
    write(tmp_path, "backend/app/admin/x_router.py", "router = APIRouter()\n\n@router.get('/x')\ndef x():\n    pass\n")
    assert check.check_isolation_rules(tmp_path) == []
    # 新加一条忘了声明
    write(tmp_path, "backend/app/delivery/router.py",
          "router = APIRouter()\n\n@router.get('/{token}/files/{fid}')\ndef f(token, fid, db=Depends(get_db)):\n    pass\n")
    (p,) = check.check_isolation_rules(tmp_path)
    assert p.rule.startswith("24") and "/{token}/files/{fid}" in p.what and p.where.endswith("router.py:3")
    write(tmp_path, "backend/app/delivery/router.py", "")
    # 越权测试被删了
    write(tmp_path, "backend/tests/channels/test_isolation.py", ISO_TESTS.replace("def test_idor_other_customer_gets_404", "def x"))
    (p,) = check.check_isolation_rules(tmp_path)
    assert "test_idor_other_customer_gets_404" in p.what
