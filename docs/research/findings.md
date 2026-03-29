# Polymarket AI Trading System - Research Findings

## Last Updated: 2026-03-29

---

## 1. Polymarket 平台架构

### 1.1 基础设施
- **区块链**: Polygon PoS (Ethereum L2)
- **结算代币**: USDC.e (从 Ethereum 桥接的 USDC，非原生 USDC)。Polymarket 是 Polygon 上最大的 USDC.e 持有者
- **交易机制**: CLOB (Hybrid-Decentralized Order Book) - 链下匹配、链上结算
- **条件代币框架**: Gnosis Conditional Token Framework (CTF)
- **代币标准**: ERC-1155 多代币标准，所有结果代币由单一 CTF 合约管理
- **每个市场**: 二元结果 (YES/NO)

### 1.2 三大 API 服务

#### Gamma API (市场元数据 - 只读)
- **Base URL**: `https://gamma-api.polymarket.com/markets`
- **认证**: 无需认证
- **用途**: 发现市场、获取事件详情、分类统计、历史数据
- 提供人类可读的市场描述和元数据

#### CLOB API (交易核心)
- **Base URL**: `https://clob.polymarket.com`
- **认证**: Ed25519 密钥认证，EIP-712 签名订单
- **关键端点**:
  - `POST /order` - 提交单个订单 (3,500 req/10s burst)
  - `POST /orders` - 批量订单，最多15个/次 (1,000 req/10s burst)
  - `DELETE /order` / `DELETE /orders` - 取消订单
  - `GET /book` - 获取订单簿
  - `GET /price` / `GET /midprice` - 获取价格 (1,500 req/10s)
- **速率限制**: REST 15,000 req/10s; CLOB 9,000 req/10s
- **订单类型**: 限价单 (默认), postOnly, FOK (Fill or Kill), FAK (Fill and Kill)
- **注意**: 所有订单均为限价单，市价单通过激进定价模拟

#### WebSocket 实时数据
- **Endpoint**: `wss://ws-subscriptions-clob.polymarket.com/ws/`
- **Market Channel** (公开): 订单簿更新、成交事件、最优买卖价变动
- **User Channel** (认证): 订单状态更新、成交通知
- **心跳机制**: 客户端断开连接后，所有挂单自动取消

### 1.3 美国市场 (2026新变化)
- Polymarket US 受 CFTC 监管，API 对美国开发者开放
- Polymarket US Retail API 包含 **23个 REST 端点** 和 **2个 WebSocket 端点**

### 1.4 条件代币框架 (CTF) 详解
1. **市场创建**: `conditionId = keccak256(questionId, oracle, outcomeSlotCount)`
   - `questionId` = IPFS hash
   - `oracle` = UMA Adapter V2
   - `outcomeSlotCount` = 2 (二元)
2. **代币铸造 (Splitting)**: 锁定 1 USDC → 铸造 1 YES token + 1 NO token
3. **代币销毁 (Merging)**: 1 YES + 1 NO → 赎回 1 USDC
4. **价格锚定**: 套利保证 YES价格 + NO价格 ≈ $1.00
5. **市场结算**: UMA Optimistic Oracle，任何人可提议结果，有争议则由 UMA 代币持有者投票

### 1.5 CLOB 匹配机制
- 链下: 运营商追踪、匹配、排序订单
- 链上: 智能合约处理结算和执行（非托管）
- 价格-时间优先匹配
- **流动性统一**: 买 YES @ $0.70 = 卖 NO @ $0.30，自动生成双边流动性

---

## 2. 已有开源工具和框架

### 2.1 官方工具

| 工具 | 语言 | 说明 |
|------|------|------|
| [Polymarket/agents](https://github.com/Polymarket/agents) | Python | 官方 AI 交易代理框架，MIT 许可，集成 Langchain + Chroma RAG + OpenAI |
| [py-clob-client](https://github.com/Polymarket/py-clob-client) | Python | 官方 CLOB 客户端 (PyPI: `polymarket-apis`) |
| [rs-clob-client](https://github.com/Polymarket/rs-clob-client) | Rust | Rust 客户端，模块化 `clob` + `ws` features |
| python-order-utils | Python | 订单生成和签名工具 |

### 2.2 社区重点项目

| 项目 | 语言 | 策略特点 |
|------|------|----------|
| [Fully-Autonomous-Polymarket-AI-Trading-Bot](https://github.com/dylanpersonguy/Fully-Autonomous-Polymarket-AI-Trading-Bot) | TypeScript | 多模型集成 (GPT-4o, Claude, Gemini)，15+ 风控检查，分数 Kelly 仓位，鲸鱼追踪 |
| [Polymarket-Trading-Bot](https://github.com/dylanpersonguy/Polymarket-Trading-Bot) | TypeScript (53K+ 行) | 7种策略: 套利、收敛、做市、动量、AI预测; 鲸鱼追踪, Paper Trading |
| [polybot](https://github.com/ent0n29/polybot) | Java 21 | 多服务架构: 策略运行时、做市、ClickHouse 数据入库、量化分析 |
| [poly-maker](https://github.com/warproxxx/poly-maker) | Python | 自动做市，双边流动性，Google Sheets 配置 |
| [polymarket-trading-bot](https://github.com/discountry/polymarket-trading-bot) | Python | 闪崩检测 (15分钟市场)，WebSocket 客户端，订单簿 TUI |
| [OctoBot-Prediction-Market](https://github.com/Drakkar-Software/OctoBot-Prediction-Market) | Python | 基于 OctoBot 平台，可视化 UI，跟单和套利 |

### 2.3 高性能框架
- **NautilusTrader** - 有 [Polymarket 集成](https://nautilustrader.io/docs/latest/integrations/polymarket/)，适合高性能算法交易
- **OpenClaw** - 基于 LLM 的自主 AI 代理框架

---

## 3. AI 新闻分析与情绪判断

### 3.1 行业实践

#### 新闻反应式交易
- AI 实时监控新闻和社交媒体
- 估计对特定预测市场的影响
- 在手动交易者反应之前交易
- 突发新闻可在**数秒内**被定价到市场

#### 概率估计
- 使用 GPT-4/Claude 分析复杂问题并估计事件概率
- 当 AI 估计概率与市场价格的差异 (edge) > ~5% 时交易

#### 情绪交易
- 分析 Reddit、Twitter/X、新闻网站的情绪变化
- 在情绪反映到市场价格之前交易

### 3.2 现有 AI 工具

| 工具 | 功能 |
|------|------|
| **Alphascope** | 每市场扫描 50+ 文章和数据源，过滤噪音，排名相关性，产出预测 |
| **PolyOracle** | 使用多个 LLM 达成共识预测 |
| **Polymarket Tips** | AI 驱动的实时社交媒体情绪分析 |
| **Polymarket Agents** (官方) | 集成 RAG、新闻检索、LLM 提示工程 |

### 3.3 学术研究发现

| 研究 | 关键发现 |
|------|----------|
| LLM 情绪准确性 | OPT (GPT-3 based) 对约100万条金融新闻达到 **74.4% 准确率**，优于 BERT (72.5%) 和 FinBERT (72.2%) |
| 基于情绪的交易 | 使用 OPT 情绪的多空策略达到 **Sharpe Ratio 3.05** |
| FinGPT | 结合新闻传播广度和上下文数据，股价预测准确性提升 **8%** |
| 情绪局限性 | 单独情绪对次日价格变动的解释力有限 (R² = 0.010)。负面情绪比正面情绪有更强的即时影响 |
| LiveTradeBench | 在高影响事件中持仓比基于弱信号频繁调仓效果更好 |

### 3.4 最佳实践
- LLM 作为**输入之一**，非唯一决策者 — 结合市场数据、民调、领域专长
- 使用 **Kelly Criterion** (通常半 Kelly) 进行仓位管理
- **新闻驱动策略** (识别未定价信息) 提供最高 edge
- 人类在领域专长、本地知识和新颖信息方面仍有优势

---

## 4. 风险管理关键发现

### 4.1 市场风险
- 预测市场流动性可能较低，大单容易滑点
- 部分市场结算标准模糊，存在争议风险 (UMA Oracle 争议)
- 市场可能受到操纵（鲸鱼效应）
- YES + NO 价格偏离 $1 时存在套利机会也是风险信号

### 4.2 技术风险
- API 速率限制: CLOB 订单 3,500 req/10s, 一般请求 9,000 req/10s
- WebSocket 断开后挂单自动取消
- 区块链网络拥堵时的交易延迟
- 钱包私钥安全 (需要 POLYGON_WALLET_PRIVATE_KEY)

### 4.3 合规风险
- 美国用户需通过 Polymarket US (CFTC 监管)
- 不同地区的法律合规要求
- KYC/AML 政策变化

---

## 5. 竞争优势分析

### 5.1 AI 交易者的优势
- **速度**: 突发新闻数秒内分析完毕并交易
- **规模**: 同时监控数百个市场
- **无情绪**: 避免人类的认知偏差
- **24/7**: 全天候监控市场和新闻
- **多模型集成**: 综合多个 AI 模型降低单一模型偏差

### 5.2 AI 交易者的劣势
- **黑天鹅事件**: 对前所未有的事件判断能力有限
- **讽刺/隐含信息**: 可能误解复杂的政治语境
- **领域深度**: 人类专家在特定领域有更深的理解
- **新颖信息**: AI 可能无法获取非公开信息
- **训练数据截止**: LLM 知识有时滞性

---

## 参考来源
- [Polymarket Endpoints Reference](https://docs.polymarket.com/quickstart/reference/endpoints)
- [Polymarket CLOB Introduction](https://docs.polymarket.com/developers/CLOB/introduction)
- [Polymarket WSS Overview](https://docs.polymarket.com/developers/CLOB/websocket/wss-overview)
- [Polymarket CTF Overview](https://docs.polymarket.com/developers/CTF/overview)
- [Polymarket API Architecture (Medium)](https://medium.com/@gwrx2005/the-polymarket-api-architecture-endpoints-and-use-cases-f1d88fa6c1bf)
- [Polymarket Rate Limits Guide](https://agentbets.ai/guides/polymarket-rate-limits-guide/)
- [Polymarket US API Available](https://www.quantvps.com/blog/polymarket-us-api-available)
- [Automated Trading on Polymarket](https://www.quantvps.com/blog/automated-trading-polymarket)
- [Polymarket/agents (GitHub)](https://github.com/Polymarket/agents)
- [Fully Autonomous AI Trading Bot (GitHub)](https://github.com/dylanpersonguy/Fully-Autonomous-Polymarket-AI-Trading-Bot)
- [AI Prediction Market Trading (Alphascope)](https://www.alphascope.app/blog/prediction-market-ai-trading)
- [Sentiment Trading with LLMs (ScienceDirect)](https://www.sciencedirect.com/science/article/pii/S1544612324002575)
- [Conditional Token Framework (Oboe)](https://oboe.com/learn/mastering-polymarket-clob-architecture-sr97oj/conditional-token-framework-1)
- [NautilusTrader Polymarket Integration](https://nautilustrader.io/docs/latest/integrations/polymarket/)
