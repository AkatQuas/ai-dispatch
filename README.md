# 📡 AI Dispatch

每天早上自动聚合 AI / Robotics / Agent 领域的最新动态，由 Claude Opus 生成深度分析，发送到你的邮箱。完全免费运行在 GitHub Actions 上，无需服务器。

*Your daily AI intelligence dispatch.*

## 效果预览

每封邮件包含五个板块：

| 板块 | 内容 |
|------|------|
| 📌 重点新闻 | 10-15 条精选，每条附意义分析和关联判断 |
| 📈 趋势分析 | 跨文章归纳的行业/技术趋势及预判 |
| 🔬 值得深挖 | 精选 arxiv 论文，说明核心贡献和阅读重点 |
| 📖 今日推荐博客 | 1 篇深度导读（可以是近期博客、经典文章或大佬访谈，自动去重不重复） |
| 💡 今日信号 | 一句话最关键判断 |

---

## 快速开始

### 前置条件

- GitHub 账号（免费）
- Gmail 账号
- [Anthropic API Key](https://console.anthropic.com/)（按用量付费，约 $0.67/天）

---

### 第一步：Fork 仓库

点击右上角 **Fork** → 创建到你自己的账号下。

---

### 第二步：获取 Gmail 应用密码

> Gmail 不允许直接用账号密码，需要生成专用的「应用密码」。

1. 打开 [myaccount.google.com/security](https://myaccount.google.com/security)
2. 确认**两步验证**已开启（未开启则先开启）
3. 搜索框输入 **App Passwords** → 进入
4. 选择「邮件」+「Mac」→ 点击**生成**
5. 复制显示的 **16 位密码**（只显示一次）

---

### 第三步：添加 GitHub Secrets

进入你 Fork 后的仓库 → **Settings → Secrets and variables → Actions → New repository secret**

需要添加以下 **4 个** Secrets：

| Secret 名称 | 填写内容 |
|-------------|----------|
| `ANTHROPIC_API_KEY` | 你的 Anthropic API Key（`sk-ant-...`） |
| `GMAIL_USER` | 你的 Gmail 地址（`yourname@gmail.com`） |
| `GMAIL_APP_PASSWORD` | 第二步生成的 16 位密码（去掉空格） |
| `RECIPIENT_EMAIL` | 收件邮箱（可以和 `GMAIL_USER` 相同） |

---

### 第四步：个性化配置

编辑仓库根目录的 **`config.yml`**，这是你唯一需要修改的文件：

```
config.yml 分为 5 个部分，按需修改：

  STEP 1 · 关注主题       → 告诉 Claude 你关心什么方向
  STEP 2 · 新闻来源       → 注释掉不需要的，添加自己的 RSS
  STEP 3 · 博客订阅       → 研究员博客，90 天内文章自动轮换
  STEP 4 · 经典收藏       → 经典文章/访谈，永久收藏，自动去重
  STEP 5 · 高级参数       → 模型选择、语言等（可不改）
```

**修改主题示例**（改成你感兴趣的领域）：
```yaml
topics:
  - computer vision
  - reinforcement learning
  - AI safety
```

**添加经典文章示例**：
```yaml
classics:
  - title: "文章标题"
    url: https://example.com/article
    author: 作者名
    type: blog        # blog / interview / talk / essay
    year: 2023
    note: 一句话说明为什么值得读
```

---

### 第五步：验证配置

进入仓库 → **Actions → ✅ Check Setup → Run workflow**

这会自动检查所有配置并发送一封测试邮件到你的邮箱。

```
── GitHub Secrets ──────────────────────────────────
  ✅  ANTHROPIC_API_KEY  (已设置)
  ✅  GMAIL_USER         (已设置)
  ✅  GMAIL_APP_PASSWORD (已设置)
  ✅  RECIPIENT_EMAIL    (已设置)

── config.yml ──────────────────────────────────────
  ✅  config.yml 存在
  ✅  topics 已配置      (3 个主题)
  ✅  news_feeds 已配置  (9 个来源)
  ✅  blog_feeds 已配置  (8 个博客)

── Anthropic API ────────────────────────────────────
  ✅  API 连接成功 (claude-opus-4-7)

── Gmail SMTP ───────────────────────────────────────
  ✅  Gmail 登录成功 (yourname@gmail.com)

── 测试邮件 ─────────────────────────────────────────
  ✅  测试邮件已发送 (请检查收件箱)

══════════════════════════════════════════════════════
  🎉  所有检查通过！查收测试邮件后即可等待每日简报。
══════════════════════════════════════════════════════
```

全部绿色后，每天 **06:00 UTC（英国夏令时 07:00 BST）** 自动运行。

---

## 费用参考

| 模型 | 每天约 | 每月约 | 说明 |
|------|--------|--------|------|
| `claude-opus-4-7` | $0.67 | $20 | 默认，分析质量最高 |
| `claude-sonnet-4-6` | $0.05 | $1.5 | 便宜 13 倍，日常摘要够用 |

在 `config.yml` 的 `digest.model` 中切换。GitHub Actions 完全免费。

---

## 文件说明

```
ai-daily-news/
├── config.yml              ← 你的个性化配置（唯一需要编辑的文件）
├── sent_history.json       ← 已推送博客记录（自动维护，请勿手动编辑）
├── fetch_news.py           ← 主程序
├── check_setup.py          ← 配置验证脚本
├── requirements.txt
└── .github/workflows/
    ├── daily_news.yml      ← 每日定时任务
    └── check_setup.yml     ← 一键验证配置
```

---

## 常见问题

**Q: 测试邮件收到了但每日邮件没来？**
检查 Actions → Daily AI News 里有没有报错。GitHub Actions 的 cron 有时会延迟 15-30 分钟。

**Q: Gmail 登录失败 (SMTPAuthenticationError)？**
确认用的是「应用专用密码」（16位）而不是 Gmail 账号密码本身。

**Q: 想换成中文以外的语言？**
`config.yml` 中把 `output_language: 中文` 改为 `output_language: English` 即可。

**Q: 如何添加自己的 RSS 源？**
在 `config.yml` 的 `news_feeds` 或 `blog_feeds` 下新增一行：`名称: RSS链接`。

**Q: 推荐博客一直重复？**
`sent_history.json` 记录已推送内容，正常情况下不会重复。如需重置，清空该文件的 `urls` 数组即可。
