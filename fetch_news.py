import feedparser
import anthropic
import smtplib
import json
import os
import re
import sys
import yaml
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timedelta, timezone
from pathlib import Path

HISTORY_PATH = Path(__file__).parent / "sent_history.json"
HISTORY_MAX = 1000  # 最多保留最近 1000 条，防止文件无限增长


def load_config() -> dict:
    path = Path(__file__).parent / "config.yml"
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_history() -> set[str]:
    if HISTORY_PATH.exists():
        data = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
        return set(data.get("urls", []))
    return set()


def save_history(history: set[str], new_url: str) -> None:
    updated = list(history | {new_url})
    if len(updated) > HISTORY_MAX:
        updated = updated[-HISTORY_MAX:]
    HISTORY_PATH.write_text(
        json.dumps({"urls": updated, "updated": datetime.now().isoformat()}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def extract_recommended_url(html: str) -> str | None:
    """从 Claude 输出的 HTML 中提取 blog-pick 块里的链接。"""
    match = re.search(r'<div class="blog-pick">.*?<a href="([^"]+)"', html, re.DOTALL)
    return match.group(1) if match else None


def _fetch_feeds(feeds: dict, hours: int, per_source: int,
                 arxiv_keywords: list[str]) -> list[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    articles = []

    for source, url in feeds.items():
        try:
            feed = feedparser.parse(url, request_headers={"User-Agent": "Mozilla/5.0"})
            for entry in feed.entries[:per_source]:
                published = None
                for attr in ("published_parsed", "updated_parsed"):
                    t = getattr(entry, attr, None)
                    if t:
                        published = datetime(*t[:6], tzinfo=timezone.utc)
                        break

                if published and published < cutoff:
                    continue

                title = entry.get("title", "")
                summary = entry.get("summary", "")
                text = (title + " " + summary).lower()

                if source.startswith("arxiv") and not any(kw in text for kw in arxiv_keywords):
                    continue

                articles.append({
                    "source": source,
                    "title": title,
                    "url": entry.get("link", ""),
                    "summary": summary[:1000] if summary else "",
                    "published": published.strftime("%Y-%m-%d %H:%M UTC") if published else "Unknown",
                })
        except Exception as e:
            print(f"[WARN] {source}: {e}", file=sys.stderr)

    return articles


def fetch_recent_articles(cfg: dict) -> list[dict]:
    d = cfg["digest"]
    return _fetch_feeds(
        cfg["news_feeds"], d["news_hours"], d["news_per_source"], cfg["arxiv_keywords"]
    )


def fetch_blog_candidates(cfg: dict, history: set[str]) -> list[dict]:
    """抓取近 blog_days 天的博客文章 + 读取经典列表，过滤已推送过的。"""
    d = cfg["digest"]
    blog_hours = d["blog_days"] * 24

    # RSS 博客
    rss_blogs = _fetch_feeds(
        cfg["blog_feeds"], blog_hours, d["blog_per_source"], cfg["arxiv_keywords"]
    )

    # 经典文章（无时间限制，从 config 读取）
    classics = [
        {
            "source": f"{c.get('type', 'classic').title()} · {c.get('author', '')}",
            "title": c["title"],
            "url": c["url"],
            "summary": c.get("note", ""),
            "published": str(c.get("year", "经典")),
        }
        for c in (cfg.get("classics") or [])
    ]

    # 合并后过滤历史
    all_candidates = rss_blogs + classics
    unsent = [a for a in all_candidates if a["url"] not in history]
    return unsent


def summarize_with_claude(articles: list[dict], blog_candidates: list[dict], cfg: dict) -> str:
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    d = cfg["digest"]

    topics_str = "、".join(cfg["topics"])
    lang = d.get("output_language", "中文")

    articles_text = "\n\n---\n\n".join(
        f"[{a['source']}] ({a['published']})\n标题: {a['title']}\n链接: {a['url']}\n摘要: {a['summary']}"
        for a in articles
    )
    blogs_text = "\n\n---\n\n".join(
        f"[{b['source']}] ({b['published']})\n标题: {b['title']}\n链接: {b['url']}\n简介: {b['summary']}"
        for b in blog_candidates
    ) if blog_candidates else "（暂无候选，所有文章均已推送过）"

    today = datetime.now().strftime("%Y年%m月%d日")

    prompt = f"""你是一位 AI 领域的资深研究员，为顶级机构的同行撰写每日深度简报。
读者是熟悉该领域的专业人士，不需要解释基础概念，需要的是洞察和判断。
用户重点关注的方向：{topics_str}。
所有输出请使用{lang}。

【新闻资讯】过去 {d['news_hours']} 小时，共 {len(articles)} 条：

{articles_text}

【博客/经典文章候选池】共 {len(blog_candidates)} 篇（含近期博客、经典文章、访谈、大佬经验分享，均未推送过）：

{blogs_text}

请完成以下五个部分，严格使用 HTML 格式输出（不要加 markdown 代码块、不要加 ```html）：

第一部分：重点新闻（10-15条，优先与用户关注方向相关）
每条包含：发生了什么（1句）、技术/商业意义（2-3句，要有判断和立场）、与其他动态的关联（如有）。

第二部分：趋势分析
识别 2-3 个值得关注的技术或行业趋势，需有证据引用，给出预判。

第三部分：值得深挖
2-3 篇值得精读的论文或报告（优先 arxiv），说明核心贡献和阅读重点。

第四部分：今日推荐博客
从候选池中挑选 1 篇最值得精读的（可以是近期博客、经典文章、访谈或经验分享，不限时间）。
优先选择与今日新闻趋势有呼应的，或能提供长期视角的经典。
给出：为什么今天推荐这篇（结合当下背景）、3 个核心观点（bullet）、适合谁读、大致阅读时间。

第五部分：今日信号
最关键的一个判断，不超过 60 字。

HTML 格式模板：

<h2>🤖 AI 深度简报 · {today}</h2>
<p class="intro">新闻 {len(articles)} 条 · 博客 {len(blogs)} 篇 · 聚焦 {topics_str}</p>

<div class="section-title">📌 重点新闻</div>

<div class="item">
  <h3><a href="URL">标题（{lang}）</a></h3>
  <span class="meta">来源：XXX · 时间</span>
  <p><strong>事件：</strong>……</p>
  <p><strong>意义：</strong>……</p>
  <p class="tag">关联：……</p>
</div>

<div class="section-title">📈 趋势分析</div>

<div class="trend">
  <h3>趋势名称</h3>
  <p>……</p>
</div>

<div class="section-title">🔬 值得深挖</div>

<div class="deep-read">
  <h3><a href="URL">论文/报告标题</a></h3>
  <p>……</p>
</div>

<div class="section-title">📖 今日推荐博客</div>

<div class="blog-pick">
  <h3><a href="URL">文章标题</a></h3>
  <span class="meta">作者/来源 · 时间</span>
  <p class="blog-why">……为什么值得读……</p>
  <ul>
    <li>核心观点一</li>
    <li>核心观点二</li>
    <li>核心观点三</li>
  </ul>
  <p class="blog-audience">适合：…… · 阅读时间：约 XX 分钟</p>
</div>

<div class="closing">
  <strong>今日信号：</strong>……
</div>"""

    msg = client.messages.create(
        model=d["model"],
        max_tokens=d["max_tokens"],
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text


EMAIL_CSS = """
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
       background: #f0f0f5; margin: 0; padding: 20px; color: #222; }
.wrapper { max-width: 700px; margin: auto; background: #fff;
           border-radius: 10px; overflow: hidden;
           box-shadow: 0 2px 12px rgba(0,0,0,.10); }
.header { background: #0f0f1a; color: #fff; padding: 28px 36px; }
.header h1 { margin: 0; font-size: 22px; letter-spacing: -.3px; }
.body { padding: 28px 36px; }
h2 { color: #0f0f1a; margin-top: 0; font-size: 20px; }
.intro { color: #666; font-size: 13px; margin-bottom: 28px; }
.section-title { font-weight: 700; font-size: 11px; text-transform: uppercase;
                 letter-spacing: .1em; color: #999; margin: 32px 0 14px;
                 padding-bottom: 6px; border-bottom: 1px solid #eee; }
.item { border-left: 3px solid #4f46e5; padding: 14px 18px;
        margin-bottom: 18px; background: #fafafa; border-radius: 0 8px 8px 0; }
.item h3 { margin: 0 0 4px; font-size: 15px; line-height: 1.4; }
.item h3 a { color: #1a1a2e; text-decoration: none; }
.item h3 a:hover { text-decoration: underline; }
.meta { font-size: 11px; color: #aaa; display: block; margin-bottom: 8px; }
.item p { margin: 6px 0 0; font-size: 14px; line-height: 1.7; color: #444; }
.item p.tag { font-size: 12px; color: #7c6fcd; margin-top: 8px; }
.trend { border-left: 3px solid #059669; padding: 14px 18px;
         margin-bottom: 18px; background: #f0fdf4; border-radius: 0 8px 8px 0; }
.trend h3 { margin: 0 0 8px; font-size: 15px; color: #065f46; }
.trend p { margin: 0; font-size: 14px; line-height: 1.7; color: #444; }
.deep-read { border-left: 3px solid #d97706; padding: 14px 18px;
             margin-bottom: 18px; background: #fffbeb; border-radius: 0 8px 8px 0; }
.deep-read h3 { margin: 0 0 8px; font-size: 15px; }
.deep-read h3 a { color: #92400e; text-decoration: none; }
.deep-read p { margin: 0; font-size: 14px; line-height: 1.7; color: #444; }
.blog-pick { border-left: 3px solid #db2777; padding: 14px 18px;
             margin-bottom: 18px; background: #fdf2f8; border-radius: 0 8px 8px 0; }
.blog-pick h3 { margin: 0 0 4px; font-size: 15px; }
.blog-pick h3 a { color: #831843; text-decoration: none; }
.blog-pick h3 a:hover { text-decoration: underline; }
.blog-why { margin: 10px 0 8px; font-size: 14px; line-height: 1.7; color: #444; }
.blog-pick ul { margin: 8px 0; padding-left: 20px; font-size: 14px;
                line-height: 1.8; color: #444; }
.blog-audience { font-size: 12px; color: #9d174d; margin: 8px 0 0; }
.closing { background: #1a1a2e; color: #e0e0ff; border-radius: 8px;
           padding: 16px 20px; margin-top: 28px; font-size: 14px; line-height: 1.6; }
.closing strong { color: #fff; }
.footer { padding: 16px 36px; font-size: 12px; color: #bbb;
          border-top: 1px solid #eee; text-align: center; }
"""


def send_email(html_body: str) -> None:
    today = datetime.now().strftime("%m/%d")
    subject = f"🤖 AI Daily Brief · {today}"

    full_html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>{EMAIL_CSS}</style>
</head>
<body>
<div class="wrapper">
  <div class="header"><h1>AI Daily Brief</h1></div>
  <div class="body">{html_body}</div>
  <div class="footer">Powered by Claude + GitHub Actions · 每日 07:00 BST 自动发送</div>
</div>
</body></html>"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = os.environ["GMAIL_USER"]
    msg["To"] = os.environ["RECIPIENT_EMAIL"]
    msg.attach(MIMEText(full_html, "html", "utf-8"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(os.environ["GMAIL_USER"], os.environ["GMAIL_APP_PASSWORD"])
        server.sendmail(os.environ["GMAIL_USER"], os.environ["RECIPIENT_EMAIL"], msg.as_string())


if __name__ == "__main__":
    cfg = load_config()
    history = load_history()

    print("Fetching news articles...")
    articles = fetch_recent_articles(cfg)
    print(f"Found {len(articles)} news articles")

    print("Fetching blog/classic candidates...")
    blog_candidates = fetch_blog_candidates(cfg, history)
    print(f"Found {len(blog_candidates)} unsent blog/classic candidates")

    if not articles and not blog_candidates:
        print("No content found, skipping.")
        sys.exit(0)

    print("Summarizing with Claude...")
    summary = summarize_with_claude(articles, blog_candidates, cfg)

    print("Sending email...")
    send_email(summary)

    recommended_url = extract_recommended_url(summary)
    if recommended_url:
        print(f"Recording recommended URL: {recommended_url}")
        save_history(history, recommended_url)
    else:
        print("[WARN] Could not extract recommended URL from output, history not updated.")

    print("Done!")
