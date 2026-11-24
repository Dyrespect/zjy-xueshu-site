"""Mac 上跑的两个脚本：开源导出（脱敏不过就不写出）、打图库包（小包每个图型 N 张）。"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"


def load(name: str):
    spec = importlib.util.spec_from_file_location(f"script_{name}", SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def fake_skill(root: Path, extra: dict[str, str] | None = None) -> Path:
    allow = [line.strip() for line in (SCRIPTS / "skill_export" / "白名单.txt").read_text(encoding="utf-8").splitlines()
             if line.strip() and not line.startswith("#")]
    for rel in allow:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("# 示例\nEdison 11-01：先问清楚要画什么。\n" if rel.endswith(".md") else "print('ok')\n", encoding="utf-8")
    for rel, text in (extra or {}).items():
        (root / rel).write_text(text, encoding="utf-8")
    return root


def test_export_blocks_paths_and_client_names(tmp_path, capsys):
    exp = load("skill_export")
    src = fake_skill(tmp_path / "src", {"参考/坑清单.md": "路径 /Users/edison/x\n小凡老师那单画坏了\n"})
    deny = tmp_path / "词表.txt"
    deny.write_text("小凡\n", encoding="utf-8")
    out = tmp_path / "out"
    code = exp.main(["--version", "t1", "--source", str(src), "--denylist", str(deny), "--out", str(out)])
    text = capsys.readouterr().out
    assert code == 1 and not out.exists()
    assert "本机路径" in text and "客户名「小凡」" in text and "怎么改" in text


def test_export_needs_denylist(tmp_path, capsys):
    exp = load("skill_export")
    code = exp.main(["--version", "t2", "--source", str(fake_skill(tmp_path / "src")), "--denylist", str(tmp_path / "无"),
                     "--out", str(tmp_path / "out"), "--dry-run"])
    assert code == 1 and "没有客户名词表" in capsys.readouterr().out


def test_export_clean_skill_writes_repo(tmp_path):
    exp = load("skill_export")
    deny = tmp_path / "词表.txt"
    deny.write_text("小凡\n", encoding="utf-8")
    out = tmp_path / "out"
    code = exp.main(["--version", "t3", "--source", str(fake_skill(tmp_path / "src")), "--denylist", str(deny),
                     "--out", str(out), "--site", "https://tuku.example.org"])
    assert code == 0
    for f in ("LICENSE", "LICENSE-docs", "README.md", "CONTRIBUTING.md", "CITATION.cff", "脚本/在线查图.py",
              ".github/ISSUE_TEMPLATE/画坏了.yml"):
        assert (out / f).is_file(), f
    assert "负责人：先问清楚" in (out / "画图单.md").read_text(encoding="utf-8")
    assert "Edison" not in (out / "画图单.md").read_text(encoding="utf-8")
    assert "https://tuku.example.org" in (out / "README.md").read_text(encoding="utf-8")
    assert "Creative Commons Attribution 4.0 International Public License" in (out / "LICENSE-docs").read_text(encoding="utf-8")
    assert not list(out.rglob("*.png")) and not list(out.rglob("*.jsonl"))


def test_pack_lite_picks_per_type():
    pack = load("figures_build_pack")
    docs = [{"号": i, "档": (i % 3) + 1, "年份": str(2000 + i), "期刊": "Nature Human Behaviour", "h": None} for i in range(30)]
    for d in docs:
        d["主图型"] = "P1" if d["号"] < 25 else "R2"
        d["h"] = d
    lite = pack.pick(docs, "lite", 10)
    assert len(lite) == 15 and sum(1 for d in lite if d["主图型"] == "P1") == 10
    assert pack.pick(docs, "full", 10) == docs
    assert pack.name_for(docs[0], ".png") == "0_P1_NatureHumanBehaviour_2000.png"
