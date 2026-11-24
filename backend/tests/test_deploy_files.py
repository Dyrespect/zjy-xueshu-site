"""部署包（deploy/）：上线前检查对一份好的、一份坏的 .env 的输出；服务器锁文件和主锁文件同一套版本；compose 的关键几项。"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DEPLOY = REPO / "deploy"


def _load_check():
    spec = importlib.util.spec_from_file_location("deploy_precheck", DEPLOY / "上线前检查.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["deploy_precheck"] = mod
    spec.loader.exec_module(mod)
    return mod


pre = _load_check()

GOOD = """# 服务器上的 .env（测试用的假值；第一阶段：不收款、助手关着）
APP_ENV=prod
PUBLIC_BASE_URL=https://psyppt.pilipala.zj.cn
TRUST_PROXY_HEADERS=true
LOG_LEVEL=INFO
ADMIN_PASSWORD=Kq7-mZ2pXw9_rT4vLc8n
SESSION_SECRET=0123456789abcdef0123456789abcdef0123
HANDOFF_MODE=pull
FACTORY_PULL_TOKEN="pull-0123456789abcdef0123456789abcdef"
PRODUCTION_TOKEN=prod-token-for-deploy-test-0123456789abcd
FIGURE_ASSET_BASE=https://psyppt.pilipala.zj.cn/figure-assets
FIGURE_ENGINE_PATH=/app/bundle/engine/脚本
FIGURE_SOURCES=/app/bundle/engine/出处.json
SHOP_METHODS=
SHOP_FAKE_PAY=false
LLM_BASE_URL=
LLM_MODEL=
LLM_API_KEY=
WECOM_CORPID=
FEISHU_WEBHOOK=https://example.com/hook
"""

BAD = """APP_ENV=dev
PUBLIC_BASE_URL=http://127.0.0.1:8710
LOG_LEVEL=DEBUG
ADMIN_PASSWORD=admin123456789012
SESSION_SECRET=too-short
HANDOFF_MODE=direct
FIGURE_ENGINE_PATH=/Users/edison/Desktop/学术汇报/PPT工厂/skills/科研绘图/脚本
SHOP_METHODS=wechat_native=pay.fake
SHOP_FAKE_PAY=true
LLM_BASE_URL=https://api.anthropic.com/v1
LLM_MODEL=deepseek-chat
WECOM_CORPID=ww123
WECOM_TOKEN=abc
DATA_DIR=/srv/other
"""


def _run(tmp_path, text, capsys, *extra: str, mode: int = 0o600):
    p = tmp_path / "prod.env"
    p.write_text(text, encoding="utf-8")
    p.chmod(mode)
    code = pre.main(["上线前检查.py", str(p), *extra])
    return code, capsys.readouterr().out


def test_good_env_all_pass(tmp_path, capsys):
    data = tmp_path / "data"
    data.mkdir(mode=0o750)
    import os
    code, out = _run(tmp_path, GOOD, capsys, "--data-dir", str(data), "--uid", str(os.getuid()))
    assert code == 0, out
    assert "[×]" not in out and "全过" in out
    for must in ("APP_ENV=prod", "没开调试", "ADMIN_PASSWORD 够强", "SESSION_SECRET 够长", "PUBLIC_BASE_URL 是 https",
                 "TRUST_PROXY_HEADERS=true", "没开假网关", "HANDOFF_MODE=pull", "FACTORY_PULL_TOKEN 已填", "PRODUCTION_TOKEN 已填",
                 "FIGURE_ASSET_BASE=https://psyppt.pilipala.zj.cn/figure-assets", "企业微信五项都空", "飞书通知配了",
                 "第一阶段 mem_limit 合计", "nginx 转发头", ".env 权限 0o600", "数据目录"):
        assert must in out, must
    for warn in ("SHOP_METHODS 空着", "接单助手关着", "noindex 开着"):  # 第一阶段该有的提醒
        assert warn in out, warn
    for secret in ("Kq7-mZ2pXw9_rT4vLc8n", "0123456789abcdef0123456789abcdef0123", "pull-0123456789", "prod-token-for"):
        assert secret not in out  # 不打印密钥


def test_bad_env_lists_what_is_missing(tmp_path, capsys):
    code, out = _run(tmp_path, BAD, capsys, "--data-dir", str(tmp_path / "nope"), mode=0o644)
    assert code == 1
    text = "\n".join(line for line in out.splitlines() if "[×]" in line)
    for must in ("APP_ENV 要写 prod", "生产不许开调试", "ADMIN_PASSWORD 太弱", "SESSION_SECRET 要至少 32 位",
                 "PUBLIC_BASE_URL 要写线上的 https", "TRUST_PROXY_HEADERS 要写 true", "生产不许用假网关",
                 "HANDOFF_MODE 要写 pull", "FACTORY_PULL_TOKEN 没填", "PRODUCTION_TOKEN 没填", "FIGURE_ASSET_BASE 没填",
                 "FIGURE_ENGINE_PATH 要写 /app/bundle/engine/脚本", "不许调 Anthropic", "模型要么三项都空",
                 "企业微信五项要么全空要么全填", "DATA_DIR=/srv/other", "别人能读，chmod 600", "不存在"):
        assert must in text, must
    assert "admin123456789012" not in out


def test_weak_password_rules():
    assert pre.weak_password("Kq7-mZ2pXw9_rT4vLc8n") == ""
    assert "太短" in pre.weak_password("Ab3-short")
    assert "常见词" in pre.weak_password("Password-123456789x")
    assert "一两类" in pre.weak_password("abcdefghijklmnopqrst")


def test_compose_mem_limit_checked(tmp_path, capsys):
    """第一阶段只许一个容器、后台任务合进网站进程、mem_limit 合计不超过 600m；改大了检查要拦。"""
    svcs = pre.parse_compose((DEPLOY / "docker-compose.yml").read_text(encoding="utf-8"))
    phase1 = {n: s for n, s in svcs.items() if not s["profiles"]}
    assert list(phase1) == ["xueshu-platform"]
    assert pre.mem_mb(str(phase1["xueshu-platform"]["mem_limit"])) <= 600
    assert phase1["xueshu-platform"]["env"]["BACKGROUND_IN_WEB"] == "true"
    assert svcs["xueshu-worker"]["profiles"] == ["split"]
    big = (DEPLOY / "docker-compose.yml").read_text(encoding="utf-8").replace("mem_limit: 600m", "mem_limit: 700m", 1)
    (tmp_path / "c.yml").write_text(big, encoding="utf-8")
    code, out = _run(tmp_path, GOOD, capsys, "--compose", str(tmp_path / "c.yml"))
    assert code == 1 and "超过 600 MB" in out


def test_nginx_forwarding_headers_checked(tmp_path, capsys):
    """nginx 模板：客人自带的 CF-Connecting-IP 要清空、X-Forwarded-For 写真实 IP；回滚到静态站只动一行 include。"""
    main = (DEPLOY / "nginx.conf.example").read_text(encoding="utf-8")
    app = (DEPLOY / "nginx" / "app.inc").read_text(encoding="utf-8")
    assert "include /etc/nginx/psyppt/app.inc;" in main and "# include /etc/nginx/psyppt/static.inc;" in main
    assert 'add_header X-Robots-Tag "noindex, nofollow" always;' in main
    assert 'proxy_set_header CF-Connecting-IP "";' in app and "proxy_set_header X-Forwarded-For $remote_addr;" in app
    assert "/var/www/xueshu-platform/figures/" in app and "error_page 502 503 504 /50x.html;" in app
    for line in app.splitlines():  # location 里写 add_header 会让 server 那行 noindex 不再继承
        assert not line.startswith("    add_header"), line
    (tmp_path / "nginx").mkdir()
    (tmp_path / "nginx" / "app.inc").write_text(app.replace('proxy_set_header CF-Connecting-IP "";', ""), encoding="utf-8")
    (tmp_path / "main.conf").write_text(main, encoding="utf-8")
    code, out = _run(tmp_path, GOOD, capsys, "--nginx", str(tmp_path / "main.conf"))
    assert code == 1 and "CF-Connecting-IP" in out


WX_BASE = GOOD.replace("SHOP_METHODS=\n", "SHOP_METHODS=wechat_native=pay.wechat,wechat_jsapi=pay.wechat\n") + """WECHATPAY_MCHID=1900000001
WECHATPAY_APPID=wxtestappid000000
WECHATPAY_CERT_SERIAL=SERIAL
WECHATPAY_PRIVATE_KEY_PATH=/app/secrets/wechatpay/apiclient_key.pem
WECHATPAY_APIV3_KEY=0123456789abcdef0123456789ABCDEF
WECHATPAY_PUBLIC_KEY_ID=PUB_KEY_ID_TEST
WECHATPAY_PUBLIC_KEY_PATH=/app/secrets/wechatpay/pub_key.pem
WECHATPAY_NOTIFY_URL=https://psyppt.pilipala.zj.cn/api/shop/pay/wechat/notify
"""


def test_mobile_wechat_pay_checked(tmp_path, capsys):
    """手机微信支付：开了 wechat_jsapi 没 AppSecret 拦；文件路径、校验文件格式、两处后台的提醒；nginx 不许先拦 *.txt；不打印密钥。"""
    code, out = _run(tmp_path, WX_BASE, capsys)
    assert code == 1 and "开了 wechat_jsapi，但 WECHAT_MP_APPSECRET_FILE / WECHAT_MP_APPSECRET 都没填" in out
    good = WX_BASE + "WECHAT_MP_APPSECRET_FILE=/app/secrets/wechat_mp_appsecret\nWECHAT_MP_VERIFY_FILE=MP_verify_AbC123.txt\n" \
                     "WECHAT_MP_VERIFY_CONTENT=AbC123\n"
    code, out = _run(tmp_path, good, capsys)
    assert "[×]" not in out, out
    for must in ("AppSecret 从文件读", "https://psyppt.pilipala.zj.cn/MP_verify_AbC123.txt", "支付授权目录」= https://psyppt.pilipala.zj.cn/order/pay/",
                 "nginx 没拦 *.txt"):
        assert must in out, must
    code, out = _run(tmp_path, WX_BASE + "WECHAT_MP_APPSECRET=inline-secret-value-0001\nWECHAT_MP_VERIFY_FILE=../x\n", capsys)
    assert code == 1 and "格式不对" in out and "建议放 /root/xueshu-platform/secrets/wechat_mp_appsecret" in out
    assert "inline-secret-value-0001" not in out and "0123456789abcdef0123456789ABCDEF" not in out
    code, out = _run(tmp_path, good.replace("wechat_jsapi=pay.wechat", "wechat_jsapi=pay.wechat,wechat_h5=pay.wechat"), capsys)
    assert "开了微信 H5" in out
    main = (DEPLOY / "nginx.conf.example").read_text(encoding="utf-8")
    app = (DEPLOY / "nginx" / "app.inc").read_text(encoding="utf-8")
    (tmp_path / "nginx").mkdir()
    (tmp_path / "nginx" / "app.inc").write_text(app + "\nlocation ~* \\.txt$ {\n    return 404;\n}\n", encoding="utf-8")
    (tmp_path / "main.conf").write_text(main, encoding="utf-8")
    code, out = _run(tmp_path, good, capsys, "--nginx", str(tmp_path / "main.conf"))
    assert code == 1 and "MP_verify" in out


def _pins(path: Path) -> dict[str, str]:
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^([A-Za-z0-9_.\-\[\]]+)==([^\s;]+)", line)
        if m:
            out[m.group(1).lower()] = m.group(2)
    return out


def test_server_lock_same_versions_as_main_lock():
    """镜像装 deploy/requirements.server.lock（不带测试和 COS 上传的可选依赖），版本必须和开发用的锁文件一样。"""
    server, main = _pins(DEPLOY / "requirements.server.lock"), _pins(REPO / "backend" / "requirements.lock")
    assert server and all(main.get(k) == v for k, v in server.items()), {k: (v, main.get(k)) for k, v in server.items() if main.get(k) != v}
    for dev_only in ("pytest",):  # cos-python-sdk-v5 11-18 起是服务器依赖（STORAGE_BACKEND=cos，底座可扩展）
        assert dev_only in main and dev_only not in server


def test_compose_and_dockerfile_key_settings():
    compose = (DEPLOY / "docker-compose.yml").read_text(encoding="utf-8")
    assert "name: xueshu-platform" in compose and "container_name: xueshu-platform" in compose
    assert '"127.0.0.1:8830:8830"' in compose
    assert "/root/xueshu-platform/data:/app/data" in compose and "/root/xueshu-platform/.env" in compose
    docker = (DEPLOY / "Dockerfile").read_text(encoding="utf-8")
    assert "FROM python:3.11-slim" in docker
    assert "USER app" in docker and "--proxy-headers" in docker and "--workers 1" in docker
    assert ".env" not in [line.split()[1] for line in docker.splitlines() if line.startswith("COPY ")]
    ignore = (DEPLOY / "Dockerfile.dockerignore").read_text(encoding="utf-8")
    assert "\n*\n" in ignore  # 白名单：默认什么都不进
    sync = (DEPLOY / "同步.sh").read_text(encoding="utf-8")
    for must in ("chuzhen-prod", "xueshu-platform:prev", "--no-build xueshu-platform", "自动回滚", "free -m", "df -Pm"):
        assert must in sync, must
    for bad in ("docker compose down", "docker system prune", "docker rm "):  # 不碰别人的容器
        assert bad not in sync, bad
