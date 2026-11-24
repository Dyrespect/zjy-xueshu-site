"""像真人的回复节奏（设计第六节）：什么时候发每一条。纯函数，不碰库；随机数从外面传进来（测试固定种子）。

一条回复的时间线（都从客人最后一条消息算）：
  看到、读完（read_base_s 随机 + 每字 read_per_char_s，封顶 read_max_s）
  → 打第一条（字数 ÷ typing_chars_per_s，上下浮动 typing_jitter，夹在 typing_min_s ~ typing_max_s）
  → 第一条发出（夹在 first_min_s ~ first_max_s；夜里 night_from~night_to 乘 night_factor、封顶 night_max_s）
  → 停一下（gap_s）再打下一条 ……
模型自己要想几秒：已经过了的时间算进去，到点了就马上发，不会因为模型慢再多等一截。
跟在回复后面的固定原文（交付说明、购买方式、二维码）像「贴过去」，前一条发完隔 gap_s 就发。
"""

from __future__ import annotations

import random
from datetime import datetime, time, timedelta

from app.intake.reception.kb import Rhythm


def _hm(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


def is_night(local: datetime, r: Rhythm) -> bool:
    a, b, t = _hm(r.night_from), _hm(r.night_to), local.time()
    return (a <= t < b) if a <= b else (t >= a or t < b)


def typing_seconds(text: str, r: Rhythm, rng: random.Random) -> float:
    base = len(text) / r.typing_chars_per_s
    jitter = 1 + rng.uniform(-r.typing_jitter, r.typing_jitter)
    return min(r.typing_max_s, max(r.typing_min_s, base * jitter))


def read_seconds(customer_chars: int, r: Rhythm, rng: random.Random) -> float:
    return min(r.read_max_s, rng.uniform(*r.read_base_s) + customer_chars * r.read_per_char_s)


def schedule(r: Rhythm, *, last_customer_at: datetime, now: datetime, local_now: datetime, customer_chars: int,
             segments: list[str], rng: random.Random, filler: str = "", filler_extra: bool = False) -> list[datetime]:
    """返回每一条（filler 在最前面，如果有）的发送时间。segments 是助手要发的几条文字。"""
    night = is_night(local_now, r)
    factor = r.night_factor if night else 1.0
    cap = r.night_max_s if night else r.first_max_s
    read = read_seconds(customer_chars, r, rng) * factor
    times: list[datetime] = []
    floor = now + timedelta(seconds=1)  # 模型已经想完了：最早也是现在之后一秒
    at = last_customer_at
    if filler:
        t_filler = at + timedelta(seconds=min(cap, max(r.first_min_s, read + typing_seconds(filler, r, rng))))
        t_filler = max(t_filler, floor)
        times.append(t_filler)
        at = t_filler + timedelta(seconds=rng.uniform(*r.filler_extra_s) if filler_extra else 0)
        read = 0.0
        floor = max(floor, at)
    for i, seg in enumerate(segments):
        typing = typing_seconds(seg, r, rng) * factor
        if i == 0 and not filler:
            delay = min(cap, max(r.first_min_s, read + typing))
            t = at + timedelta(seconds=delay)
        elif i == 0:
            t = at + timedelta(seconds=typing)
        else:
            t = times[-1] + timedelta(seconds=rng.uniform(*r.gap_s) + typing)
        t = max(t, floor if i == 0 else times[-1] + timedelta(seconds=0.5))
        times.append(t)
    return times


def paste_after(prev: datetime, r: Rhythm, rng: random.Random) -> datetime:
    """固定原文（交付说明、购买方式、二维码）跟在前一条后面「贴过去」。"""
    return prev + timedelta(seconds=rng.uniform(*r.gap_s))
