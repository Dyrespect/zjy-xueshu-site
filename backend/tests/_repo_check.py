"""把仓库根的 scripts/check.py 当模块加载（测试用）。"""

import importlib.util
import sys
from pathlib import Path

CHECK_PATH = Path(__file__).resolve().parents[2] / "scripts" / "check.py"


def load_check():
    name = "repo_check"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, CHECK_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod
