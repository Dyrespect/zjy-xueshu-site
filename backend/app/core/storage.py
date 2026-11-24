"""存文件的接口。业务代码只认 `Storage`，不直接拼本地路径。

- `LocalStorage`（STORAGE_BACKEND=local，现在）：存到 `DATA_DIR/files/` 下，返回相对路径（库里存这个相对路径）。
  根目录单独一层 files/，是为了 delete 再怎么写错也碰不到库文件 app.db。
- `CosStorage`（STORAGE_BACKEND=cos，百人档起）：腾讯云 COS 私有桶，用官方 SDK cos-python-sdk-v5（MIT）；
  对象键 = COS_PREFIX + 同样的相对路径，所以本地的文件原样传上去、库里的路径不用改。多台网站机器共用一个桶。
业务代码只认 `Storage` 的这几个方法，换后端只改配置。下载现在一律经应用校验归属后返回（桶保持私有）；
以后大文件要省流量，可以用 `signed_url` 给一个几分钟有效的签名链接（本地实现返回 None = 走应用下载）。

相对路径只给后端自己用，不许出现在对外接口的返回里（scripts/check.py 第 6 条）。
对外给的是缩略图 / 预览图 / 签名下载的网址。
"""

from __future__ import annotations

import re
import tempfile
import uuid
from abc import ABC, abstractmethod
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO
from urllib.parse import quote, urlsplit

from app.core.config import Settings

_UNSAFE = re.compile(r"[^\w.\-一-鿿]+")


class StorageError(Exception):
    pass


def _safe_filename(name: str) -> str:
    """去掉目录和怪字符，保留中文、字母数字、点、横线、下划线。"""
    base = PurePosixPath(name.replace("\\", "/")).name
    base = _UNSAFE.sub("_", base).strip("._")
    return base[:120] or "file"


def _safe_folder(folder: str) -> PurePosixPath:
    parts = [p for p in PurePosixPath(folder.replace("\\", "/")).parts if p not in ("", "/", ".")]
    if any(p == ".." for p in parts):
        raise StorageError(f"目录里不许有 ..：{folder!r}")
    return PurePosixPath(*parts) if parts else PurePosixPath()


def _new_rel(folder: str, filename: str) -> str:
    sub = _safe_folder(folder)
    name = f"{uuid.uuid4().hex[:8]}_{_safe_filename(filename)}"
    return str(sub / name) if str(sub) != "." else name


def _check_rel(rel_path: str) -> None:
    if not rel_path or rel_path.startswith("/") or "\\" in rel_path or ".." in PurePosixPath(rel_path).parts:
        raise StorageError(f"不是合法的相对路径：{rel_path!r}")


class Storage(ABC):
    @abstractmethod
    def save(self, data: bytes | BinaryIO, *, folder: str, filename: str) -> str:
        """存一个文件，返回相对路径（如 `uploads/2026-11/ab12cd_论文.pdf`）。同名不覆盖。"""

    @abstractmethod
    def open(self, rel_path: str) -> BinaryIO:
        """以二进制只读打开。调用方负责关闭。"""

    @abstractmethod
    def read_bytes(self, rel_path: str) -> bytes: ...

    @abstractmethod
    def exists(self, rel_path: str) -> bool: ...

    @abstractmethod
    def delete(self, rel_path: str) -> bool:
        """删掉返回 True，本来就没有返回 False。"""

    def signed_url(self, rel_path: str, *, expires: int = 600, filename: str = "") -> str | None:
        """几分钟有效的直接下载链接；返回 None 表示这个后端没有，调用方走应用下载（先校验归属再 read_bytes）。"""
        return None


class LocalStorage(Storage):
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def local_path(self, rel_path: str) -> Path:
        """相对路径 -> 本机绝对路径（只有本地实现有；要用 Pillow 处理、拷进工厂 inbox 时用）。"""
        if not rel_path or rel_path.startswith("/") or "\\" in rel_path:
            raise StorageError(f"不是合法的相对路径：{rel_path!r}")
        p = (self.root / rel_path).resolve()
        if p != self.root and self.root not in p.parents:
            raise StorageError(f"路径跑出了数据目录：{rel_path!r}")
        return p

    def save(self, data: bytes | BinaryIO, *, folder: str, filename: str) -> str:
        rel = _new_rel(folder, filename)
        target = self.local_path(rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "xb") as f:  # x：已存在就报错，绝不覆盖
            if isinstance(data, (bytes, bytearray)):
                f.write(data)
            else:
                while chunk := data.read(1024 * 1024):
                    f.write(chunk)
        return rel

    def open(self, rel_path: str) -> BinaryIO:
        p = self.local_path(rel_path)
        if not p.is_file():
            raise FileNotFoundError(rel_path)
        return open(p, "rb")

    def read_bytes(self, rel_path: str) -> bytes:
        with self.open(rel_path) as f:
            return f.read()

    def exists(self, rel_path: str) -> bool:
        return self.local_path(rel_path).is_file()

    def delete(self, rel_path: str) -> bool:
        p = self.local_path(rel_path)
        if not p.is_file():
            return False
        p.unlink()
        return True


class CosStorage(Storage):
    """腾讯云 COS 私有桶（官方 SDK）。注意 chuzhen-us 那边的桶是公开读的：客户文件要用私有桶，或私有前缀加桶策略。"""

    def __init__(self, *, bucket: str, region: str, secret_id: str, secret_key: str, prefix: str = "",
                 endpoint: str = "", timeout: int = 60, client: Any = None) -> None:
        from qcloud_cos import CosConfig, CosS3Client

        self.bucket = bucket
        self.prefix = (prefix.strip("/") + "/") if prefix.strip("/") else ""
        if client is None:
            kw: dict[str, Any] = dict(Region=region, SecretId=secret_id, SecretKey=secret_key, Timeout=timeout)
            if endpoint:  # 自定义域名或测试用的假服务：http://127.0.0.1:9000
                u = urlsplit(endpoint if "://" in endpoint else f"https://{endpoint}")
                kw.update(Scheme=u.scheme or "https", Domain=u.netloc)
            else:
                kw["Scheme"] = "https"
            client = CosS3Client(CosConfig(**kw))
        self.client = client

    def key(self, rel_path: str) -> str:
        _check_rel(rel_path)
        return self.prefix + rel_path

    def _missing(self, e: Exception) -> bool:
        from qcloud_cos.cos_exception import CosServiceError

        return isinstance(e, CosServiceError) and (e.get_status_code() == 404 or e.get_error_code() in ("NoSuchKey", "NoSuchResource"))

    def save(self, data: bytes | BinaryIO, *, folder: str, filename: str) -> str:
        rel = _new_rel(folder, filename)  # 名字里有随机串，不会撞到已有的（跟本地一样不覆盖）
        body = bytes(data) if isinstance(data, (bytes, bytearray)) else data
        self.client.put_object(Bucket=self.bucket, Body=body, Key=self.key(rel))
        return rel

    def read_bytes(self, rel_path: str) -> bytes:
        try:
            resp = self.client.get_object(Bucket=self.bucket, Key=self.key(rel_path))
        except Exception as e:
            if self._missing(e):
                raise FileNotFoundError(rel_path) from e
            raise
        return resp["Body"].get_raw_stream().read()

    def open(self, rel_path: str) -> BinaryIO:
        """下到一个临时文件（8MB 以内在内存）再给出去；调用方负责关闭。"""
        try:
            resp = self.client.get_object(Bucket=self.bucket, Key=self.key(rel_path))
        except Exception as e:
            if self._missing(e):
                raise FileNotFoundError(rel_path) from e
            raise
        tmp = tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024)
        raw = resp["Body"].get_raw_stream()
        while chunk := raw.read(1024 * 1024):
            tmp.write(chunk)
        tmp.seek(0)
        return tmp  # type: ignore[return-value]

    def exists(self, rel_path: str) -> bool:
        return bool(self.client.object_exists(Bucket=self.bucket, Key=self.key(rel_path)))

    def delete(self, rel_path: str) -> bool:
        if not self.exists(rel_path):
            return False
        self.client.delete_object(Bucket=self.bucket, Key=self.key(rel_path))
        return True

    def signed_url(self, rel_path: str, *, expires: int = 600, filename: str = "") -> str | None:
        params = {"response-content-disposition": f"attachment; filename*=UTF-8''{quote(filename)}"} if filename else {}
        return self.client.get_presigned_download_url(Bucket=self.bucket, Key=self.key(rel_path), Expired=expires,
                                                      Params=params)


ObjectStorage = CosStorage  # 老名字


def build_storage(settings: Settings) -> Storage:
    if settings.STORAGE_BACKEND == "local":
        return LocalStorage(settings.DATA_DIR / "files")
    if settings.STORAGE_BACKEND == "cos":
        return CosStorage(bucket=settings.COS_BUCKET, region=settings.COS_REGION, prefix=settings.COS_PREFIX,
                          secret_id=settings.COS_SECRET_ID.get_secret_value(),
                          secret_key=settings.COS_SECRET_KEY.get_secret_value(), endpoint=settings.COS_ENDPOINT)
    raise StorageError(f"未知的 STORAGE_BACKEND：{settings.STORAGE_BACKEND}")
