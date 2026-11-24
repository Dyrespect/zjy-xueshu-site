"""请求计数：用 Prometheus 官方客户端（prometheus_client）记，ops.metrics_flush 每分钟把「这一分钟多出来的数」存进 ops_samples。

为什么这样分两层：
- 计数用现成的 prometheus_client：Histogram（按 方法 × 路由模板 × 状态类 分桶记耗时）、Counter（页面访问）、Gauge（仪表）。
  同一份数在 /api/ops/metrics 给 Prometheus 拉（要令牌；以后装了 Prometheus + Grafana 不用改代码）。
- prometheus_client 只在内存里存「进程启动以来的累计」，答不了「近 7 天」「昨天」。没装 Prometheus 之前，
  每分钟取一次累计、减上一次，差值存进库（ops_samples），后台运维页和日报从库里读。
- 访客（独立访客）没有现成的隐私做法可抄：当天散列 = HMAC(SESSION_SECRET, 日期) + IP + UA，只存 16 位，换天换盐（倒推不出 IP）。
- 5xx 另记一条错误（路由模板、请求号、类型、已脱敏的摘要），落库进 ops_errors。
路由一律用模板（/api/delivery/{token}），不是原始网址。进程重启丢的只是最后不到一分钟的数。
"""

from __future__ import annotations

import hashlib
import hmac
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest

from app.core.reqlog import RequestInfo
from app.ops.stats import BUCKETS_MS, new_hist

_BOTS = ("bot", "spider", "crawl", "slurp", "curl/", "python-httpx", "python-requests", "wget", "headless", "monitor", "uptime")
# 前端页面的第一段 → 页面组（后台不算访问）
PAGE_GROUPS = {"": "首页", "figures": "图库", "order": "下单页", "d": "交付页", "chat": "网页聊天", "c": "兑换页", "x": "固定链接页",
               "redeem": "兑换页"}
SPA_ROUTE = "/{full_path:path}"
SlotKey = tuple[datetime, str, str, str]  # (分钟, kind, key, dim)


@dataclass
class Slot:
    n: int = 0
    total: float = 0.0
    max: float = 0.0
    hist: list[int] = field(default_factory=new_hist)


class Collector:
    def __init__(self, secret: str, tz: str = "Asia/Shanghai") -> None:
        self._secret = secret.encode() or b"ops"
        self._tz = ZoneInfo(tz)
        self._lock = threading.Lock()
        self.enabled = True
        # 每个 app 一份 registry（测试里会起很多个 app，不能用全局默认的）
        self.registry = CollectorRegistry(auto_describe=True)
        self.http = Histogram("psyppt_http_request_duration_seconds", "请求耗时（秒），按方法、路由模板、状态类",
                              ["method", "route", "status"], buckets=[b / 1000 for b in BUCKETS_MS], registry=self.registry)
        self.pages = Counter("psyppt_page_views", "整页访问（不含后台、爬虫）", ["page"], registry=self.registry)
        self.gauge = Gauge("psyppt_gauge", "运维仪表读数（水印队列、做单产能、磁盘……）", ["name"], registry=self.registry)
        self._prev: dict[tuple[str, str, str], tuple[list[float], float, float]] = {}  # 上一次取的累计（桶、次数、合计秒）
        self._page_prev: dict[str, float] = {}
        self.errors: list[dict[str, Any]] = []
        self.visitors: list[tuple[str, str, str]] = []  # (day, vh, page)

    # ---------------------------------------------------------------- 写入（请求线程里调，要快）

    def observe(self, info: RequestInfo) -> None:
        if not self.enabled:
            return
        self.http.labels(info.method, info.route[:160], f"{info.status // 100}xx").observe(info.ms / 1000)
        if info.status >= 500:
            with self._lock:
                self.errors.append({"at": datetime.now(timezone.utc), "rid": info.rid, "method": info.method,
                                    "route": info.route[:160], "status": info.status, "kind": info.error_kind or "5xx",
                                    "message": info.error_message[:300], "ms": round(info.ms, 1)})
        page = self._page_group(info)
        if page is not None:
            self.pages.labels(page).inc()
            day = datetime.now(timezone.utc).astimezone(self._tz).strftime("%Y-%m-%d")
            with self._lock:
                self.visitors.append((day, self.visitor_hash(day, info.client, info.user_agent), page))

    def set_gauge(self, name: str, value: float) -> None:
        self.gauge.labels(name).set(value)

    def _page_group(self, info: RequestInfo) -> str | None:
        if info.method != "GET" or info.status != 200 or info.route != SPA_ROUTE:
            return None
        if "text/html" not in info.accept:
            return None
        ua = info.user_agent.lower()
        if not ua or any(b in ua for b in _BOTS):
            return None
        first = info.path.strip("/").split("/")[0]
        if first == "admin":
            return None
        return PAGE_GROUPS.get(first, "其他页")

    def visitor_hash(self, day: str, ip: str, ua: str) -> str:
        salt = hmac.new(self._secret, day.encode(), hashlib.sha256).digest()
        return hmac.new(salt, f"{ip}|{ua}".encode(), hashlib.sha256).hexdigest()[:16]

    def exposition(self) -> bytes:
        """/api/ops/metrics 给 Prometheus 拉的文本。"""
        return generate_latest(self.registry)

    # ---------------------------------------------------------------- 取出（落库时调）

    def drain(self, *, now: datetime | None = None, **_: Any) -> tuple[dict[SlotKey, Slot], list[dict[str, Any]], list[tuple[str, str, str]]]:
        """取走「上次取到现在」多出来的数，记在上一分钟名下；和全部错误、全部访客。"""
        at = (now or datetime.now(timezone.utc)).replace(second=0, microsecond=0) - timedelta(minutes=1)
        slots: dict[SlotKey, Slot] = {}
        with self._lock:
            cur: dict[tuple[str, str, str], dict[str, Any]] = {}
            for metric in self.http.collect():
                for s in metric.samples:
                    lab = s.labels
                    k = (lab.get("method", ""), lab.get("route", ""), lab.get("status", ""))
                    c = cur.setdefault(k, {"buckets": {}, "count": 0.0, "sum": 0.0})
                    if s.name.endswith("_bucket"):
                        c["buckets"][float(lab["le"])] = s.value
                    elif s.name.endswith("_count"):
                        c["count"] = s.value
                    elif s.name.endswith("_sum"):
                        c["sum"] = s.value
            for k, c in cur.items():
                cum = [c["buckets"][le] for le in sorted(c["buckets"])]  # 累计桶，最后一个是 +Inf
                p_cum, p_n, p_sum = self._prev.get(k, ([0.0] * len(cum), 0.0, 0.0))
                dn = int(round(c["count"] - p_n))
                if dn <= 0:
                    continue
                d_cum = [a - b for a, b in zip(cum, p_cum)]
                per = [int(round(d_cum[0]))] + [int(round(d_cum[i] - d_cum[i - 1])) for i in range(1, len(d_cum))]
                top = max((i for i, v in enumerate(per) if v > 0), default=0)
                approx_max = BUCKETS_MS[top] if top < len(BUCKETS_MS) else BUCKETS_MS[-1] * 2  # 直方图没有最大值：取最慢那桶的上沿
                method, route, status = k
                slots[(at, "http", route, f"{method} {status}")] = Slot(n=dn, total=(c["sum"] - p_sum) * 1000, max=float(approx_max),
                                                                        hist=per)
                self._prev[k] = (cum, c["count"], c["sum"])
            for metric in self.pages.collect():
                for s in metric.samples:
                    if not s.name.endswith("_total"):
                        continue
                    page = s.labels.get("page", "")
                    d = s.value - self._page_prev.get(page, 0.0)
                    if d > 0:
                        slots[(at, "page", page, "pv")] = Slot(n=int(round(d)), total=d, max=d, hist=[])
                        self._page_prev[page] = s.value
            errors, self.errors = self.errors, []
            visitors, self.visitors = self.visitors, []
        return slots, errors, visitors

    def put_back(self, slots: dict[SlotKey, Slot]) -> None:
        """落库失败时：把「上次取到」退回去，下一分钟连这次的一起再取。"""
        with self._lock:
            for (_at, kind, key, dim), s in slots.items():
                if kind == "http":
                    method, _, status = dim.partition(" ")
                    k = (method, key, status)
                    if k in self._prev:
                        cum, n, sm = self._prev[k]
                        back, run = [], 0
                        for v in s.hist:
                            run += v
                            back.append(run)
                        self._prev[k] = ([a - b for a, b in zip(cum, back)], n - s.n, sm - s.total / 1000)
                elif kind == "page":
                    self._page_prev[key] = self._page_prev.get(key, 0.0) - s.n
