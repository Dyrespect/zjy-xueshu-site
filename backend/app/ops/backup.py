"""备份、保留、恢复演练（ops.backup_run / ops.backup_prune / ops.restore_drill 背后的实现）。

**引擎用现成的 restic**（BSD-2，单个程序）：去重、加密（仓库密码）、本机仓库或对象存储（腾讯云 COS 走 s3 协议）、
`forget --keep-daily 7 --keep-weekly 4 --prune` 就是我们要的保留策略、`restore` 做恢复演练。我们只写一层很薄的壳：
  1. 先用 SQLite 自带的在线备份把库拷一份一致的快照（core/dbbackup.py；restic 官方说数据库要先导出再备份）；
  2. 快照 + 清单（订单数、实付合计等核对数）+ DATA_DIR/files 交给 `restic backup`；
  3. `restic forget ... --prune` 按设置里的天数留；
  4. 恢复演练：`restic restore latest` 到临时目录 → 完整性检查 → 核对数和清单一样。
**restic 没装（要 Edison 点头装）之前**用内置兜底：同样的在线备份 + gzip + 清单，只有数据库、只在本机，按同样的 7 日 4 周留。
数据库连续备份（几秒一次，出事能恢复到任一时刻）用 Litestream，单独一个进程，配置样例在 deploy/ops/litestream.yml，也等点头。

密钥：restic 仓库密码只从 OPS_RESTIC_PASSWORD_FILE 指的文件给 restic（不读进来）；推 COS 的密钥只在 OPS_BACKUP_COS_ENABLED=true
时从 OPS_BACKUP_COS_CREDENTIALS_FILE 读，作为环境变量交给 restic 子进程，不写日志、不进事件（scripts/check.py 规矩 19）。
"""

from __future__ import annotations

import gzip
import json
import os
import shutil
import subprocess
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from app.core import dbbackup
from app.core.redact import redact_text
from app.ops.config import OpsConfig
from app.ops.models_io import BackupOut, DrillOut, PruneOut
from app.ops.runtime import OpsCtx

MANIFEST = "manifest.json"


class BackupError(RuntimeError):
    pass


# ---------------------------------------------------------------- 选引擎

def restic_bin(ctx: OpsCtx) -> str | None:
    return shutil.which(ctx.osettings.OPS_RESTIC_BIN)


def engine(ctx: OpsCtx) -> str:
    want = ctx.osettings.OPS_BACKUP_ENGINE
    ready = bool(restic_bin(ctx)) and bool(ctx.osettings.OPS_RESTIC_PASSWORD_FILE) and Path(
        str(ctx.osettings.OPS_RESTIC_PASSWORD_FILE)).is_file()
    if want == "restic":
        return "restic"
    if want == "builtin":
        return "builtin"
    return "restic" if ready else "builtin"


def _cos_creds(ctx: OpsCtx) -> dict[str, str] | None:
    """开关开着才读密钥文件。返回 None = 不推。"""
    os_ = ctx.osettings
    if not os_.OPS_BACKUP_COS_ENABLED:
        return None
    path = os_.OPS_BACKUP_COS_CREDENTIALS_FILE
    if path is None or not Path(path).is_file():
        raise BackupError("开了推对象存储，但 OPS_BACKUP_COS_CREDENTIALS_FILE 没给或文件不在")
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    missing = [k for k in ("secret_id", "secret_key", "bucket", "region") if not data.get(k)]
    if missing:
        raise BackupError(f"COS 密钥文件缺：{'、'.join(missing)}")
    return {k: str(v) for k, v in data.items()}


def restic_env(ctx: OpsCtx) -> tuple[dict[str, str], str]:
    """（交给 restic 子进程的环境变量，仓库地址的说法——不含密钥）。"""
    os_ = ctx.osettings
    env = {k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "LANG", "TMPDIR")}
    env["RESTIC_PASSWORD_FILE"] = str(os_.OPS_RESTIC_PASSWORD_FILE or "")
    env["RESTIC_CACHE_DIR"] = str(ctx.backup_dir / ".restic-cache")
    creds = _cos_creds(ctx)
    if creds:
        prefix = creds.get("prefix", "psyppt-backup").strip("/")
        repo = f"s3:https://cos.{creds['region']}.myqcloud.com/{creds['bucket']}/{prefix}"
        env["AWS_ACCESS_KEY_ID"], env["AWS_SECRET_ACCESS_KEY"] = creds["secret_id"], creds["secret_key"]
        env["AWS_DEFAULT_REGION"] = creds["region"]
        shown = f"COS {creds['bucket']}/{prefix}"
    else:
        repo = os_.OPS_RESTIC_REPOSITORY or str(ctx.backup_dir / "restic")
        shown = repo if not os_.OPS_RESTIC_REPOSITORY.startswith(("s3:", "rest:", "sftp:")) else os_.OPS_RESTIC_REPOSITORY.split("@")[-1]
    env["RESTIC_REPOSITORY"] = repo
    return env, shown


def _restic(ctx: OpsCtx, *args: str, timeout: int = 3600) -> subprocess.CompletedProcess[str]:
    exe = restic_bin(ctx)
    if exe is None:
        raise BackupError(f"没找到 restic（{ctx.osettings.OPS_RESTIC_BIN}）；要 Edison 点头装上，见 docs/运维/运维手册.md 第四节")
    if not ctx.osettings.OPS_RESTIC_PASSWORD_FILE:
        raise BackupError("没给 OPS_RESTIC_PASSWORD_FILE（restic 仓库密码文件）")
    env, _ = restic_env(ctx)
    p = subprocess.run([exe, *args], env=env, capture_output=True, text=True, timeout=timeout)
    if p.returncode != 0:
        raise BackupError(f"restic {args[0]} 失败：{redact_text(p.stderr.strip())[-300:]}")
    return p


# ---------------------------------------------------------------- 快照 + 清单（两个引擎都用）

def _local_name(ctx: OpsCtx, now: datetime) -> str:
    return now.astimezone(ZoneInfo(ctx.osettings.OPS_TIMEZONE)).strftime("app-%Y%m%d-%H%M%S")


def snapshot_db(ctx: OpsCtx, cfg: OpsConfig, dest_dir: Path, *, now: datetime) -> dict[str, Any]:
    """在线拷库到 dest_dir/app.db，查完整性、数核对数，写清单。返回清单。"""
    dest = dest_dir / "app.db"
    size = dbbackup.online_backup(ctx.settings.DATABASE_URL, dest)
    ok = dbbackup.integrity(dest)
    if ok != "ok":
        raise BackupError(f"拷出来的库完整性检查没过：{ok}")
    verify = dbbackup.facts(f"sqlite:///{dest}", cfg.backup.verify)
    local = now.astimezone(ZoneInfo(ctx.osettings.OPS_TIMEZONE))
    manifest = {"name": _local_name(ctx, now), "created_at": now.isoformat(), "db_bytes": size, "verify": verify,
                "weekly": local.weekday() == cfg.backup.weekly_weekday, "local_date": local.strftime("%Y-%m-%d")}
    (dest_dir / MANIFEST).write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    return manifest


def _include_dirs(ctx: OpsCtx) -> list[Path]:
    out = []
    for name in ctx.osettings.OPS_BACKUP_INCLUDE.split(","):
        p = ctx.settings.DATA_DIR / name.strip()
        if name.strip() and p.is_dir():
            out.append(p)
    return out


def _count_files(dirs: list[Path]) -> tuple[int, int]:
    n = size = 0
    for d in dirs:
        for f in d.rglob("*"):
            if f.is_file():
                n += 1
                size += f.stat().st_size
    return n, size


# ---------------------------------------------------------------- 备份

def run_backup(ctx: OpsCtx, cfg: OpsConfig, *, now: datetime) -> BackupOut:
    t0 = time.perf_counter()
    eng = engine(ctx)
    if dbbackup.sqlite_path(ctx.settings.DATABASE_URL) is None and eng == "builtin":
        raise BackupError("数据库不是 SQLite：用托管库自带的自动备份（见万人路线图）；文件备份要装 restic")
    if eng == "builtin":
        root = ctx.backup_dir / "builtin"
        work = Path(tempfile.mkdtemp(prefix="snap-", dir=_ensure(ctx.backup_dir)))
        try:
            m = snapshot_db(ctx, cfg, work, now=now)
            root.mkdir(parents=True, exist_ok=True)
            gz = root / f"{m['name']}.db.gz"
            with open(work / "app.db", "rb") as src, gzip.open(gz, "wb", compresslevel=6) as dst:
                shutil.copyfileobj(src, dst)
            (root / f"{m['name']}.json").write_text(json.dumps({**m, "engine": "builtin"}, ensure_ascii=False, indent=1), encoding="utf-8")
        finally:
            shutil.rmtree(work, ignore_errors=True)
        return BackupOut(name=m["name"], path=str(gz), db_bytes=m["db_bytes"], seconds=round(time.perf_counter() - t0, 2),
                         verify=m["verify"], weekly=m["weekly"], engine="builtin",
                         note="内置兜底：只有数据库、只在本机（装上 restic 后才备份客户文件、推对象存储）")
    # restic
    staging = _ensure(ctx.backup_dir / "staging")
    m: dict[str, Any] = {}
    if dbbackup.sqlite_path(ctx.settings.DATABASE_URL) is not None:
        m = snapshot_db(ctx, cfg, staging, now=now)
    dirs = _include_dirs(ctx)
    n_files, files_bytes = _count_files(dirs)
    _ensure_repo(ctx)
    p = _restic(ctx, "backup", "--json", "--tag", "psyppt", "--host", "psyppt", str(staging), *map(str, dirs))
    summary = next((json.loads(x) for x in reversed(p.stdout.splitlines()) if '"summary"' in x), {})
    _, shown = restic_env(ctx)
    return BackupOut(name=m.get("name") or _local_name(ctx, now), path=f"{shown}#{summary.get('snapshot_id', '')[:8]}",
                     db_bytes=m.get("db_bytes", 0), files_count=n_files, files_bytes=files_bytes,
                     seconds=round(time.perf_counter() - t0, 2), verify=m.get("verify", {}), weekly=bool(m.get("weekly")),
                     engine="restic", note=f"新增 {summary.get('data_added', 0) / 1e6:.1f} MB")


def _ensure(p: Path) -> Path:
    p.mkdir(parents=True, exist_ok=True)
    return p


def _ensure_repo(ctx: OpsCtx) -> None:
    exe = restic_bin(ctx)
    env, _ = restic_env(ctx)
    probe = subprocess.run([exe or "restic", "cat", "config"], env=env, capture_output=True, text=True, timeout=120)
    if probe.returncode != 0:
        _restic(ctx, "init")


# ---------------------------------------------------------------- 保留

def builtin_list(ctx: OpsCtx) -> list[dict[str, Any]]:
    root = ctx.backup_dir / "builtin"
    out = []
    for js in sorted(root.glob("app-*.json"), reverse=True) if root.is_dir() else []:
        try:
            m = json.loads(js.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        gz = root / f"{m.get('name', js.stem)}.db.gz"
        m["path"], m["bytes"] = str(gz), gz.stat().st_size if gz.exists() else 0
        out.append(m)
    return out


def prune(ctx: OpsCtx, cfg: OpsConfig) -> PruneOut:
    b = cfg.backup
    if engine(ctx) == "restic":
        _restic(ctx, "forget", "--tag", "psyppt", "--keep-daily", str(b.keep_daily), "--keep-weekly", str(b.keep_weekly), "--prune")
        return PruneOut(kept=[f"restic：留最近 {b.keep_daily} 天每天一份、{b.keep_weekly} 周每周一份"], removed=[])
    items = [m for m in builtin_list(ctx) if m.get("local_date")]  # 新的在前
    keep: set[str] = set()
    days: list[str] = []
    for m in items:  # 日备：每天留最新一份，留最近 keep_daily 天（和 restic --keep-daily 一个意思）
        if m["local_date"] not in days and len(days) < b.keep_daily:
            days.append(m["local_date"])
            keep.add(m["name"])
    weeks: list[str] = []
    for m in items:  # 周备：每周留一份（那周标了 weekly 的，没有就那周最新的），留最近 keep_weekly 周
        wk = _week(m)
        if wk in weeks:
            continue
        if len(weeks) >= b.keep_weekly:
            break
        same = [x for x in items if _week(x) == wk]
        weeks.append(wk)
        keep.add(next((x for x in same if x.get("weekly")), same[0])["name"])
    removed = []
    root = ctx.backup_dir / "builtin"
    for m in items:
        if m["name"] in keep:
            continue
        for f in (root / f"{m['name']}.db.gz", root / f"{m['name']}.json"):
            f.unlink(missing_ok=True)
        removed.append(m["name"])
    return PruneOut(kept=[m["name"] for m in items if m["name"] in keep], removed=removed)


def _week(m: dict[str, Any]) -> str:
    d = datetime.fromisoformat(m["local_date"])
    return f"{d.isocalendar()[0]}-{d.isocalendar()[1]}"


# ---------------------------------------------------------------- 恢复演练

def drill(ctx: OpsCtx, cfg: OpsConfig) -> DrillOut:
    """在临时目录里真恢复最新一份：完整性检查 + 核对数和清单一样 + 迁移版本对得上。临时目录用完删掉。"""
    t0 = time.perf_counter()
    tmp = Path(tempfile.mkdtemp(prefix="restore-drill-"))
    try:
        if engine(ctx) == "restic":
            _restic(ctx, "restore", "latest", "--tag", "psyppt", "--target", str(tmp),
                    "--include", str(ctx.backup_dir / "staging"))
            found = list(tmp.rglob("staging/app.db"))
            if not found:
                raise BackupError("restic 恢复出来的东西里没有数据库快照")
            db_file, manifest = found[0], json.loads((found[0].parent / MANIFEST).read_text(encoding="utf-8"))
            name = f"restic latest（{manifest.get('name', '')}）"
        else:
            items = builtin_list(ctx)
            if not items:
                raise BackupError("还没有备份，演练不了")
            manifest = items[0]
            db_file = tmp / "app.db"
            with gzip.open(manifest["path"], "rb") as src, open(db_file, "wb") as dst:
                shutil.copyfileobj(src, dst)
            name = manifest["name"]
        integ = dbbackup.integrity(db_file)
        actual = dbbackup.facts(f"sqlite:///{db_file}", cfg.backup.verify)
        labels = {v.key: v.label for v in cfg.backup.verify}
        checks = [{"key": k, "label": labels.get(k, k), "expected": manifest.get("verify", {}).get(k), "actual": v,
                   "ok": manifest.get("verify", {}).get(k) == v} for k, v in actual.items()]
        version = dbbackup.facts(f"sqlite:///{db_file}", [{"key": "n", "table": "alembic_version", "agg": "count"}])
        alembic = "有迁移版本表" if version.get("n") else "没有迁移版本表"
        return DrillOut(backup=name, integrity=integ, checks=checks, files_ok=integ == "ok" and all(c["ok"] for c in checks),
                        alembic=alembic, seconds=round(time.perf_counter() - t0, 2))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def list_backups(ctx: OpsCtx) -> dict[str, Any]:
    """后台「备份」页：引擎、仓库在哪（不含密钥）、内置兜底的列表、restic 快照列表。"""
    eng = engine(ctx)
    out: dict[str, Any] = {"engine": eng, "restic_installed": bool(restic_bin(ctx)), "cos_enabled": ctx.osettings.OPS_BACKUP_COS_ENABLED,
                           "builtin": builtin_list(ctx)[:30], "restic": [], "where": str(ctx.backup_dir), "error": ""}
    if eng == "restic":
        try:
            _, shown = restic_env(ctx)
            out["where"] = shown
            p = _restic(ctx, "snapshots", "--json", "--tag", "psyppt", timeout=120)
            out["restic"] = [{"id": s.get("short_id"), "time": s.get("time"), "paths": len(s.get("paths", []))}
                             for s in reversed(json.loads(p.stdout or "[]"))][:30]
        except Exception as e:  # noqa: BLE001
            out["error"] = redact_text(str(e))[:200]
    return out


def max_age_ok(done_at: datetime | None, now: datetime, hours: float) -> bool:
    return done_at is not None and now - done_at <= timedelta(hours=hours)
