# Polymarket AI Trading System - Practical Implementation Details

## Last Updated: 2026-03-29

---

## 1. 钱包设置与 API 认证 (关键起步步骤)

### 1.1 安装
```bash
pip install py-clob-client
# 注意: 需要固定 web3==6.14.0 避免依赖冲突
pip install web3==6.14.0
```

### 1.2 签名类型
| 类型 | signature_type | 说明 |
|------|---------------|------|
| EOA (推荐机器人用) | 0 | MetaMask / 硬件钱包的私钥 |
| Email / Magic 钱包 | 1 | 需要额外的 `funder` 地址 |
| 浏览器钱包代理 | 2 | Gnosis Safe |

### 1.3 EOA 钱包认证代码 (最常用)
```python
from py_clob_client.client import ClobClient

client = ClobClient(
    "https://clob.polymarket.com",
    key=PRIVATE_KEY,       # 不带 0x 前缀
    chain_id=137,          # Polygon 主网
    signature_type=0
)
# 创建或派生 API 凭证
client.set_api_creds(client.create_or_derive_api_creds())
```

### 1.4 必须的初始化步骤
1. 创建 Polygon 钱包 (EOA)
2. 向钱包转入 MATIC (gas费) 和 USDC.e
3. **设置代币授权** (一次性): USDC + 条件代币 → Exchange 合约
4. 通过 `create_or_derive_api_creds()` 获取 API 凭证
5. 存储 `PK`, `API_KEY`, `API_SECRET`, `API_PASSPHRASE` 到 `.env`

### 1.5 重要注意
- **py-clob-client 不兼容 Polymarket US** (`api.polymarket.us` 使用 Ed25519 认证)
- 私钥**绝不**提交到 git
- CLOB 使用 EIP-712 签名消息; 订单匹配链下进行，结算链上

---

## 2. Paper Trading 方案 (无官方测试网)

### 2.1 现实: 没有官方测试网
Polymarket **只运行在 Polygon 主网** (chain ID 137)，没有沙盒环境。

### 2.2 替代方案

| 方案 | 说明 | 推荐度 |
|------|------|--------|
| **DIY Mock Layer** | 运行所有逻辑但跳过实际交易提交 | ⭐⭐⭐⭐⭐ 最推荐 |
| **PolySimulator** (polysimulator.com) | $1k 虚拟余额，实时赔率 | ⭐⭐⭐⭐ |
| **Polymarket Paper Trader (Termo)** | 针对真实订单簿执行，模拟滑点和费用 | ⭐⭐⭐⭐ |
| **Manifold Markets** | 游戏币 (Mana) 环境，开放 API，适合原型验证 | ⭐⭐⭐ |
| **Kalshi Sandbox** (`demo-api.kalshi.com`) | 竞争平台的完整沙盒 | ⭐⭐ |

### 2.3 推荐策略
1. **第1周**: DIY Mock Layer — 记录所有"假"交易到数据库
2. **第2周**: 对比 Mock 交易结果 vs 实际市场走势，验证 edge
3. **第3周**: 极小额实盘 ($5-10/笔)
4. **渐进放大**: 验证盈利后逐步增加仓位

---

## 3. 成本预算详细估算

### 3.1 Gas 费 (Polygon)
- 单笔交易: **$0.01 - $0.20** (通常有 meta-transaction 补贴)
- 存取款: **$0.02 - $0.05**
- 20笔/天 ≈ **$1-4/天**

### 3.2 Taker 手续费 (2026年3月)
- **最高 1.80%** (概率50%时)，向两端递减
- 高频加密市场: 峰值 ~1.56% @ $0.50
- 体育/宏观市场: ~0.25% (beta试点)
- **Maker 返佣**: Taker 费用的 25-50% 返还给限价单挂单者
- Polymarket US: 0.30% taker, 0.20% maker 返佣

### 3.3 LLM API 费用 (月度)
| 使用级别 | 模型 | 预估月费 |
|----------|------|----------|
| 轻度 (1K 调用/月) | Haiku 4.5 / GPT-4o-mini | **$1-5** |
| 中度 (10K 调用/月) | Sonnet 4.6 / GPT-4o | **$30-150** |
| 重度 (100K 调用/月) | Sonnet 4.6 / GPT-5.2 | **$300-1,500** |

**省钱策略**:
- **Prompt Caching**: 节省 50-90% 输入成本
- **模型路由**: 便宜模型做解析，贵模型做推理
- **Batch API**: 额外 50% 折扣

### 3.4 新闻/数据 API
- 免费层: NewsAPI (100 req/天), GDELT (免费), RSS (免费)
- 付费: NewsAPI Pro $50-200/月

### 3.5 总月度预算汇总

| 级别 | LLM | 新闻 | Gas+手续费 | 服务器 | 合计 |
|------|-----|------|------------|--------|------|
| **入门** | $5 | $0 | $30 | $0 (本地) | **~$35/月** |
| **中等** | $100 | $50 | $100 | $20 (VPS) | **~$270/月** |
| **专业** | $500 | $200 | $500 | $100 (云) | **~$1,300/月** |

---

## 4. Kelly Criterion 与 Edge 阈值 (实战参数)

### 4.1 核心公式
```python
edge = ai_estimated_probability - market_price
kelly_fraction = edge / (1 - market_price)
position_size = kelly_fraction * fraction_multiplier * bankroll
```

### 4.2 分数 Kelly (行业标准)
- **Full Kelly 太激进** — 大多数机器人使用 **10-50% Kelly**
- 半 Kelly (alpha=0.5): 达到 ~75% 的 Full Kelly 增长率，但只有 ~25% 的波动
- 实战示例: `kelly * 0.15 * bankroll`, 硬性上限为资金的 5% 和 $75-100/笔

### 4.3 不同场景的 Edge 阈值

| 市场类型 | 最低 Edge 阈值 | 说明 |
|----------|---------------|------|
| 加密货币信号 | **2%** | 快速变化、高流动性 |
| 新闻驱动 | **5%** | 通用推荐值 |
| 天气/小众市场 | **8%** | 不确定性更大 |
| 保守策略 | **20%** | 某些仪表盘系统使用 |

### 4.4 预期绩效基准 (系统化策略)
- 年化回报: 15-25%
- Sharpe Ratio: 2.0-2.8
- 胜率: 52-58%
- 平均每笔 Edge: 2-4%

### 4.5 风控硬限制
- **20% 最大回撤停止交易**
- Kelly ≤ 0 时不下注 (无感知 edge)
- 单个仓位永不超过资金的 5%

---

## 5. 反机器人措施 (好消息: 官方支持)

### 5.1 Polymarket **明确支持**自动化交易
- 官方提供 MIT 许可的开源框架 [Polymarket/agents](https://github.com/Polymarket/agents)
- **Builder Program**: 提供更高速率限制、交易量奖励、通过 Relayer Client 免 gas 交易

### 5.2 限制措施 (非禁止，而是控制)
| 措施 | 详情 |
|------|------|
| 速率限制 | POST /order: 3,500/10s burst, 36,000/10min (~60/s avg) |
| 流量管理 | Cloudflare 排队加延迟 (非直接拒绝), HTTP 429 仅作最后手段 |
| Taker 费用 | 2026年1-2月引入，天然抑制高频交易 |
| 延迟调整 | 限制纯速度优势 |

### 5.3 竞争现实
- OpenClaw 机器人一周内产生 $115K 收入
- 某机器人 ("0x8dxd") 通过 20,000+ 笔交易赚取 $1.7M+
- **但**: 只有 0.51% 的 Polymarket 用户赚取超过 $1,000 — 竞争极其激烈

---

## 6. 订单约束

### 6.1 最小/最大限制
- **无明确最小订单量** — SDK 示例显示可低至 **5 shares**
- **无明确最大持仓限制** — 受可用 USDC 余额约束
- 实际最小值受手续费制约 (太小的订单不经济)

### 6.2 计算公式
```python
max_order_size = balance - sum(open_order_size - filled_amount)
```

### 6.3 关键约束
- 股票价格始终在 **$0.00 - $1.00** 之间
- 所有订单都是限价单 (可通过 FOK/FAK 模拟市价单)
- 订单类型: **GTC** (Good-Til-Cancelled), **FOK** (Fill-Or-Kill), **FAK** (Fill-And-Kill)
- 大单会移动价格 — 下单前必须检查订单簿深度
- 全部余额可被挂单预留，阻止同一市场的新订单

---

## 参考来源
- [py-clob-client GitHub](https://github.com/Polymarket/py-clob-client)
- [Polymarket Quickstart Docs](https://docs.polymarket.com/developers/CLOB/quickstart)
- [AgentBets API Guide](https://agentbets.ai/guides/polymarket-api-guide/)
- [PolySimulator](https://polysimulator.com)
- [Polymarket Fees Docs](https://docs.polymarket.com/trading/fees)
- [LLM API Cost Comparison](https://inventivehq.com/blog/llm-api-cost-comparison)
- [Kelly Criterion in Prediction Markets (arXiv)](https://arxiv.org/html/2412.14144v1)
- [Polymarket Rate Limits Docs](https://docs.polymarket.com/quickstart/introduction/rate-limits)
- [Polymarket Orders Docs](https://docs.polymarket.com/developers/CLOB/orders/orders)
