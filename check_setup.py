"""
验证所有配置是否就绪，完成后发送一条测试 Lark 消息。
在 GitHub Actions 中运行：Actions → ✅ Check Setup → Run workflow
"""
import os
import sys
from datetime import datetime
from pathlib import Path

import yaml

from llm import DEFAULT_MODEL, api_key_configured, ping
from send_lark_message import build_interactive_card, lark_configured, send_message

OK = "✅"
FAIL = "❌"
errors = []


def check(label: str, ok: bool, detail: str = "") -> bool:
    status = OK if ok else FAIL
    line = f"  {status}  {label}"
    if detail:
        line += f"  ({detail})"
    print(line)
    if not ok:
        errors.append(label)
    return ok


def section(title: str) -> None:
    print(f"\n── {title} {'─' * (50 - len(title))}")


# ── 0. 读取 config.yml ───────────────────────────
config_path = Path(__file__).parent / "config.yml"
_cfg_raw = (
    yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if config_path.exists()
    else {}
)

# ── 1. 环境变量 ──────────────────────────────────
section("GitHub Secrets")
required_secrets = {
    "DEEPSEEK_API_KEY": os.getenv("DEEPSEEK_API_KEY"),
    "LARK_APP_ID": os.getenv("LARK_APP_ID"),
    "LARK_SECRET": os.getenv("LARK_SECRET"),
    "LARK_RECEIVER": os.getenv("LARK_RECEIVER"),
}
for name, value in required_secrets.items():
    check(name, bool(value), "已设置" if value else "未找到，请在 Settings → Secrets 中添加")

# ── 2. config.yml ────────────────────────────────
section("config.yml")
cfg = None
if check("config.yml 存在", config_path.exists()):
    try:
        with open(config_path, encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        check("YAML 格式正确", True)
        check("topics 已配置", bool(cfg.get("topics")),
              f"{len(cfg.get('topics', []))} 个主题")
        check("news_feeds 已配置", bool(cfg.get("news_feeds")),
              f"{len(cfg.get('news_feeds', {}))} 个来源")
        check("blog_feeds 已配置", bool(cfg.get("blog_feeds")),
              f"{len(cfg.get('blog_feeds', {}))} 个博客")
        classics = cfg.get("classics") or []
        check("classics 已配置", True,
              f"{len(classics)} 篇（0 篇也可以，此项可选）")
    except Exception as e:
        check("YAML 格式正确", False, str(e))

# ── 3. DeepSeek API ──────────────────────────────
section("DeepSeek API")
model = cfg["digest"]["model"] if cfg else DEFAULT_MODEL
if api_key_configured():
    try:
        ping(model=model)
        check(f"API 连接成功 ({model})", True)
    except Exception as e:
        check("API 连接", False, str(e))
else:
    check("API 连接（跳过，DEEPSEEK_API_KEY 未设置）", False)

# ── 4. Lark ──────────────────────────────────────
section("Lark")
all_ok = not errors
if not lark_configured():
    check("Lark 配置完整", False, "需设置 LARK_APP_ID、LARK_SECRET、LARK_RECEIVER")
else:
    check("Lark 配置完整", True)
    if all_ok and cfg:
        try:
            now = datetime.now().strftime("%Y-%m-%d %H:%M UTC")
            card = build_interactive_card(
                title="✅ AI Dispatch — 配置验证成功",
                fields=[
                    {"is_short": False, "content": f"环境已就绪，每日简报将发送到 Lark。\n\n验证时间：{now}"},
                    {"is_short": True, "content": f"**新闻来源**\n{len(cfg.get('news_feeds', {}))} 个"},
                    {"is_short": True, "content": f"**博客订阅**\n{len(cfg.get('blog_feeds', {}))} 个"},
                ],
                template="green",
            )
            ok_send = send_message(
                receive_id=os.environ["LARK_RECEIVER"],
                content=card,
                msg_type="interactive",
            )
            check("测试 Lark 消息已发送", ok_send)
        except Exception as e:
            check("发送测试 Lark 消息", False, str(e))
    else:
        print("  ⚠️  存在配置错误，跳过发送测试 Lark 消息")

# ── 结果汇总 ─────────────────────────────────────
print("\n" + "═" * 54)
if not errors:
    print("  🎉  所有检查通过！查收 Lark 测试消息后即可等待每日简报。")
else:
    print(f"  ❌  {len(errors)} 项需要修复：")
    for e in errors:
        print(f"       · {e}")
    print("\n  参考 README.md 完成配置后重新运行此检查。")
print("═" * 54)

sys.exit(0 if not errors else 1)
