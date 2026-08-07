"""
验证所有配置是否就绪，完成后发送一条测试 Lark 消息。
在 GitHub Actions 中运行：Actions → ✅ Check Setup → Run workflow
"""

from __future__ import annotations

import os
import sys
from datetime import datetime

import yaml
from dotenv import load_dotenv

from ai_dispatch.lark_notify import send_report_as_doc
from ai_dispatch.llm import DEFAULT_MODEL, api_key_configured, ping
from ai_dispatch.paths import CONFIG_PATH, ENV_PATH
from ai_dispatch.send_lark_message import lark_configured

OK = "✅"
FAIL = "❌"


def check(errors: list[str], label: str, ok: bool, detail: str = "") -> bool:
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


def main() -> int:
    load_dotenv(ENV_PATH)
    errors: list[str] = []

    section("GitHub Secrets")
    required_secrets = {
        "DEEPSEEK_API_KEY": os.getenv("DEEPSEEK_API_KEY"),
        "LARK_APP_ID": os.getenv("LARK_APP_ID"),
        "LARK_SECRET": os.getenv("LARK_SECRET"),
        "LARK_RECEIVER": os.getenv("LARK_RECEIVER"),
        "LARK_FOLDER_TOKEN": os.getenv("LARK_FOLDER_TOKEN"),
    }
    for name, value in required_secrets.items():
        check(
            errors,
            name,
            bool(value),
            "已设置" if value else "未找到，请在 Settings → Secrets 中添加",
        )

    section("config.yml")
    cfg = None
    if check(errors, "config.yml 存在", CONFIG_PATH.exists()):
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                cfg = yaml.safe_load(f)
            check(errors, "YAML 格式正确", True)
            check(
                errors,
                "topics 已配置",
                bool(cfg.get("topics")),
                f"{len(cfg.get('topics', []))} 个主题",
            )
            check(
                errors,
                "news_feeds 已配置",
                bool(cfg.get("news_feeds")),
                f"{len(cfg.get('news_feeds', {}))} 个来源",
            )
            check(
                errors,
                "blog_feeds 已配置",
                bool(cfg.get("blog_feeds")),
                f"{len(cfg.get('blog_feeds', {}))} 个博客",
            )
            classics = cfg.get("classics") or []
            check(
                errors,
                "classics 已配置",
                True,
                f"{len(classics)} 篇（0 篇也可以，此项可选）",
            )
        except Exception as e:
            check(errors, "YAML 格式正确", False, str(e))

    section("DeepSeek API")
    model = cfg["digest"]["model"] if cfg else DEFAULT_MODEL
    if api_key_configured():
        try:
            ping(model=model)
            check(errors, f"API 连接成功 ({model})", True)
        except Exception as e:
            check(errors, "API 连接", False, str(e))
    else:
        check(errors, "API 连接（跳过，DEEPSEEK_API_KEY 未设置）", False)

    section("Lark")
    all_ok = not errors
    if not lark_configured():
        check(
            errors,
            "Lark 配置完整",
            False,
            "需设置 LARK_APP_ID、LARK_SECRET、LARK_RECEIVER、LARK_FOLDER_TOKEN",
        )
    else:
        check(errors, "Lark 配置完整", True)
        if all_ok and cfg:
            try:
                now = datetime.now().strftime("%Y-%m-%d %H:%M UTC")
                markdown = (
                    f"# AI Dispatch — 配置验证成功\n\n"
                    f"验证时间：{now}\n\n"
                    f"- 新闻来源：{len(cfg.get('news_feeds', {}))} 个\n"
                    f"- 博客订阅：{len(cfg.get('blog_feeds', {}))} 个\n"
                )
                ok_send = send_report_as_doc(
                    title="配置验证",
                    markdown=markdown,
                    summary="AI Dispatch — 配置验证成功",
                )
                check(errors, "测试 Lark 文档通知已发送", ok_send)
            except Exception as e:
                check(errors, "发送测试 Lark 消息", False, str(e))
        else:
            print("    存在配置错误，跳过发送测试 Lark 消息")

    print("\n" + "═" * 54)
    if not errors:
        print("   所有检查通过！查收 Lark 测试消息后即可等待每日简报。")
    else:
        print(f"   {len(errors)} 项需要修复：")
        for item in errors:
            print(f"       · {item}")
        print("\n  参考 README.md 完成配置后重新运行此检查。")
    print("═" * 54)

    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
