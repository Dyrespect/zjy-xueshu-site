"""后台激活码页的接口：按货号生成（code.issue 节点）、按发卡站格式下载 CSV（一个货号一个文件）、列表、作废；没有认领接口。"""

from __future__ import annotations

from urllib.parse import unquote

import pytest
from fastapi.testclient import TestClient

from tests.conftest import TEST_PASSWORD
from tests.intake.helpers import make_app


@pytest.fixture
def c(settings, notifier, tmp_path):
    app = make_app(settings, notifier, tmp_path)
    with TestClient(app) as client:
        client.post("/api/auth/login", json={"password": TEST_PASSWORD})
        yield client


def test_generate_export_list_void(c):
    r = c.post("/api/admin/intake/codes/generate", json={"sku": "regular-p1", "count": 5, "note": "发卡站第一批"}).json()
    assert r["count"] == 5 and r["batch"].endswith("-1") and all(x.startswith("PSY-") for x in r["codes"])
    r2 = c.post("/api/admin/intake/codes/generate", json={"sku": "addon-rush", "count": 2, "platform": "xy",
                                                         "expires_on": "2099-12-31"}).json()
    assert r2["batch"].endswith("-2")
    assert c.post("/api/admin/intake/codes/generate", json={"sku": "light-p4_5", "count": 1}).status_code == 400  # 不开放
    assert c.post("/api/admin/intake/codes/generate", json={"sku": "nope", "count": 1}).status_code == 400
    assert c.post("/api/admin/intake/codes/generate", json={"sku": "regular-p1", "count": 0}).status_code == 422
    assert c.post("/api/admin/intake/codes/generate", json={"sku": "regular-p1", "count": 1, "expires_on": "2020-01-01"}).status_code == 400

    # 发卡站 Dujiao-Next 的导入格式：表头一列 secret，下面一行一个码；一个货号一个文件
    e = c.get("/api/admin/intake/codes/export.csv", params={"batch": r["batch"]})
    assert e.status_code == 200 and e.headers["content-type"].startswith("text/csv")
    assert e.content.decode("utf-8").splitlines() == ["secret", *r["codes"]] and not e.content.startswith(b"\xef\xbb\xbf")
    assert unquote(e.headers["content-disposition"].split("''", 1)[1]) == f"激活码_常规1篇_{r['batch']}.csv"
    e = c.get("/api/admin/intake/codes/export.csv", params={"sku": "addon-rush"})
    assert e.content.decode().splitlines()[1:] == r2["codes"] and "加购加急" in unquote(e.headers["content-disposition"])
    assert c.get("/api/admin/intake/codes/export.csv").status_code == 400
    assert c.get("/api/admin/intake/codes/export.csv", params={"batch": r["batch"], "sku": "long-p1"}).status_code == 400

    d = c.get("/api/admin/intake/codes").json()
    assert d["counts"] == {"unused": 7, "used": 0, "void": 0}
    names = {x["sku"]: x for x in d["skus"]}
    assert names["regular-p1"]["name"] == "常规 · 1 篇" and names["regular-p1"]["price"] == "29.9" and "light-p4_5" not in names
    assert names["addon-find_refs"]["kind"] == "addon"
    row = next(x for x in d["rows"] if x["code"] == r["codes"][0])
    assert (row["sku_name"], row["status_label"], row["note"], row["platform"]) == ("常规 · 1 篇", "没用", "发卡站第一批", "fk")
    assert c.get("/api/admin/intake/codes", params={"sku": "addon-rush"}).json()["rows"][0]["platform"] == "xy"
    assert c.get("/api/admin/intake/codes", params={"q": r["codes"][0].lower()}).json()["rows"][0]["code"] == r["codes"][0]

    v = c.post(f"/api/admin/intake/codes/{row['id']}/void").json()
    assert v["status"] == "void"
    assert c.post(f"/api/admin/intake/codes/{row['id']}/void").status_code == 409
    assert r["codes"][0] not in c.get("/api/admin/intake/codes/export.csv", params={"batch": r["batch"]}).text
    assert c.post("/api/admin/intake/codes/redeem", json={"code": r["codes"][1]}).status_code in (404, 405)  # 后台不能核销
