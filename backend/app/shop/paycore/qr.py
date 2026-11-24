"""二维码（微信 Native 给的 code_url 要画成二维码让客人扫）。

不加依赖：照 Project Nayuki 的 QR Code generator（MIT 许可，https://www.nayuki.io/page/qr-code-generator-library）
的算法写的精简版——只做字节模式、版本 1–10（纠错 M 级最多 213 个字节，微信的 code_url 几十个字节），
自动挑罚分最低的掩码。返回模块矩阵（True = 深色），前端按矩阵画 SVG（颜色走设计变量）。
"""

from __future__ import annotations

# 纠错等级 → (格式位里的编号, 每块纠错码字数[版本], 块数[版本])；版本 1–10，下标 0 不用
_ECL = {
    "L": (1, (-1, 7, 10, 15, 20, 26, 18, 20, 24, 30, 18), (-1, 1, 1, 1, 1, 1, 2, 2, 2, 2, 4)),
    "M": (0, (-1, 10, 16, 26, 18, 24, 16, 18, 22, 22, 26), (-1, 1, 1, 1, 2, 2, 4, 4, 4, 5, 5)),
    "Q": (3, (-1, 13, 22, 18, 26, 18, 24, 18, 22, 20, 24), (-1, 1, 1, 2, 2, 4, 4, 6, 6, 8, 8)),
    "H": (2, (-1, 17, 28, 22, 16, 22, 28, 26, 26, 24, 28), (-1, 1, 1, 2, 4, 4, 4, 5, 6, 8, 8)),
}
MAX_VERSION = 10


def _raw_modules(ver: int) -> int:
    n = (16 * ver + 128) * ver + 64
    if ver >= 2:
        na = ver // 7 + 2
        n -= (25 * na - 10) * na - 55
        if ver >= 7:
            n -= 36
    return n


def _data_codewords(ver: int, ecl: str) -> int:
    _, ecc, blocks = _ECL[ecl]
    return _raw_modules(ver) // 8 - ecc[ver] * blocks[ver]


def _gf_mul(x: int, y: int) -> int:
    z = 0
    for i in reversed(range(8)):
        z = (z << 1) ^ ((z >> 7) * 0x11D)
        z ^= ((y >> i) & 1) * x
    return z


def _rs_divisor(degree: int) -> list[int]:
    result = [0] * (degree - 1) + [1]
    root = 1
    for _ in range(degree):
        for j in range(degree):
            result[j] = _gf_mul(result[j], root)
            if j + 1 < degree:
                result[j] ^= result[j + 1]
        root = _gf_mul(root, 0x02)
    return result


def _rs_remainder(data: list[int], divisor: list[int]) -> list[int]:
    result = [0] * len(divisor)
    for b in data:
        factor = b ^ result.pop(0)
        result.append(0)
        for i, coef in enumerate(divisor):
            result[i] ^= _gf_mul(coef, factor)
    return result


def _with_ecc(data: list[int], ver: int, ecl: str) -> list[int]:
    _, ecc_t, blocks_t = _ECL[ecl]
    nblocks, ecclen = blocks_t[ver], ecc_t[ver]
    raw = _raw_modules(ver) // 8
    nshort = nblocks - raw % nblocks
    shortlen = raw // nblocks
    div = _rs_divisor(ecclen)
    blocks, k = [], 0
    for i in range(nblocks):
        dat = data[k: k + shortlen - ecclen + (0 if i < nshort else 1)]
        k += len(dat)
        ecc = _rs_remainder(dat, div)
        if i < nshort:
            dat = dat + [0]
        blocks.append(dat + ecc)
    out = []
    for i in range(len(blocks[0])):
        for j, blk in enumerate(blocks):
            if i != shortlen - ecclen or j >= nshort:
                out.append(blk[i])
    return out


class _Grid:
    def __init__(self, ver: int) -> None:
        self.ver = ver
        self.size = ver * 4 + 17
        self.m = [[False] * self.size for _ in range(self.size)]
        self.fn = [[False] * self.size for _ in range(self.size)]

    def set_fn(self, x: int, y: int, dark: bool) -> None:
        self.m[y][x] = dark
        self.fn[y][x] = True

    def align_positions(self) -> list[int]:
        if self.ver == 1:
            return []
        na = self.ver // 7 + 2
        step = (self.ver * 8 + na * 3 + 5) // (na * 4 - 4) * 2
        return [6] + list(reversed([self.size - 7 - i * step for i in range(na - 1)]))

    def draw_functions(self) -> None:
        for i in range(self.size):
            self.set_fn(6, i, i % 2 == 0)
            self.set_fn(i, 6, i % 2 == 0)
        for cx, cy in ((3, 3), (self.size - 4, 3), (3, self.size - 4)):
            for dy in range(-4, 5):
                for dx in range(-4, 5):
                    x, y = cx + dx, cy + dy
                    if 0 <= x < self.size and 0 <= y < self.size:
                        self.set_fn(x, y, max(abs(dx), abs(dy)) not in (2, 4))
        pos = self.align_positions()
        n = len(pos)
        for i in range(n):
            for j in range(n):
                if (i == 0 and j == 0) or (i == 0 and j == n - 1) or (i == n - 1 and j == 0):
                    continue
                for dy in range(-2, 3):
                    for dx in range(-2, 3):
                        self.set_fn(pos[i] + dx, pos[j] + dy, max(abs(dx), abs(dy)) != 1)
        self.draw_format(0, "M")
        if self.ver >= 7:
            rem = self.ver
            for _ in range(12):
                rem = (rem << 1) ^ ((rem >> 11) * 0x1F25)
            bits = self.ver << 12 | rem
            for i in range(18):
                bit = (bits >> i) & 1 != 0
                a, b = self.size - 11 + i % 3, i // 3
                self.set_fn(a, b, bit)
                self.set_fn(b, a, bit)

    def draw_format(self, mask: int, ecl: str) -> None:
        data = _ECL[ecl][0] << 3 | mask
        rem = data
        for _ in range(10):
            rem = (rem << 1) ^ ((rem >> 9) * 0x537)
        bits = (data << 10 | rem) ^ 0x5412

        def bit(i: int) -> bool:
            return (bits >> i) & 1 != 0

        for i in range(6):
            self.set_fn(8, i, bit(i))
        self.set_fn(8, 7, bit(6))
        self.set_fn(8, 8, bit(7))
        self.set_fn(7, 8, bit(8))
        for i in range(9, 15):
            self.set_fn(14 - i, 8, bit(i))
        for i in range(8):
            self.set_fn(self.size - 1 - i, 8, bit(i))
        for i in range(8, 15):
            self.set_fn(8, self.size - 15 + i, bit(i))
        self.set_fn(8, self.size - 8, True)

    def draw_codewords(self, data: list[int]) -> None:
        i, right = 0, self.size - 1
        total = len(data) * 8
        while right >= 1:
            if right == 6:
                right = 5
            for vert in range(self.size):
                for j in range(2):
                    x = right - j
                    upward = ((right + 1) & 2) == 0
                    y = self.size - 1 - vert if upward else vert
                    if not self.fn[y][x] and i < total:
                        self.m[y][x] = (data[i >> 3] >> (7 - (i & 7))) & 1 != 0
                        i += 1
            right -= 2

    def apply_mask(self, mask: int) -> None:
        for y in range(self.size):
            for x in range(self.size):
                if self.fn[y][x]:
                    continue
                if mask == 0:
                    inv = (x + y) % 2 == 0
                elif mask == 1:
                    inv = y % 2 == 0
                elif mask == 2:
                    inv = x % 3 == 0
                elif mask == 3:
                    inv = (x + y) % 3 == 0
                elif mask == 4:
                    inv = (x // 3 + y // 2) % 2 == 0
                elif mask == 5:
                    inv = x * y % 2 + x * y % 3 == 0
                elif mask == 6:
                    inv = (x * y % 2 + x * y % 3) % 2 == 0
                else:
                    inv = ((x + y) % 2 + x * y % 3) % 2 == 0
                if inv:
                    self.m[y][x] = not self.m[y][x]

    def penalty(self) -> int:
        n, m, score = self.size, self.m, 0
        lines = [m[y] for y in range(n)] + [[m[y][x] for y in range(n)] for x in range(n)]
        finder = (True, False, True, True, True, False, True)
        for line in lines:
            run, prev = 0, None
            for v in line:
                if v == prev:
                    run += 1
                else:
                    if run >= 5:
                        score += 3 + (run - 5)
                    run, prev = 1, v
            if run >= 5:
                score += 3 + (run - 5)
            padded = [False] * 4 + list(line) + [False] * 4
            for i in range(len(padded) - 6):
                if tuple(padded[i:i + 7]) == finder:
                    before = not any(padded[max(0, i - 4):i]) and i >= 4
                    after = not any(padded[i + 7:i + 11]) and i + 11 <= len(padded)
                    if before or after:
                        score += 40
        for y in range(n - 1):
            for x in range(n - 1):
                c = m[y][x]
                if c == m[y][x + 1] == m[y + 1][x] == m[y + 1][x + 1]:
                    score += 3
        dark = sum(sum(1 for v in row if v) for row in m)
        total = n * n
        k = (abs(dark * 20 - total * 10) + total - 1) // total - 1
        score += max(k, 0) * 10
        return score


def encode(text: str, ecl: str = "M") -> list[list[bool]]:
    """把一段文字编成二维码模块矩阵（外面没留白，画的时候自己留 4 格）。太长（超过版本 10）抛 ValueError。"""
    data = text.encode("utf-8")
    ver = next((v for v in range(1, MAX_VERSION + 1)
                if 4 + (8 if v <= 9 else 16) + len(data) * 8 <= _data_codewords(v, ecl) * 8), None)
    if ver is None:
        raise ValueError("内容太长，二维码装不下")
    bits: list[int] = []

    def put(val: int, n: int) -> None:
        bits.extend((val >> i) & 1 for i in reversed(range(n)))

    put(0b0100, 4)
    put(len(data), 8 if ver <= 9 else 16)
    for b in data:
        put(b, 8)
    cap = _data_codewords(ver, ecl) * 8
    put(0, min(4, cap - len(bits)))
    put(0, (8 - len(bits) % 8) % 8)
    pad = 0xEC
    while len(bits) < cap:
        put(pad, 8)
        pad ^= 0xEC ^ 0x11
    codewords = [int("".join(map(str, bits[i:i + 8])), 2) for i in range(0, len(bits), 8)]
    allcw = _with_ecc(codewords, ver, ecl)

    best: _Grid | None = None
    best_score = 0
    for mask in range(8):
        g = _Grid(ver)
        g.draw_functions()
        g.draw_codewords(allcw)
        g.apply_mask(mask)
        g.draw_format(mask, ecl)
        s = g.penalty()
        if best is None or s < best_score:
            best, best_score = g, s
    assert best is not None
    return best.m


def rows(text: str, ecl: str = "M") -> list[str]:
    """矩阵写成一行一个字符串（1 深 0 浅），接口里给前端。"""
    return ["".join("1" if v else "0" for v in row) for row in encode(text, ecl)]
