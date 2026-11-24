"""限流：计数不放进程内存，多个网站进程、多台机器看到的是同一份（设计第六节）。

算法和 Redis 后端用现成的 `limits` 库（MIT）：滑动窗口（moving window，跟原来各模块进程内存里的 deque 同一个算法）。
后端按 RATE_LIMIT_BACKEND：
- `db`（现在、百人档）：本文件的 SqlStorage，把 limits 要的「一个 key 一串时间戳」存在表 core_rate_events
  （一次一行，worker 每 10 分钟删两天前的，见 core.tasks.prune）。主库是 SQLite 时，这张表放在旁边单独一个
  SQLite 文件 DATA_DIR/ratelimit.db：限流自己开事务写，主库同一时刻只有一个写的，请求已经拿着主库写锁时再去主库写
  会自己等自己（11-18 合并入口后撞到过，等满 15 秒报 database is locked）；分开以后各有各的锁，也少占主库的写锁。
  主库是 PG 就用主库（没有整库写锁）。数和记在一个写事务里、同一个 key 加事务锁，
  两种库都精确（11-18 实测：PG 上不加锁，20 个并发打上限 5 会放过 13 个）。
- `redis`（万人档）：limits 自带的 Redis 存储，不用写代码；`pip install redis`，REDIS_URL=redis://…。

用法（接口一开始、动库之前调；限流自己开很短的事务，不跟请求的事务搅在一起）：

    limiter = get_ratelimiter(request)            # app.core.deps
    if not limiter.hit("shop.checkout", ip, limit=20, window=3600):
        raise HTTPException(429, ...)

「错几次锁一阵」（登录、令牌）：`limiter.test(...)` 看还能不能试，错了 `hit`，对了 `clear`（三处参数要一样）。
「只记一笔、按窗口数」（入口：访客问答每个 IP 每天几次，阈值在后台设置里）：`add(bucket, key)`、`count(bucket, key, window)`，
窗口最长两天（库里只留两天）。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from limits import RateLimitItemPerSecond
from limits.storage import MovingWindowSupport, Storage, storage_from_string
from limits.strategies import MovingWindowRateLimiter
from sqlalchemy import Index, Integer, String, delete, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, Database, PoolSettings, UTCDateTime, txn_lock, utcnow

KEEP_DAYS = 2


class RateEvent(Base):
    __tablename__ = "core_rate_events"
    __table_args__ = (Index("ix_core_rate_events_key_at", "key", "at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(255))
    at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)


class SqlStorage(Storage, MovingWindowSupport):
    """limits 的存储后端：存进我们自己的库（SQLite / PostgreSQL 都行）。只配 MovingWindowRateLimiter 用。"""

    STORAGE_SCHEME = ["xh-sqlalchemy"]

    def __init__(self, database: Database, *, owned: bool = False) -> None:
        super().__init__(uri=None, wrap_exceptions=False)
        self.database = database
        self.owned = owned  # 旁边那个 SQLite 文件是限流自己开的：关的时候要关掉

    @property
    def base_exceptions(self) -> type[Exception]:
        return SQLAlchemyError

    def acquire_entry(self, key: str, limit: int, expiry: int, amount: int = 1) -> bool:
        if amount > limit:
            return False
        now = utcnow()
        with self.database.session() as db:  # 数和记在同一个写事务里：SQLite 写会话独占；PG 上同一个 key 加事务锁
            txn_lock(db, f"rate:{key}")
            n = db.scalar(select(func.count()).select_from(RateEvent).where(
                RateEvent.key == key[:255], RateEvent.at >= now - timedelta(seconds=expiry))) or 0
            if n + amount > limit:
                return False
            db.add_all([RateEvent(key=key[:255], at=now) for _ in range(amount)])
            return True

    def get_moving_window(self, key: str, limit: int, expiry: int) -> tuple[float, int]:
        now = utcnow()
        with self.database.session(write=False) as db:
            n, oldest = db.execute(select(func.count(), func.min(RateEvent.at)).where(
                RateEvent.key == key[:255], RateEvent.at >= now - timedelta(seconds=expiry))).one()
        if not n:
            return now.timestamp(), 0
        oldest = oldest if oldest.tzinfo else oldest.replace(tzinfo=timezone.utc)
        return oldest.timestamp(), int(n)

    def clear(self, key: str) -> None:
        with self.database.session() as db:
            db.execute(delete(RateEvent).where(RateEvent.key == key[:255]))

    def prune(self, keep_days: int = KEEP_DAYS) -> int:
        return prune_rate_events(self.database, keep_days=keep_days)

    def check(self) -> bool:
        try:
            with self.database.session(write=False) as db:
                db.scalar(select(func.count()).select_from(RateEvent).limit(1))
            return True
        except SQLAlchemyError:
            return False

    def reset(self) -> int | None:
        with self.database.session() as db:
            return db.execute(delete(RateEvent)).rowcount

    # 固定窗口那套这里不用（只用滑动窗口）；limits 要求有这几个方法
    def incr(self, key: str, expiry: int, amount: int = 1) -> int:
        raise NotImplementedError("SqlStorage 只配 MovingWindowRateLimiter 用")

    def get(self, key: str) -> int:
        raise NotImplementedError("SqlStorage 只配 MovingWindowRateLimiter 用")

    def get_expiry(self, key: str) -> float:
        raise NotImplementedError("SqlStorage 只配 MovingWindowRateLimiter 用")


class RateLimits:
    """业务模块用的入口（app.state.ratelimit）。bucket 是哪一类（如 shop.checkout），key 是谁（通常是 IP）。"""

    _EVENTS = RateLimitItemPerSecond(1_000_000, KEEP_DAYS * 86400)  # add / count 用：只记事件，数的时候再定窗口

    def __init__(self, storage: Storage) -> None:
        self.storage = storage
        self.limiter = MovingWindowRateLimiter(storage)

    def add(self, bucket: str, key: str) -> None:
        """记一笔（不拦）。"""
        self.limiter.hit(self._EVENTS, bucket, key)

    def count(self, bucket: str, key: str, window: float) -> int:
        """最近 window 秒（最长两天）记了几笔。"""
        w = int(min(window, self._EVENTS.get_expiry()))
        return int(self.storage.get_moving_window(self._EVENTS.key_for(bucket, key), self._EVENTS.amount, w)[1])

    @staticmethod
    def _item(limit: int, window: float) -> RateLimitItemPerSecond:
        return RateLimitItemPerSecond(max(1, int(limit)), max(1, int(window)))

    def hit(self, bucket: str, key: str, *, limit: int, window: float) -> bool:
        """窗口（秒）内还没满 limit 次 → 记一次、放行（True）；满了 → 不记、拦下（False）。"""
        return self.limiter.hit(self._item(limit, window), bucket, key)

    def test(self, bucket: str, key: str, *, limit: int, window: float) -> bool:
        """还能再来一次吗（不记）。"""
        return self.limiter.test(self._item(limit, window), bucket, key)

    def used(self, bucket: str, key: str, *, limit: int, window: float) -> int:
        """窗口内已经记了几次。"""
        return limit - self.limiter.get_window_stats(self._item(limit, window), bucket, key).remaining

    def clear(self, bucket: str, key: str, *, limit: int, window: float) -> None:
        self.limiter.clear(self._item(limit, window), bucket, key)

    def close(self) -> None:
        if getattr(self.storage, "owned", False):
            self.storage.database.dispose()

    def prune(self) -> int:
        """删两天前的记录（存在库里时；Redis 自己过期）。"""
        fn = getattr(self.storage, "prune", None)
        return fn() if fn else 0


def build_ratelimiter(settings, database: Database) -> RateLimits:
    if settings.RATE_LIMIT_BACKEND == "redis":
        return RateLimits(storage_from_string(settings.REDIS_URL))  # 没装 redis 包时 limits 会报缺依赖
    if database.dialect != "sqlite":
        return RateLimits(SqlStorage(database))
    side = Database(f"sqlite:///{settings.DATA_DIR / 'ratelimit.db'}", PoolSettings(size=5, max_overflow=20,
                                                                              busy_timeout_ms=settings.DB_BUSY_TIMEOUT_MS))
    RateEvent.__table__.create(side.engine, checkfirst=True)  # 只这一张表，启动时建；几个进程同时建也没事
    return RateLimits(SqlStorage(side, owned=True))


def prune_rate_events(database: Database, *, keep_days: int = KEEP_DAYS) -> int:
    with database.session() as db:
        return db.execute(delete(RateEvent).where(RateEvent.at < utcnow() - timedelta(days=keep_days))).rowcount or 0
