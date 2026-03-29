# Polymarket AI Trading System - Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建一个完整的 AI 驱动的 Polymarket 自动交易系统，通过新闻分析、情绪判断和市场监控实现智能交易决策和自动执行。

**Architecture:** 微服务架构，由5个核心模块组成：新闻采集引擎、AI分析引擎、市场监控引擎、交易决策引擎、交易执行引擎。使用 Python 作为主要语言，FastAPI 作为 API 框架，PostgreSQL 存储数据，Redis 做缓存和消息队列。

**Tech Stack:** Python 3.11+, FastAPI, Claude API/OpenAI API, py-clob-client, PostgreSQL, Redis, Celery, WebSocket, Docker

**预算参考:** 入门 ~$35/月, 中等 ~$270/月, 专业 ~$1,300/月 (详见 docs/research/practical_details.md)

---

## ⚡ Quick Start: MVP 最小可行原型 [建议最先执行, 2-3天]

> 在构建完整系统之前，先用最小代码验证核心假设：AI 概率估计是否真的比市场价格更准确？

### MVP Step 1: 连接 Polymarket (2小时)
- [ ] `pip install py-clob-client web3==6.14.0`
- [ ] 创建 Polygon EOA 钱包，获取私钥
- [ ] 编写连接脚本，拉取所有活跃市场列表
- [ ] 选择 5-10 个高流动性市场进行监控
- [ ] 存储市场数据到 CSV/SQLite

### MVP Step 2: AI 概率估计 (4小时)
- [ ] 用 Claude API (Sonnet) 分析每个目标市场
- [ ] Prompt: 给出市场问题 + 网上可搜索到的信息 → 输出 YES 概率
- [ ] 记录: AI 概率 vs 市场价格 → 计算 edge
- [ ] 每天运行一次，持续 3-5 天收集数据

### MVP Step 3: 验证 Edge (1天)
- [ ] 统计 AI 预测 vs 市场价格 vs 最终结果
- [ ] 计算: 如果按 AI 信号交易，理论盈亏是多少？
- [ ] **关键决策点**: Edge 是否真实存在？ > 5% 才值得继续

### MVP Step 4: 手动小额测试 (1天)
- [ ] 向钱包转入 $50 USDC.e
- [ ] 在 AI 给出高 edge (>10%) 的市场上手动下单
- [ ] 追踪实际盈亏
- [ ] **通过此步骤验证后，再进入 Phase 0 构建完整系统**

---

## Phase 0: 项目基础设施搭建 [预计2天]

### 0.1 项目初始化
- [ ] 创建 Python monorepo 项目结构
  ```
  polymarket-ai-trader/
  ├── src/
  │   ├── core/           # 共享配置、日志、工具类
  │   ├── news/           # 新闻采集模块
  │   ├── analysis/       # AI 分析模块
  │   ├── market/         # 市场监控模块
  │   ├── strategy/       # 交易策略/决策模块
  │   ├── execution/      # 交易执行模块
  │   └── dashboard/      # Web 仪表盘
  ├── tests/
  ├── config/
  ├── docker/
  ├── docs/
  └── scripts/
  ```
- [ ] 初始化 `pyproject.toml`, 配置 Poetry/uv 依赖管理
- [ ] 设置 `.env` 模板（API keys、数据库连接、钱包配置）
- [ ] 配置 logging 框架 (structlog)
- [ ] 编写 Dockerfile 和 docker-compose.yml

### 0.2 数据库设计
- [ ] 设计并创建 PostgreSQL schema:
  - `markets` - 市场信息表（market_id, question, description, end_date, category, status）
  - `market_prices` - 价格历史表（market_id, timestamp, yes_price, no_price, volume）
  - `news_articles` - 新闻文章表（id, source, title, content, url, published_at）
  - `analysis_results` - AI分析结果表（id, market_id, news_id, sentiment, probability, confidence, reasoning）
  - `trading_signals` - 交易信号表（id, market_id, signal_type, strength, ai_probability, market_price, edge）
  - `orders` - 订单表（id, market_id, side, price, size, status, tx_hash）
  - `positions` - 持仓表（market_id, token_type, size, avg_entry_price, current_price, pnl）
  - `portfolio` - 组合管理表（total_value, cash_balance, exposure, risk_metrics）
- [ ] 编写 Alembic migrations
- [ ] 编写 SQLAlchemy ORM 模型
- [ ] 编写数据库初始化和种子脚本

### 0.3 核心配置模块
- [ ] 创建 `src/core/config.py` - Pydantic Settings 配置管理
- [ ] 创建 `src/core/logger.py` - structlog 配置
- [ ] 创建 `src/core/database.py` - 数据库连接池
- [ ] 创建 `src/core/redis.py` - Redis 连接
- [ ] 创建 `src/core/exceptions.py` - 自定义异常类
- [ ] 为所有核心模块编写单元测试

---

## Phase 1: 新闻采集引擎 [预计3天]

### 1.1 新闻源适配器 (News Source Adapters)
- [ ] 创建 `src/news/base.py` - 新闻源抽象基类
  ```python
  class NewsSourceAdapter(ABC):
      async def fetch_latest(self, keywords: list[str], since: datetime) -> list[NewsArticle]
      async def search(self, query: str, max_results: int) -> list[NewsArticle]
  ```
- [ ] 实现 `src/news/sources/newsapi.py` - NewsAPI 适配器
  - 支持按关键词搜索
  - 支持按分类浏览 (politics, business, technology, sports)
  - 处理 API 速率限制和重试
- [ ] 实现 `src/news/sources/rss_feeds.py` - RSS/Atom Feed 聚合器
  - 预配置政治、经济、体育等分类的 RSS 源
  - 支持自定义 RSS 源添加
- [ ] 实现 `src/news/sources/twitter.py` - Twitter/X 适配器
  - 关注关键 KOL 和权威账号
  - 实时流式监控特定关键词
- [ ] 实现 `src/news/sources/reddit.py` - Reddit 适配器
  - 监控相关 subreddit (r/polymarket, r/politics, etc.)
- [ ] 实现 `src/news/sources/web_scraper.py` - 通用网页爬虫
  - 使用 Playwright/httpx 获取网页内容
  - 使用 readability/trafilatura 提取正文
- [ ] 为每个适配器编写集成测试（使用 mock responses）

### 1.2 新闻聚合与去重
- [ ] 创建 `src/news/aggregator.py` - 新闻聚合器
  - 并发从多个源获取新闻
  - 基于标题/内容的语义去重 (使用 sentence-transformers)
  - 新闻重要性评分
- [ ] 创建 `src/news/classifier.py` - 新闻分类器
  - 自动将新闻关联到 Polymarket 市场
  - 基于关键词 + 语义匹配
- [ ] 编写单元测试

### 1.3 新闻采集调度
- [ ] 创建 `src/news/scheduler.py` - Celery 定时任务
  - 高频源 (Twitter): 每1-5分钟
  - 中频源 (NewsAPI, RSS): 每15-30分钟
  - 低频源 (深度分析): 每1-2小时
- [ ] 创建 `src/news/pipeline.py` - 新闻处理管道
  - 采集 → 去重 → 分类 → 关联市场 → 存储 → 触发分析
- [ ] 编写端到端测试

---

## Phase 2: AI 分析引擎 [预计4天]

### 2.1 LLM 集成层
- [ ] 创建 `src/analysis/llm/base.py` - LLM Provider 抽象
  ```python
  class LLMProvider(ABC):
      async def analyze(self, prompt: str, system: str) -> AnalysisResult
      async def estimate_probability(self, context: str, question: str) -> ProbabilityEstimate
  ```
- [ ] 实现 `src/analysis/llm/claude_provider.py` - Claude API 集成
  - 使用 Claude 4.5/4.6 Sonnet 用于高频低成本分析
  - 使用 Claude Opus 用于关键决策
  - 实现重试和降级逻辑
- [ ] 实现 `src/analysis/llm/openai_provider.py` - OpenAI API 集成（备用）
- [ ] 创建 `src/analysis/llm/router.py` - 智能路由
  - 根据任务重要性选择模型
  - 成本监控和预算控制
- [ ] 编写 provider 测试

### 2.2 新闻情绪分析
- [ ] 创建 `src/analysis/sentiment.py` - 情绪分析模块
  - **Prompt 模板设计**:
    ```
    你是一位专业的预测市场分析师。请分析以下新闻对指定事件结果的影响。

    市场问题: {market_question}
    当前 YES 价格: {current_yes_price}

    新闻标题: {title}
    新闻内容: {content}
    发布时间: {published_at}

    请输出:
    1. sentiment: 对 YES 结果的影响 (strongly_positive/positive/neutral/negative/strongly_negative)
    2. impact_score: 影响力度 (0-100)
    3. probability_shift: 对 YES 概率的调整建议 (+/- 百分点)
    4. confidence: 你对这个判断的信心 (0-100)
    5. reasoning: 简短推理过程
    6. time_relevance: 这条新闻的时效性 (hours)
    ```
  - 批量分析支持（多条新闻一起分析，节省 tokens）
  - 结果结构化输出 (JSON mode)
- [ ] 编写情绪分析测试（使用预设新闻样本）

### 2.3 概率估计引擎
- [ ] 创建 `src/analysis/probability.py` - 概率估计模块
  - **基础概率估计**: LLM 直接给出概率
  - **贝叶斯更新**: 基于新新闻更新先验概率
    ```python
    def bayesian_update(prior: float, likelihood_ratio: float) -> float:
        posterior = (prior * likelihood_ratio) /
                    (prior * likelihood_ratio + (1 - prior))
        return posterior
    ```
  - **多模型集成**: 多个 LLM 预测的加权平均
  - **校准层**: 历史预测 vs 实际结果的校准曲线
- [ ] 创建 `src/analysis/calibration.py` - 校准模块
  - 记录所有预测和实际结果
  - 计算 Brier Score
  - 自动调整校准参数
- [ ] 编写概率估计测试

### 2.4 深度研究代理
- [ ] 创建 `src/analysis/research_agent.py` - 深度研究代理
  - 对高价值市场进行深入研究
  - 自动搜索补充信息
  - 生成综合分析报告
  - 识别市场可能忽略的信息
- [ ] 创建 `src/analysis/contrarian.py` - 逆向思维分析
  - 寻找市场可能定价错误的情况
  - 分析"市场为什么可能是错的"
- [ ] 编写研究代理测试

---

## Phase 3: 市场监控引擎 [预计3天]

### 3.1 Polymarket API 集成
- [ ] 创建 `src/market/polymarket_client.py` - Polymarket 客户端封装
  - 基于 py-clob-client 的高级封装
  - 市场列表获取和缓存
  - 价格/订单簿实时数据
  - 历史成交数据
  - 错误处理和重连逻辑
- [ ] 创建 `src/market/websocket.py` - WebSocket 实时数据流
  - 价格变动推送
  - 订单簿更新推送
  - 成交通知
  - 自动重连机制
- [ ] 编写 API 集成测试

### 3.2 市场扫描器
- [ ] 创建 `src/market/scanner.py` - 市场扫描模块
  - **新市场发现**: 自动检测新上线的市场
  - **高价值市场筛选**: 基于流动性、成交量、到期时间筛选
  - **异常检测**:
    - 价格突变（短时间大幅波动）
    - 成交量异常（突然放量）
    - 价差异常（买卖价差过大）
  - **市场分类**: 自动对市场进行主题分类
- [ ] 创建 `src/market/metrics.py` - 市场指标计算
  - 流动性指标 (bid-ask spread, depth)
  - 波动率指标
  - 价格动量指标
  - 成交量加权平均价 (VWAP)
- [ ] 编写市场扫描测试

### 3.3 市场数据存储
- [ ] 创建 `src/market/data_store.py` - 市场数据持久化
  - 定时快照市场价格和订单簿
  - 时序数据存储和查询优化
  - 数据过期清理策略
- [ ] 编写数据存储测试

---

## Phase 4: 交易决策引擎 [预计4天]

### 4.1 信号生成器
- [ ] 创建 `src/strategy/signal_generator.py` - 交易信号生成
  - **Edge 计算**:
    ```python
    edge = ai_estimated_probability - market_price
    # 只有 edge > threshold (例如 5%) 时才生成信号
    ```
  - **信号类型**: BUY_YES, BUY_NO, SELL_YES, SELL_NO, HOLD
  - **信号强度**: 基于 edge 大小和置信度
  - **信号过期**: 每个信号有时效性
- [ ] 创建 `src/strategy/filters.py` - 信号过滤器
  - 最低流动性要求
  - 最低成交量要求
  - 市场到期时间要求 (不交易快到期的市场)
  - 最大持仓集中度限制
  - 已有持仓方向过滤
- [ ] 编写信号生成测试

### 4.2 风险管理模块
- [ ] 创建 `src/strategy/risk_manager.py` - 风险管理
  - **仓位限制**:
    - 单个市场最大仓位: 总资金的 X%
    - 单个类别最大仓位: 总资金的 Y%
    - 总仓位限制: 总资金的 Z%
  - **止损规则**:
    - 单笔交易最大亏损
    - 单日最大亏损
    - 总回撤限制
  - **Kelly Criterion**: 基于 edge 和胜率计算最优仓位
    ```python
    kelly_fraction = (edge * win_probability - (1 - win_probability)) / edge
    position_size = kelly_fraction * bankroll * kelly_multiplier  # 通常用半 Kelly
    ```
  - **相关性检查**: 避免在高度相关的市场上过度暴露
- [ ] 创建 `src/strategy/portfolio.py` - 组合管理
  - 持仓汇总和 P&L 计算
  - 组合风险指标 (VaR, Expected Shortfall)
  - 再平衡建议
- [ ] 编写风险管理测试

### 4.3 决策引擎
- [ ] 创建 `src/strategy/decision_engine.py` - 核心决策引擎
  - 综合所有输入（信号、风控、持仓、市场状态）
  - 生成最终交易决策
  - **决策流程**:
    1. 接收交易信号
    2. 检查风控约束
    3. 计算最优仓位大小
    4. 选择订单类型（限价/市价）
    5. 设定价格和数量
    6. 生成交易指令
  - 决策日志记录
- [ ] 创建 `src/strategy/backtester.py` - 回测引擎
  - 基于历史数据模拟交易
  - 计算策略绩效指标 (Sharpe, Max Drawdown, Win Rate)
  - 参数优化
- [ ] 编写决策引擎测试

---

## Phase 5: 交易执行引擎 [预计3天]

### 5.1 订单管理
- [ ] 创建 `src/execution/order_manager.py` - 订单管理器
  - 订单创建和签名
  - 订单提交和确认
  - 订单状态追踪
  - 部分成交处理
  - 订单取消
- [ ] 创建 `src/execution/executor.py` - 交易执行器
  - **限价单执行**: 挂单等待成交
  - **市价单模拟**: 使用激进限价单模拟即时成交
  - **分批执行**: 大单拆分避免影响价格
  - **滑点保护**: 价格偏差超限自动取消
- [ ] 编写订单管理测试

### 5.2 钱包和资金管理
- [ ] 创建 `src/execution/wallet.py` - 钱包管理
  - Polygon 钱包集成 (web3.py)
  - USDC 余额查询
  - 条件代币余额查询
  - Gas 费估算和管理
  - 交易签名
- [ ] 创建 `src/execution/funding.py` - 资金管理
  - USDC 充值检测
  - 资金分配追踪
  - 利润提取
- [ ] 编写钱包测试（testnet）

### 5.3 执行监控
- [ ] 创建 `src/execution/monitor.py` - 执行监控
  - 未成交订单超时处理
  - 交易确认等待和重试
  - 区块链交易状态追踪
  - 异常告警 (Telegram/Discord/Slack)
- [ ] 编写监控测试

---

## Phase 6: 仪表盘与通知 [预计3天]

### 6.1 Web Dashboard
- [ ] 创建 `src/dashboard/app.py` - FastAPI Web 应用
- [ ] 实现仪表盘页面:
  - **总览页**: 总资产、P&L、活跃仓位数、今日交易数
  - **市场监控页**: 关注的市场列表、价格走势图、AI 分析摘要
  - **持仓页**: 当前所有持仓、盈亏、风险指标
  - **交易历史页**: 所有历史交易记录
  - **AI 分析页**: 最新分析结果、概率估计对比
  - **设置页**: 策略参数、风控参数、API 配置
- [ ] 实现 WebSocket 实时更新

### 6.2 告警与通知
- [ ] 创建 `src/dashboard/notifications.py` - 通知模块
  - **Telegram Bot**: 交易执行通知、风险告警、每日汇总
  - **Discord Webhook**: 可选的 Discord 通知
  - **邮件**: 每日/每周绩效报告
- [ ] 告警规则:
  - 新交易信号 (高 edge)
  - 订单成交
  - 止损触发
  - 市场异常波动
  - 系统错误
  - 每日 P&L 汇总
- [ ] 编写通知测试

---

## Phase 7: 部署与运维 [预计2天]

### 7.1 容器化部署
- [ ] 完善 Docker Compose 配置
  ```yaml
  services:
    news-engine:      # 新闻采集
    analysis-engine:  # AI 分析
    market-monitor:   # 市场监控
    strategy-engine:  # 交易策略
    executor:         # 交易执行
    dashboard:        # Web 仪表盘
    postgres:         # 数据库
    redis:           # 缓存/队列
    celery-worker:   # 后台任务
    celery-beat:     # 定时调度
  ```
- [ ] 配置健康检查和自动重启
- [ ] 设置日志聚合 (ELK 或 Loki)
- [ ] 配置监控告警 (Prometheus + Grafana)

### 7.2 安全加固
- [ ] 私钥加密存储 (使用 Vault 或加密环境变量)
- [ ] API Key 轮换机制
- [ ] 网络安全: 防火墙规则、VPN
- [ ] 交易金额上限硬编码保护
- [ ] 紧急停止开关 (kill switch)

### 7.3 持续改进
- [ ] 设置 A/B 测试框架 (比较不同策略)
- [ ] 自动化回测管道
- [ ] 模型性能监控和告警
- [ ] 定期策略回顾和优化

---

## 关键里程碑

| 里程碑 | 目标 | 预计完成 |
|--------|------|----------|
| M0 | 项目骨架、数据库、核心配置 | Phase 0 完成 |
| M1 | 能采集和存储新闻 | Phase 1 完成 |
| M2 | AI 能分析新闻并给出概率估计 | Phase 2 完成 |
| M3 | 能实时监控 Polymarket 市场 | Phase 3 完成 |
| M4 | 能生成交易信号和决策 | Phase 4 完成 |
| M5 | 能自动执行交易（先用 testnet/paper trading）| Phase 5 完成 |
| M6 | 有可视化仪表盘和通知 | Phase 6 完成 |
| M7 | 生产环境部署，实盘小额测试 | Phase 7 完成 |

---

## 安全第一原则

1. **先 Paper Trading**: 至少运行2周模拟交易，验证策略可行性
2. **小额起步**: 实盘初期用极小资金（<$100），逐步增加
3. **硬性止损**: 总回撤超过 20% 自动停止所有交易
4. **人工审核**: 初期所有交易需人工确认，逐步放宽到自动执行
5. **每日检查**: 每天至少人工检查一次系统状态和持仓
