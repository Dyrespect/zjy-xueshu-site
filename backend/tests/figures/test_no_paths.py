"""原图路径不出现在任何接口返回里（check.py 第 6 条的运行时那一半）：真调一遍图库的每个接口，看返回的字。"""

import re

from tests.conftest import TEST_PASSWORD
from tests.figures.conftest import first_id_of, needs_engine, tiny_png

pytestmark = needs_engine

LEAKS = re.compile(r"资料/调研|补收_2026|/Users/|学术汇报|\.(png|jpe?g)\b|[A-Z]_[A-Z]_\d{4}", re.I)


def _assert_clean(text: str, where: str) -> None:
    m = LEAKS.search(text)
    assert m is None, f"{where} 的返回里有像文件路径的东西：{text[max(0, m.start() - 60) : m.end() + 60]!r}"


def test_public_and_admin_responses_have_no_paths(fclient, engine, settings):
    fid = first_id_of(engine, "W2")
    fclient.post("/api/figures/requests", data={"want": "x"}, files={"sketch": ("我的草图.png", tiny_png(), "image/png")})
    fclient.post(
        "/api/figures/submissions", data={"source": "10.1/x"}, files={"image": ("投稿.jpg", tiny_png(), "image/png")}
    )
    fclient.post(f"/api/figures/{fid}/feedback", json={"reason": "other"})
    search = fclient.get("/api/figures/search", params={"q": "被试内实验的试次流程"})
    urls = [
        "/api/figures/site",
        "/api/figures/home",
        "/api/figures/search?q=功能性近红外 fNIRS 的光极排布图",
        "/api/figures/types/D2",
        f"/api/figures/{fid}",
        f"/api/figures/{fid}/similar",
    ]
    _assert_clean(search.text, "/api/figures/search")
    for u in urls:
        r = fclient.get(u)
        assert r.status_code == 200, u
        _assert_clean(r.text, u)

    # 每张图的详情都过一遍（出处、图注里也不能带路径）
    for d in engine.docs[:300]:
        _assert_clean(fclient.get(f"/api/figures/{d['号']}").text, f"/api/figures/{d['号']}")

    fclient.post("/api/auth/login", json={"password": TEST_PASSWORD})
    for kind in ("feedback", "requests", "submissions", "site"):
        r = fclient.get(f"/api/admin/figures/inbox/{kind}")
        assert r.status_code == 200
        _assert_clean(r.text, f"/api/admin/figures/inbox/{kind}")
        assert "figures/requests/" not in r.text and "figures/submissions/2" not in r.text
    _assert_clean(fclient.get("/api/admin/figures/stats").text, "/api/admin/figures/stats")
