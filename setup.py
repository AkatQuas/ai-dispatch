#!/usr/bin/env python3
"""
AI Dispatch — 交互式配置向导
运行方式：uv run python setup.py
完成后所有 GitHub Secrets 自动写入，config.yml 同步更新，无需手动操作。
"""

import getpass
import re
import subprocess
import sys
from pathlib import Path

# ── 颜色输出 ────────────────────────────────────────────────────────────────


def green(s):
    return f"\033[32m{s}\033[0m"


def yellow(s):
    return f"\033[33m{s}\033[0m"


def red(s):
    return f"\033[31m{s}\033[0m"


def bold(s):
    return f"\033[1m{s}\033[0m"


def dim(s):
    return f"\033[2m{s}\033[0m"


def ok(msg):
    print(f"  {green('✓')}  {msg}")


def warn(msg):
    print(f"  {yellow('!')}  {msg}")


def fail(msg):
    print(f"  {red('✗')}  {msg}")


def section(title):
    print(f"\n{bold('── ' + title + ' ' + '─' * max(0, 48 - len(title)))}")


# ── 工具函数 ─────────────────────────────────────────────────────────────────


def ask(prompt, default=None, secret=False):
    hint = f" [{dim(default)}]" if default else ""
    full_prompt = f"  {prompt}{hint}: "
    while True:
        val = (getpass.getpass(full_prompt) if secret else input(full_prompt)).strip()
        if val:
            return val
        if default is not None:
            return default
        print(f"  {red('请输入内容')}")


def ask_optional(prompt, secret=False):
    hint = f" [{dim('留空跳过')}]"
    full_prompt = f"  {prompt}{hint}: "
    return (getpass.getpass(full_prompt) if secret else input(full_prompt)).strip()


def collect_langfuse_config() -> dict[str, str]:
    section("Langfuse 追踪（可选）")
    print(dim("  在 https://langfuse.com/cloud 创建项目并获取 API Keys"))
    print(dim("  留空跳过；需同时填写 PUBLIC_KEY 和 SECRET_KEY 才会启用"))

    public_key = ask_optional("LANGFUSE_PUBLIC_KEY")
    secret_key = ask_optional("LANGFUSE_SECRET_KEY", secret=True) if public_key else ""
    if not public_key and not secret_key:
        return {}
    if not (public_key and secret_key):
        warn("Langfuse 需要同时设置 PUBLIC_KEY 和 SECRET_KEY，已跳过")
        return {}

    base_url = ask("LANGFUSE_BASE_URL", default="https://cloud.langfuse.com")
    config = {
        "LANGFUSE_PUBLIC_KEY": public_key,
        "LANGFUSE_SECRET_KEY": secret_key,
        "LANGFUSE_BASE_URL": base_url,
    }
    ok("Langfuse 追踪已配置")
    return config


def ask_choice(prompt, choices):
    """显示编号菜单，返回选中的值。"""
    print(f"\n  {prompt}")
    for i, (label, desc) in enumerate(choices, 1):
        print(f"    {bold(str(i))}.  {label}  {dim(desc)}")
    while True:
        raw = input(f"  选择 [1-{len(choices)}]: ").strip()
        if raw.isdigit() and 1 <= int(raw) <= len(choices):
            return choices[int(raw) - 1][0]
        print(f"  {red('请输入有效编号')}")


def run(cmd: list[str], capture=True):
    return subprocess.run(cmd, capture_output=capture, text=True)


def get_repo_slug():
    """从 git remote 解析 owner/repo。"""
    r = run(["git", "remote", "get-url", "origin"])
    url = r.stdout.strip()
    m = re.search(r"[:/]([^/]+/[^/]+?)(?:\.git)?$", url)
    return m.group(1) if m else None


def set_secret(repo: str, name: str, value: str) -> bool:
    r = run(["gh", "secret", "set", name, "--repo", repo, "--body", value])
    return r.returncode == 0


# ── 主流程 ───────────────────────────────────────────────────────────────────


def main():
    print()
    print(bold("   AI Dispatch 配置向导"))
    print(dim("  ─────────────────────────────────────────────"))
    print(dim("  回答以下问题，向导将自动完成全部配置。"))
    print(dim("  密码输入时不显示字符，直接回车接受 [默认值]。"))

    # ── 检查依赖 ──────────────────────────────────────────────────────────
    section("环境检查")

    if run(["git", "rev-parse", "--is-inside-work-tree"]).returncode != 0:
        fail("请在 ai-dispatch 仓库目录内运行此脚本")
        sys.exit(1)
    ok("Git 仓库")

    repo = get_repo_slug()
    if not repo:
        fail("无法解析 GitHub 仓库地址，请确认 origin remote 已设置")
        sys.exit(1)
    ok(f"仓库：{repo}")

    if run(["gh", "--version"]).returncode != 0:
        fail("未检测到 GitHub CLI")
        print()
        print(f"  请先安装 gh：{bold('https://cli.github.com')}")
        print(f"  macOS:   {dim('brew install gh')}")
        print(f"  Windows: {dim('winget install GitHub.cli')}")
        print(f"  Linux:   {dim('sudo apt install gh  # 或参考上方链接')}")
        print()
        sys.exit(1)

    if run(["gh", "auth", "status"]).returncode != 0:
        fail("GitHub CLI 未登录")
        print()
        print(f"  请运行：{bold('gh auth login')}，按提示完成授权后重新运行此向导。")
        print()
        sys.exit(1)
    ok("GitHub CLI 已认证")

    # ── DeepSeek ───────────────────────────────────────────────────────────
    section("DeepSeek API")
    print(dim("  申请 API Key：https://platform.deepseek.com/api_keys"))
    api_key = ask("粘贴你的 DEEPSEEK_API_KEY", secret=True)
    default_model = ask("模型名称", default="deepseek-v4-flash")

    # ── Lark ─────────────────────────────────────────────────────────────
    section("Lark 配置")
    print(dim("  在飞书开放平台创建应用：https://open.feishu.cn/app"))
    print(dim("  需开通 im:message、docx:document 权限，receive_id 为接收人的 union_id"))
    print(dim("  LARK_FOLDER_TOKEN 见 docs/lark-doc.md"))
    lark_app_id = ask("LARK_APP_ID")
    lark_secret = ask("LARK_SECRET", secret=True)
    lark_folder_token = ask("LARK_FOLDER_TOKEN（云文档文件夹 token）")
    lark_union_id = ask("LARK_RECEIVER（接收人 union_id）")

    # ── 输出语言 ───────────────────────────────────────────────────────────
    section("简报语言")
    lang = ask_choice(
        "摘要输出语言？",
        [
            ("English", "默认"),
            ("中文", "中文输出"),
        ],
    )

    # ── Langfuse（可选）────────────────────────────────────────────────────
    langfuse_config = collect_langfuse_config()

    # ── 写入 GitHub Secrets ────────────────────────────────────────────────
    section("写入 GitHub Secrets")
    secrets = {
        "DEEPSEEK_API_KEY": api_key,
        "LARK_APP_ID": lark_app_id,
        "LARK_SECRET": lark_secret,
        "LARK_FOLDER_TOKEN": lark_folder_token,
        "LARK_RECEIVER": lark_union_id,
        **langfuse_config,
    }
    all_ok = True
    for name, value in secrets.items():
        if set_secret(repo, name, value):
            ok(name)
        else:
            fail(f"{name}  （写入失败，请检查 gh 权限）")
            all_ok = False

    if not all_ok:
        warn("部分 Secret 写入失败，可手动在 Settings → Secrets → Actions 中补充")

    # ── 更新 config.yml ────────────────────────────────────────────────────
    section("更新 config.yml")
    config_path = Path(__file__).parent / "config.yml"
    raw = config_path.read_text(encoding="utf-8")

    # model
    raw = re.sub(r"^(\s+model:\s*)\S+", f"\\g<1>{default_model}", raw, flags=re.MULTILINE)
    # output_language
    raw = re.sub(r"^(\s+output_language:\s*)\S+", f"\\g<1>{lang}", raw, flags=re.MULTILINE)

    config_path.write_text(raw, encoding="utf-8")
    ok(f"model={default_model}, language={lang}")

    # ── Commit & Push ──────────────────────────────────────────────────────
    section("提交配置")
    has_changes = run(["git", "diff", "--quiet", "config.yml"]).returncode != 0
    if has_changes:
        do_commit = ask_choice(
            "config.yml 已更新，是否提交并推送到 GitHub？",
            [("yes", "推荐"), ("no", "稍后手动 commit")],
        )
        if do_commit == "yes":
            run(["git", "add", "config.yml"], capture=False)
            run(["git", "commit", "-m", "chore: apply setup wizard config"], capture=False)
            r = run(["git", "push"])
            if r.returncode == 0:
                ok("已推送到 GitHub")
            else:
                warn("推送失败，请手动运行 git push")
    else:
        ok("config.yml 无变化，跳过提交")

    # ──  验证（可选）──────────────────────────────────────────────────────
    section("完成")
    print(f"""
  {green("✓")}  配置完成！

  下一步（可选）：

    1. 在 GitHub Actions 手动触发一次验证：
       {bold("Actions → Check Setup → Run workflow")}

    2. 手动发送今天的简报测试效果：
       {bold("Actions → AI Dispatch → Run workflow")}

  每天会自动推送到 Lark（发送时间见 .github/workflows/daily_news.yml 中的 cron）。
""")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n\n  {yellow('已取消')}\n")
        sys.exit(0)
