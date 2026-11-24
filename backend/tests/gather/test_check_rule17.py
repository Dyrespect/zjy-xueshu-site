"""check.py 规矩 17（聚人）：每一条坏例子都要真报错，失败信息写三件（错在哪、怎么改、看哪份）。"""

from __future__ import annotations

from pathlib import Path

from tests._repo_check import load_check

check = load_check()
REPO = Path(__file__).resolve().parents[3]


def write(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def mini_repo(tmp: Path) -> Path:
    """最小的好仓库：gather 只 import 流程引擎、text_for_unlock 先看阶段、测试都在。"""
    write(tmp, "backend/app/gather/__init__.py", "")
    write(tmp, "backend/app/gather/settings.py", 'class S:\n    FUNNEL_SOURCES: list[str] = ["gzh", "ai"]\n')
    write(tmp, "backend/app/gather/service.py", "from app.intake import flow\nSTAGE_SENT = 'sent'\n\n"
          "def text_for_unlock(db, unlock, cfg, gs):\n    if unlock.stage != STAGE_SENT:\n        return '', ''\n    return 'x', '1'\n")
    tests = "\n".join(f"def {n}():\n    pass\n" for n in check.GATHER_REQUIRED_TESTS)
    write(tmp, "backend/tests/gather/test_x.py", tests)
    return tmp


def msgs(root: Path) -> list:
    return check.check_gather_rules(root)


def test_good_repo_passes(tmp_path):
    assert msgs(mini_repo(tmp_path)) == []


def test_real_repo_passes():
    assert msgs(REPO) == []


def test_catches_intake_import(tmp_path):
    root = mini_repo(tmp_path)
    write(root, "backend/app/gather/bad.py", "from app.intake.models import Order\n")
    (p,) = msgs(root)
    assert "app.intake.models" in p.what and p.fix and p.see


def test_catches_pan_link_in_code(tmp_path):
    root = mini_repo(tmp_path)
    write(root, "frontend/src/blocks/x/X.tsx", 'const u = "https://pan.baidu.com/s/abc";\n')
    (p,) = msgs(root)
    assert "pan.baidu.com" in p.what and "网盘链接" in p.fix


def test_catches_forward_wording_outside_dialog(tmp_path):
    root = mini_repo(tmp_path)
    write(root, "frontend/src/pages/figures/HomePage.tsx", 'const t = "转发到朋友圈就能拿全部图库";\n')
    write(root, "frontend/src/blocks/all-library-dialog/A.tsx", 'const t = "转发到朋友圈";\n')  # 弹层里可以
    (p,) = msgs(root)
    assert "HomePage.tsx" in p.where and "弹层" in p.fix


def test_catches_from_not_in_whitelist(tmp_path):
    root = mini_repo(tmp_path)
    write(root, "frontend/src/lib/x.ts", 'const a = "/?from=wechat"; const b = "/order?from=tuku_header"; const c = "/?from=gzh";\n')
    (p,) = msgs(root)
    assert "from=wechat" in p.what


def test_catches_path_field_in_public_model(tmp_path):
    root = mini_repo(tmp_path)
    write(root, "backend/app/gather/models_io.py", "class V:\n    share_code: str\n    file: str\n")
    (p,) = msgs(root)
    assert "file" in p.what


def test_catches_gate_removed(tmp_path):
    root = mini_repo(tmp_path)
    write(root, "backend/app/gather/service.py", "def text_for_unlock(db, unlock, cfg, gs):\n    return 'x', '1'\n")
    (p,) = msgs(root)
    assert "text_for_unlock" in p.what


def test_catches_missing_test(tmp_path):
    root = mini_repo(tmp_path)
    write(root, "backend/tests/gather/test_x.py", "def test_unverified_never_gets_pack_link():\n    pass\n")
    ps = msgs(root)
    assert len(ps) == len(check.GATHER_REQUIRED_TESTS) - 1 and all("没有测试" in p.what for p in ps)
