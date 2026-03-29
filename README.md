# Polymarket AI Trader

AI 驱动的 Polymarket 自动交易系统。通过 Claude AI 分析新闻、估计概率、监控市场、生成交易信号，帮助你在预测市场中找到并执行高价值交易机会。

---

## 目录

- [快速开始](#快速开始)
- [系统要求](#系统要求)
- [安装指南](#安装指南)
- [配置说明](#配置说明)
- [使用教程](#使用教程)
  - [CLI 命令行工具](#cli-命令行工具)
  - [Web 仪表盘](#web-仪表盘)
- [核心概念](#核心概念)
- [交易策略详解](#交易策略详解)
- [模块说明](#模块说明)
- [常见问题](#常见问题)
- [风险提示](#风险提示)

---

## 快速开始

只需 5 步，从零开始运行系统：

```bash
# Step 1: 克隆项目
git clone https://github.com/colin0615/111.git
cd 111

# Step 2: 安装依赖
pip install httpx python-dotenv pydantic pydantic-settings rich aiosqlite structlog anthropic

# Step 3: 配置 API Key
cp .env.example .env
# 编辑 .env 文件，填入你的 API Key（详见下方配置说明）

# Step 4: 初始化组合
python -m src.main init

# Step 5: 启动 Web 仪表盘
python -m src.dashboard
# 打开浏览器访问 http://localhost:8888
```

---

## 系统要求

| 要求 | 说明 |
|------|------|
| **Python** | 3.11 或更高版本 |
| **操作系统** | Windows / macOS / Linux 均可 |
| **网络** | 需要能访问 Polymarket API 和 Claude API |
| **API Key** | 必须：Anthropic API Key；可选：NewsAPI Key |
| **钱包** | 实盘交易需要 Polygon 钱包和 USDC.e（Paper Trading 不需要）|

---

## 安装指南

### 方式一：pip 直接安装（推荐）

```bash
pip install httpx python-dotenv pydantic pydantic-settings rich aiosqlite structlog anthropic
```

### 方式二：使用 pyproject.toml

```bash
pip install -e .
```

### 验证安装

```bash
python -m src.main
```

如果看到命令菜单，说明安装成功。

---

## 配置说明

### 第 1 步：创建配置文件

```bash
cp .env.example .env
```

### 第 2 步：填写必要配置

用任意文本编辑器打开 `.env` 文件：

```bash
# ============================================
# 必填项
# ============================================

# Claude AI API Key（必须）
# 获取方式：https://console.anthropic.com/settings/keys
# 点击 "Create Key"，复制粘贴到这里
ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxxxxxxxxxxxxx

# ============================================
# 可选项（Paper Trading 模式下不需要填）
# ============================================

# Polymarket 钱包私钥（实盘交易才需要）
# 这是你的 Polygon 钱包私钥，不带 0x 前缀
# ⚠️ 绝对不要分享给任何人！
POLYMARKET_PRIVATE_KEY=

# NewsAPI Key（可选，提升新闻质量）
# 获取方式：https://newsapi.org/register （免费，100次/天）
NEWSAPI_KEY=

# Telegram 通知（可选）
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
```

### 第 3 步：调整交易参数（可选）

```bash
# 交易参数（有默认值，可不填）
INITIAL_BANKROLL=50        # 初始资金 $50
MAX_POSITION_SIZE=5        # 单笔最大 $5
MIN_EDGE_THRESHOLD=0.08    # 最低 8% edge 才交易
MAX_DAILY_TRADES=3         # 每天最多 3 笔
STOP_LOSS_PCT=0.20         # 亏损 20% 自动停止
KELLY_FRACTION=0.15        # Kelly 系数的 15%
```

### 参数说明

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `INITIAL_BANKROLL` | 50 | 你的初始交易资金（美元） |
| `MAX_POSITION_SIZE` | 5 | 单笔交易最大金额，建议不超过资金的 10% |
| `MIN_EDGE_THRESHOLD` | 0.08 | AI 概率与市场价格的最小差值（8%），低于此值不交易 |
| `MAX_DAILY_TRADES` | 3 | 每天最多交易次数，防止过度交易 |
| `STOP_LOSS_PCT` | 0.20 | 总亏损达到初始资金的 20% 时自动停止交易 |
| `KELLY_FRACTION` | 0.15 | Kelly 公式系数，0.15 表示使用 15% Kelly（保守策略） |

---

## 使用教程

### CLI 命令行工具

系统提供 6 个核心命令：

#### 1. `init` — 初始化组合

首次使用时运行，创建数据库并设置初始资金。

```bash
python -m src.main init
```

输出示例：
```
Portfolio initialized with $50.00
Database: /your/path/data/trader.db
```

#### 2. `scan` — 扫描市场机会

这是你最常用的命令。它会：
1. 从 Polymarket 拉取所有活跃市场
2. 为每个市场收集相关新闻
3. 用 Claude AI (Haiku) 快速分析每个市场
4. 计算 AI 概率与市场价格的差距 (edge)
5. 生成交易信号

```bash
# 扫描 top 20 市场（默认）
python -m src.main scan

# 扫描 top 50 市场
python -m src.main scan 50
```

输出示例：
```
┌────────────────────────── Market Scan Results ──────────────────────────┐
│ #  │ Market                                    │ Cat    │ YES $ │ AI   │ Edge   │ Signal   │ Size  │
│ 1  │ Will BTC exceed $100k before May?         │ crypto │ 0.650 │ 78%  │ +13.0% │ BUY_YES  │ $2.79 │
│ 2  │ Will Fed cut rates in May?                │ econ   │ 0.420 │ 40%  │ -2.0%  │ -        │ -     │
│ 3  │ Dem win Georgia Senate?                   │ politi │ 0.480 │ 38%  │ +10.0% │ BUY_NO   │ $2.00 │
└─────────────────────────────────────────────────────────────────────────┘
```

**如何看这个表：**
- **AI Prob**: AI 认为 YES 的概率
- **Edge**: AI概率 - 市场价格。**正数 = 市场低估了 YES**，**负数 = 市场高估了 YES**
- **Signal**: 交易方向。BUY_YES = 买入 YES（看涨），BUY_NO = 买入 NO（看跌）
- **Size**: 建议的交易金额

**关键：只关注 Edge > 8% 的市场！**

#### 3. `analyze <condition_id>` — 深度分析

对某个市场进行深入 AI 分析（使用更强的 Claude Sonnet 模型）：

```bash
python -m src.main analyze 0xabc123...
```

这会输出：
- YES 和 NO 的详细论据
- AI 概率估计和置信度
- 市场可能遗漏的信息
- 具体交易建议

**什么时候用深度分析？**
- 扫描发现 edge > 10% 的市场
- 准备投入较大金额之前
- 对某个市场特别感兴趣时

#### 4. `trade` — 交易流程

完整的交易流程：扫描 → 分析 → 生成信号 → 执行。

```bash
# 干跑模式（只看信号，不实际交易）
python -m src.main trade

# Paper Trading（记录虚拟交易到数据库）
python -m src.main trade --execute
```

**Paper Trading 模式说明：**
- 不需要 Polymarket 钱包
- 不花真钱
- 所有交易记录到数据库
- 用来验证策略是否有效
- **建议至少 paper trade 2 周再用真钱**

#### 5. `portfolio` — 查看组合

```bash
python -m src.main portfolio
```

输出示例：
```
        Portfolio Summary
┌────────────────────┬──────────┐
│  Initial Bankroll  │  $50.00  │
│  Cash Available    │  $44.21  │
│  Invested          │   $5.79  │
│  Unrealized P&L    │  +$0.43  │
│  Total Value       │  $50.43  │
│  Return            │   +0.9%  │
│  Trades Today      │       2  │
└────────────────────┴──────────┘

         Open Positions
┌─────────────────────────┬──────┬────────┬───────┬─────────┬─────────┐
│ Market                  │ Side │ Shares │ Avg $ │ Current │ P&L     │
│ BTC > $100k by May?     │ YES  │  4.29  │ 0.650 │  0.680  │ +$0.13  │
│ Dem win GA Senate?      │ NO   │  3.85  │ 0.520 │  0.550  │ +$0.12  │
└─────────────────────────┴──────┴────────┴───────┴─────────┴─────────┘
```

#### 6. `history` — 交易历史

```bash
python -m src.main history
```

---

### Web 仪表盘

系统内置一个漂亮的 Web 界面，在浏览器中操作：

```bash
python -m src.dashboard
```

然后打开浏览器访问：**http://localhost:8888**

**仪表盘功能：**
- 总览页：资金、P&L、持仓概览
- 市场扫描：一键扫描 + AI 分析结果
- 深度分析：选中市场进行 Sonnet 深度分析
- 交易执行：Paper Trade 一键执行
- 组合管理：持仓、历史、P&L 图表
- 实时更新：自动刷新市场数据

---

## 核心概念

### 什么是 Edge？

**Edge = AI 估计概率 - 市场价格**

这是整个系统的核心。举个例子：

```
市场问题："BTC 会在4月底前突破 $100k 吗？"
市场 YES 价格：$0.65（市场认为 65% 概率）
AI 估计概率：78%

Edge = 78% - 65% = +13%

这意味着：AI 认为市场低估了 YES 的概率。
如果 AI 是对的，买入 YES 有 13% 的预期优势。
```

### 什么时候交易？

```
Edge > 8%   → 可以考虑交易
Edge > 15%  → 好机会
Edge > 20%  → 罕见的大机会（但要怀疑 AI 是否过度自信）
Edge < 8%   → 不交易（优势太小，手续费会吃掉利润）
```

### Kelly Criterion 是什么？

Kelly 公式帮你计算"应该投多少钱"：

```
kelly_fraction = edge / (1 - market_price)
position_size = kelly_fraction × kelly_multiplier × bankroll
```

我们使用 15% Kelly（非常保守），避免因为 AI 判断错误而亏太多。

### Paper Trading vs 实盘

| 模式 | 命令 | 花真钱？ | 需要钱包？ |
|------|------|----------|-----------|
| 干跑 | `trade` | 否 | 否 |
| Paper | `trade --execute` | 否 | 否 |
| 实盘 | 代码中切换 | **是** | **是** |

**强烈建议流程：干跑 → Paper Trading 2周 → 小额实盘**

---

## 交易策略详解

### 市场选择

系统将市场分为 5 个类别，按 AI 优势排序：

| 优先级 | 类别 | 资金分配 | AI 优势 |
|--------|------|----------|---------|
| 1 | 加密货币 | 40% | 数据丰富，24/7，AI快速反应 |
| 2 | 政治/政策 | 30% | AI可快速读大量政策文件 |
| 3 | 经济/科技 | 20% | 数据发布有固定时间 |
| 4 | 体育 | 0% | AI优势最小，暂不参与 |
| - | 储备金 | 10% | 保留应对突发机会 |

### 风控规则

系统内置 6 道风控检查，**全部通过才允许交易**：

1. **止损检查**: 总亏损 > 20% → 禁止所有交易
2. **每日限额**: 超过 3 笔/天 → 停止
3. **资金检查**: 现金不足 → 拒绝
4. **持仓检查**: 同一市场已有仓位 → 拒绝
5. **集中度检查**: 总投资 > 80% 资金 → 拒绝
6. **信号质量**: Edge < 8% 或 置信度 < 4 → 拒绝

### 每日工作流程建议

```
早上 (5分钟):
  1. python -m src.main portfolio     # 看看昨天的持仓变化
  2. python -m src.main scan          # 扫描新机会

发现机会时 (10分钟):
  3. python -m src.main analyze <id>  # 深度分析高 edge 市场
  4. python -m src.main trade --execute  # Paper trade

晚上 (5分钟):
  5. python -m src.main history       # 回顾今日交易
  6. python -m src.main portfolio     # 检查总体表现
```

---

## 模块说明

```
src/
├── core/
│   ├── config.py          # 配置管理：从 .env 加载所有参数
│   └── database.py        # SQLite 数据库：markets, analyses, trades, portfolio
├── market/
│   └── client.py          # Polymarket API 客户端
│                           #   - Gamma API: 市场发现和元数据
│                           #   - CLOB API: 价格和订单簿
│                           #   - 市场自动分类
├── analysis/
│   └── ai_analyzer.py     # Claude AI 分析引擎
│                           #   - quick_scan(): Haiku 快速分析（便宜）
│                           #   - deep_analysis(): Sonnet 深度分析（更准）
├── news/
│   └── collector.py       # 新闻采集
│                           #   - RSS Feed 聚合（免费，无需 API Key）
│                           #   - NewsAPI 集成（可选，需要 Key）
│                           #   - 自动匹配新闻到市场
├── strategy/
│   └── signals.py         # 交易策略
│                           #   - Edge 计算
│                           #   - Kelly Criterion 仓位管理
│                           #   - 6 道风控检查
│                           #   - 信号排名
├── execution/
│   ├── paper_trader.py    # Paper Trading 执行器
│   └── live_trader.py     # 实盘执行器（py-clob-client）
├── dashboard/             # Web 仪表盘
│   └── app.py             # FastAPI 后端 + 前端页面
└── main.py                # CLI 入口
```

---

## 常见问题

### Q: 需要多少钱才能开始？
**A:** Paper Trading 不需要任何钱，只需要 Anthropic API Key（Claude API 有免费额度）。实盘建议最少 $50。

### Q: Claude API 费用大概多少？
**A:** 使用 Haiku 模型扫描 20 个市场约花费 $0.01。每天扫描 3 次 + 偶尔深度分析，月费约 $1-5。

### Q: 可以赚钱吗？
**A:** 不保证。预测市场竞争激烈，只有 0.51% 的用户赚超过 $1,000。这个工具帮你找优势，但 AI 也会犯错。请先 Paper Trading 验证。

### Q: 如何获取 Polymarket 钱包？
**A:**
1. 安装 MetaMask 浏览器扩展
2. 创建新钱包或导入已有钱包
3. 切换到 Polygon 网络
4. 通过交易所买入 USDC，转到 Polygon 上的钱包地址
5. 将钱包私钥（不带 0x）填入 `.env`

### Q: 我在中国/其他地区，能用吗？
**A:** Polymarket API 的访问性取决于你的地区。如果 API 被限制，可能需要使用代理。美国用户需要通过 Polymarket US（CFTC 监管），注意 py-clob-client 目前不兼容 Polymarket US。

### Q: scan 很慢怎么办？
**A:** scan 需要：获取市场 + 收集新闻 + AI 分析。20 个市场大约需要 1-3 分钟。可以减少扫描数量：`python -m src.main scan 10`

### Q: 如何从 Paper Trading 切换到实盘？
**A:** 在确认 Paper Trading 持续盈利后（建议至少 2 周）：
1. 在 `.env` 填入 `POLYMARKET_PRIVATE_KEY`
2. 向钱包存入少量 USDC.e（建议从 $50 开始）
3. 在代码中将 `paper_trader` 替换为 `live_trader`（后续版本会增加命令行开关）

### Q: 数据存在哪里？
**A:** 所有数据存在项目目录下的 `data/trader.db`（SQLite 文件）。可以用任何 SQLite 客户端查看。

---

## 风险提示

**重要：本工具仅供学习和研究使用。**

1. **预测市场有亏损风险。** 你可能会亏掉全部投入。
2. **AI 不是完美的。** Claude 的概率估计可能有偏差。
3. **过去的表现不代表未来。** Paper Trading 赚钱不意味着实盘也会赚。
4. **请只用你能承受亏损的钱。** 不要借钱或用生活费交易。
5. **了解你所在地区的法律法规。** 某些地区可能限制预测市场交易。
6. **保管好私钥。** 私钥泄露 = 资金丢失，无法找回。

---

## 许可证

MIT License
