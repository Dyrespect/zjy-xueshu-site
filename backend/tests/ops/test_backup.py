"""备份：内置兜底（在线备份 + 完整性 + 清单）、保留 7 日 4 周、恢复演练对得上、restic 的命令行和密钥只给子进程、默认不推对象存储。"""

from __future__ import annotations

import gzip
import json
import os
import stat
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core import dbbackup
from app.core.events import Event
from app.ops import backup
from app.ops.config import OpsConfig
from app.ops.runtime import get_ops
from tests.conftest import PG_MODE
from tests.ops.helpers import login, make_order, ops_app, write

SQLITE_ONLY = pytest.mark.skipif(PG_MODE, reason="内置备份只做 SQLite（PG 用托管库的自动备份或 pg_dump，core/dbbackup.py）")


@SQLITE_ONLY
def test_builtin_backup_drill_and_api(settings, notifier):
    app = ops_app(settings, notifier, OPS_BACKUP_ENGINE="auto")  # 没装 restic、没密码文件：自动用内置兜底
    with TestClient(app) as c:
        login(c)
        ctx = get_ops(app)
        with ctx.database.session() as db:
            for amt in ("29.90", "44.90", "0.00", ""):
                make_order(db, paid=amt)
        r = c.post("/api/admin/ops/backups/run").json()
        assert r["exit"] == "ok", r
        res = r["result"]
        assert res["engine"] == "builtin" and res["verify"]["orders"] == 4 and res["verify"]["paid_sum"] == "74.80"
        gz = Path(res["path"])
        assert gz.exists() and gz.name.endswith(".db.gz")
        raw = gzip.decompress(gz.read_bytes())
        assert raw[:16] == b"SQLite format 3\x00"  # 真是一个库，不是半截文件
        # 备份之后又来一单：演练对的是备份那一刻的清单，照样对得上
        with ctx.database.session() as db:
            make_order(db, paid="59.90")
        d = c.post("/api/admin/ops/backups/drill").json()
        assert d["exit"] == "ok", d
        checks = {x["key"]: x for x in d["result"]["checks"]}
        assert checks["orders"]["actual"] == 4 and checks["paid_sum"]["actual"] == "74.80" and all(x["ok"] for x in checks.values())
        assert d["result"]["integrity"] == "ok"
        lst = c.get("/api/admin/ops/backups").json()
        assert lst["engine"] == "builtin" and lst["builtin"][0]["name"] == res["name"] and lst["last_drill"]["ok"] is True
        # 备份坏了：演练失败、记事件
        gz.write_bytes(gz.read_bytes()[:200])
        d = c.post("/api/admin/ops/backups/drill").json()
        assert d["exit"] == "fail" and d["result"]["error"]
        with ctx.database.session() as db:
            types = [e.type for e in db.scalars(select(Event).where(Event.type.like("ops.%")))]
        assert "ops.backup_done" in types and types.count("ops.restore_drilled") == 2


@SQLITE_ONLY
def test_online_backup_is_not_a_file_copy(settings, notifier, tmp_path):
    """WAL 模式下没 checkpoint 的数据也要在备份里（直接拷 app.db 会漏）。"""
    app = ops_app(settings, notifier)
    with TestClient(app):
        ctx = get_ops(app)
        with ctx.database.session() as db:
            for _ in range(30):
                make_order(db)
        out = tmp_path / "copy.db"
        dbbackup.online_backup(settings.DATABASE_URL, out)
        assert dbbackup.integrity(out) == "ok"
        assert dbbackup.facts(f"sqlite:///{out}", [{"key": "n", "table": "intake_orders", "agg": "count"}])["n"] == 30


def test_builtin_prune_keeps_7_daily_and_4_weekly(settings, notifier):
    app = ops_app(settings, notifier)
    with TestClient(app):
        ctx = get_ops(app)
        root = ctx.backup_dir / "builtin"
        day0 = datetime(2026, 11, 18).date()  # 周三
        names = []
        for i in range(30):
            d = day0 - timedelta(days=i)
            for hh in ("0330", "1500"):  # 有的天备了两次（手动又点了一次）
                name = f"app-{d:%Y%m%d}-{hh}00"
                names.append(name)
                write(root / f"{name}.json", json.dumps({"name": name, "local_date": d.isoformat(), "weekly": d.weekday() == 6}))
                (root / f"{name}.db.gz").write_bytes(b"x")
        out = backup.prune(ctx, OpsConfig())
        kept = out.kept
        daily = [f"app-{day0 - timedelta(days=i):%Y%m%d}-150000" for i in range(7)]  # 每天留最新那份
        assert kept[:7] == daily
        weekly_extra = [k for k in kept if k not in daily]
        assert all(datetime.strptime(k[4:12], "%Y%m%d").weekday() == 6 for k in weekly_extra)  # 多留的都是周日那份
        assert len(kept) == 7 + len(weekly_extra) and 2 <= len(weekly_extra) <= 4
        assert len(list(root.glob("*.db.gz"))) == len(kept) and len(out.removed) == 60 - len(kept)


FAKE_RESTIC = r'''#!{py}
import json, os, sys
log = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), "..", "restic.log")  # 子进程只拿到白名单里的环境变量
with open(log, "a") as f:
    f.write(json.dumps({{"args": sys.argv[1:], "env": sorted(k for k in os.environ if k.startswith(("AWS_", "RESTIC_"))),
                        "repo": os.environ.get("RESTIC_REPOSITORY", "")}}) + "\n")
cmd = sys.argv[1]
if cmd == "cat":
    sys.exit(0)
if cmd == "backup":
    print(json.dumps({{"message_type": "summary", "snapshot_id": "abcdef1234567890", "data_added": 1234567}}))
if cmd == "snapshots":
    print(json.dumps([{{"short_id": "abcdef12", "time": "2026-11-18T03:30:00Z", "paths": ["/x"]}}]))
sys.exit(0)
'''


def _fake_restic(tmp_path: Path) -> tuple[Path, Path]:
    exe = tmp_path / "bin" / "restic"
    write(exe, FAKE_RESTIC.format(py=sys.executable))
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    return exe, tmp_path / "restic.log"


def test_restic_engine_commands_and_cos_off_by_default(settings, notifier, tmp_path, monkeypatch):
    exe, log = _fake_restic(tmp_path)
    pw = write(tmp_path / "restic-pass", "local-test-password")
    (settings.DATA_DIR / "files" / "a").mkdir(parents=True)
    (settings.DATA_DIR / "files" / "a" / "论文.pdf").write_bytes(b"%PDF")
    creds = tmp_path / "cos.json"  # 开关关着：这个文件根本不存在也没关系（不读）
    app = ops_app(settings, notifier, OPS_RESTIC_BIN=str(exe), OPS_RESTIC_PASSWORD_FILE=pw, OPS_BACKUP_COS_CREDENTIALS_FILE=creds)
    with TestClient(app) as c:
        login(c)
        ctx = get_ops(app)
        assert backup.engine(ctx) == "restic"
        r = c.post("/api/admin/ops/backups/run").json()
        assert r["exit"] == "ok" and r["result"]["engine"] == "restic" and r["result"]["files_count"] == 1
        calls = [json.loads(x) for x in log.read_text().splitlines()]
        bk = next(x for x in calls if x["args"][0] == "backup")
        assert "--tag" in bk["args"] and str(ctx.backup_dir / "staging") in bk["args"] and str(settings.DATA_DIR / "files") in bk["args"]
        assert bk["repo"] == str(ctx.backup_dir / "restic") and not [k for k in bk["env"] if k.startswith("AWS_")]  # 默认不推 COS
        fg = next(x for x in calls if x["args"][0] == "forget")
        assert fg["args"][fg["args"].index("--keep-daily") + 1] == "7" and fg["args"][fg["args"].index("--keep-weekly") + 1] == "4"
        assert "--prune" in fg["args"]


def test_restic_cos_credentials_only_reach_the_subprocess(settings, notifier, tmp_path, monkeypatch):
    exe, log = _fake_restic(tmp_path)
    pw = write(tmp_path / "restic-pass", "local-test-password")
    secret = "fake-cos-secret-value-zzz"
    creds = write(tmp_path / "cos.json", json.dumps({"secret_id": "fake-id-xyz", "secret_key": secret, "bucket": "psyppt-backup-1250000000",
                                                     "region": "ap-shanghai", "prefix": "db"}))
    app = ops_app(settings, notifier, OPS_RESTIC_BIN=str(exe), OPS_RESTIC_PASSWORD_FILE=pw, OPS_BACKUP_COS_ENABLED=True,
                  OPS_BACKUP_COS_CREDENTIALS_FILE=creds)
    with TestClient(app) as c:
        login(c)
        r = c.post("/api/admin/ops/backups/run").json()
        assert r["exit"] == "ok"
        bk = next(json.loads(x) for x in log.read_text().splitlines() if json.loads(x)["args"][0] == "backup")
        assert bk["repo"] == "s3:https://cos.ap-shanghai.myqcloud.com/psyppt-backup-1250000000/db"
        assert {"AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "RESTIC_PASSWORD_FILE"} <= set(bk["env"])
        ctx = get_ops(app)
        with ctx.database.session() as db:
            dumped = json.dumps([e.content for e in db.scalars(select(Event))], ensure_ascii=False)
        assert secret not in dumped and "fake-id-xyz" not in dumped and "local-test-password" not in dumped
        assert secret not in json.dumps(c.get("/api/admin/ops/backups").json(), ensure_ascii=False)
        assert secret not in os.environ.get("AWS_SECRET_ACCESS_KEY", "")  # 只给子进程，不写进自己的环境


def test_backup_failure_records_event_and_alerts(settings, notifier, tmp_path):
    app = ops_app(settings, notifier, OPS_BACKUP_ENGINE="restic", OPS_RESTIC_BIN=str(tmp_path / "没有这个程序"))
    with TestClient(app) as c:
        login(c)
        r = c.post("/api/admin/ops/backups/run").json()
        assert r["exit"] == "fail" and "restic" in r["detail"]
        ctx = get_ops(app)
        from app.core.nodes import NodeCall, run_node

        with ctx.database.session() as db:
            out = run_node("ops.alert_eval", NodeCall(db, ctx, "test"), {}).output
        assert "backup_failed" in out.opened and any("备份失败" in s for s in notifier.sent)
