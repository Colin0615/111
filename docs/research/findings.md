# Polymarket AI Trading System - Research Findings

## Last Updated: 2026-03-29

---

## 1. Polymarket 平台架构

### 1.1 基础设施
- **区块链**: Polygon (Matic) - 低gas费、高吞吐量
- **结算代币**: USDC (USD Coin)
- **交易机制**: CLOB (Central Limit Order Book) - 中心化限价订单簿
- **条件代币框架**: Gnosis Conditional Token Framework (CTF)
- **每个市场**: 二元结果 (YES/NO)，每个结果对应一个 ERC-1155 条件代币

### 1.2 Polymarket CLOB API
- **Base URL**: `https://clob.polymarket.com`
- **关键端点**:
  - `GET /markets` - 获取所有活跃市场
  - `GET /book` - 获取特定市场的订单簿
  - `GET /price` - 获取最新价格
  - `GET /trades` - 获取最近成交记录
  - `POST /order` - 提交限价订单
  - `DELETE /order` - 取消订单
  - `GET /positions` - 查询持仓
- **WebSocket**: 实时价格/订单簿推送
- **认证**: API Key + Secret, HMAC签名

### 1.3 Polymarket Gamma API
- **用途**: 获取市场元数据、描述、分辨率来源等
- **Base URL**: `https://gamma-api.polymarket.com`
- **关键端点**:
  - `GET /markets` - 市场列表及详细描述
  - `GET /events` - 事件分组

### 1.4 交易流程
1. 用户存入 USDC 到 Polygon 钱包
2. 批准 USDC 给 CTF Exchange 合约
3. 通过 CLOB API 提交买/卖订单
4. 订单匹配后，获得条件代币 (YES/NO token)
5. 市场结算后，胜方代币可兑换 $1 USDC

---

## 2. 已有开源工具和框架

### 2.1 官方 SDK
- **py-clob-client**: Polymarket 官方 Python CLOB 客户端
  - GitHub: `https://github.com/Polymarket/py-clob-client`
  - 功能: 订单管理、市场数据、WebSocket
- **clob-client (JS/TS)**: JavaScript/TypeScript 版本
  - GitHub: `https://github.com/Polymarket/clob-client`

### 2.2 社区项目
- **polymarket-trading-bot**: 社区开发的交易机器人框架
- **prediction-market-agent**: 基于 AI agent 的预测市场交易
- **omen-agent**: 针对 Omen/Polymarket 的 AI 交易代理

### 2.3 相关工具
- **CCXT**: 加密货币交易所统一 API (可参考架构)
- **LangChain/LlamaIndex**: LLM 编排框架，适合构建新闻分析链
- **CrewAI**: 多代理协作框架

---

## 3. AI 新闻分析与情绪判断

### 3.1 新闻源
- **主流媒体 API**: NewsAPI, GDELT, Reuters API
- **社交媒体**: Twitter/X API, Reddit API
- **加密新闻**: CoinDesk, The Block, CoinTelegraph RSS
- **政治新闻**: Politico, FiveThirtyEight, RealClearPolitics
- **专业数据**: 体育赛事 API, 天气 API, 经济数据 API

### 3.2 AI 情绪分析方法
- **LLM 直接分析**: 使用 Claude/GPT-4 直接分析新闻文本，判断对事件结果的影响
- **结构化提示工程**: 设计专门的 prompt 模板，让 LLM 输出概率评估
- **多源交叉验证**: 综合多个新闻源的信息，减少单一来源偏差
- **历史校准**: 对比 AI 预测与市场价格的历史偏差，持续优化

### 3.3 概率估计方法
- **超级预测者方法**: 参考 Philip Tetlock 的超级预测框架
- **贝叶斯更新**: 基于新信息持续更新概率估计
- **集成方法**: 多个 AI 模型的预测取加权平均

---

## 4. 风险管理关键发现

### 4.1 市场风险
- 预测市场流动性可能较低，大单容易滑点
- 部分市场结算标准模糊，存在争议风险
- 市场可能受到操纵（鲸鱼效应）

### 4.2 技术风险
- API 速率限制和可用性
- 区块链网络拥堵时的交易延迟
- 钱包私钥安全

### 4.3 合规风险
- 不同地区的法律合规要求
- KYC/AML 政策变化
- 监管不确定性

---

## 5. 竞争优势分析

### 5.1 AI 交易者的优势
- **速度**: 快速处理大量新闻和数据
- **无情绪**: 避免人类的认知偏差
- **24/7**: 全天候监控市场和新闻
- **多市场**: 同时监控数百个市场

### 5.2 AI 交易者的劣势
- **黑天鹅事件**: 对前所未有的事件判断能力有限
- **讽刺/隐含信息**: 可能误解复杂的政治语境
- **市场微观结构**: 对流动性变化的适应能力
- **训练数据截止**: LLM 知识有时滞性
