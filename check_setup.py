"""
验证所有配置是否就绪，完成后发送一封测试邮件。
在 GitHub Actions 中运行：Actions → ✅ Check Setup → Run workflow
"""
import os
import smtplib
import sys
import yaml
from pathlib import Path
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime

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


# ── 0. 读取 config.yml（后续检查需要 provider 信息）──
config_path = Path(__file__).parent / "config.yml"
_cfg_raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
provider = _cfg_raw.get("provider", "anthropic")

# ── 1. 环境变量 ──────────────────────────────────
section("GitHub Secrets")
llm_key_name = "GEMINI_API_KEY" if provider == "gemini" else "ANTHROPIC_API_KEY"
required_secrets = {
    llm_key_name:        os.getenv(llm_key_name),
    "GMAIL_USER":        os.getenv("GMAIL_USER"),
    "GMAIL_APP_PASSWORD": os.getenv("GMAIL_APP_PASSWORD"),
    "RECIPIENT_EMAIL":   os.getenv("RECIPIENT_EMAIL"),
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

# ── 3. LLM API ───────────────────────────────────
section(f"LLM API ({provider})")
api_key = os.getenv(llm_key_name)
model = cfg["digest"]["model"] if cfg else ("gemini-2.0-flash" if provider == "gemini" else "claude-sonnet-4-6")
if api_key:
    try:
        if provider == "gemini":
            from google import genai as google_genai
            client = google_genai.Client(api_key=api_key)
            client.models.generate_content(model=model, contents="hi")
        else:
            import anthropic as _anthropic
            client = _anthropic.Anthropic(api_key=api_key)
            client.messages.create(
                model=model, max_tokens=10,
                messages=[{"role": "user", "content": "hi"}],
            )
        check(f"API 连接成功 ({model})", True)
    except Exception as e:
        check("API 连接", False, str(e))
else:
    check(f"API 连接（跳过，{llm_key_name} 未设置）", False)

# ── 4. Gmail SMTP ────────────────────────────────
section("Gmail SMTP")
gmail_user = os.getenv("GMAIL_USER")
gmail_pass = os.getenv("GMAIL_APP_PASSWORD")
if gmail_user and gmail_pass:
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(gmail_user, gmail_pass)
        check("Gmail 登录成功", True, gmail_user)
    except smtplib.SMTPAuthenticationError:
        check("Gmail 登录", False,
              "认证失败——请确认已开启两步验证并使用「应用专用密码」而非账号密码")
    except Exception as e:
        check("Gmail 登录", False, str(e))
else:
    check("Gmail 登录（跳过，凭据未设置）", False)

# ── 5. 发送测试邮件 ──────────────────────────────
section("测试邮件")
recipient = os.getenv("RECIPIENT_EMAIL")
all_ok = not errors

if all_ok and gmail_user and gmail_pass and recipient:
    try:
        now = datetime.now().strftime("%Y-%m-%d %H:%M UTC")
        html = f"""<!DOCTYPE html>
<html><body style="font-family:sans-serif;max-width:600px;margin:auto;padding:20px">
<h2 style="color:#1a1a2e">✅ AI Dispatch — 配置验证成功</h2>
<p>你的环境已就绪，每日简报将按时自动发送到这个邮箱。</p>
<table style="width:100%;border-collapse:collapse;font-size:14px">
  <tr><td style="padding:8px;color:#666">验证时间</td><td>{now}</td></tr>
  <tr><td style="padding:8px;color:#666">发件账号</td><td>{gmail_user}</td></tr>
  <tr><td style="padding:8px;color:#666">收件邮箱</td><td>{recipient}</td></tr>
  <tr><td style="padding:8px;color:#666">新闻来源</td>
      <td>{len(cfg.get('news_feeds', {}))} 个</td></tr>
  <tr><td style="padding:8px;color:#666">博客订阅</td>
      <td>{len(cfg.get('blog_feeds', {}))} 个</td></tr>
  <tr><td style="padding:8px;color:#666">经典收藏</td>
      <td>{len(cfg.get('classics') or [])} 篇</td></tr>
  <tr><td style="padding:8px;color:#666">使用模型</td>
      <td>{cfg['digest']['model']}</td></tr>
</table>
<p style="margin-top:24px;color:#888;font-size:12px">
  AI Dispatch · 由 config.yml send_hour_utc 控制发送时间
</p>
</body></html>"""

        msg = MIMEMultipart("alternative")
        msg["Subject"] = "✅ AI Dispatch 配置验证成功"
        msg["From"] = gmail_user
        msg["To"] = recipient
        msg.attach(MIMEText(html, "html", "utf-8"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(gmail_user, gmail_pass)
            server.sendmail(gmail_user, recipient, msg.as_string())

        check("测试邮件已发送", True, f"请检查 {recipient}")
    except Exception as e:
        check("发送测试邮件", False, str(e))
else:
    if not all_ok:
        print(f"  ⚠️  存在配置错误，跳过发送测试邮件")
    else:
        print(f"  ⚠️  邮件凭据不完整，跳过发送")

# ── 结果汇总 ─────────────────────────────────────
print("\n" + "═" * 54)
if not errors:
    print("  🎉  所有检查通过！查收测试邮件后即可等待每日简报。")
else:
    print(f"  ❌  {len(errors)} 项需要修复：")
    for e in errors:
        print(f"       · {e}")
    print("\n  参考 README.md 完成配置后重新运行此检查。")
print("═" * 54)

sys.exit(0 if not errors else 1)
