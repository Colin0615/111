# findings.md

## 技能使用与安装（状态）
- 通过 skill-installer 尝试从 GitHub 安装 `obra/superpowers`、`othmanadi/planning-with-files`、`karpathy/autoresearch`。
- 环境到 github.com / raw.githubusercontent.com 的 CONNECT 隧道返回 403，导致自动安装失败。
- 采用能力映射继续执行：
  - planning-with-files：三文件计划驱动（task_plan/findings/progress）。
  - superpowers：规格→计划→执行→复审流程。
  - autoresearch：假设驱动实验与版本晋升机制。

## 深度研究参考（核心）
1. Polymarket Trading Overview（CLOB 架构、鉴权、SDK）：
   - https://docs.polymarket.com/trading/overview
2. Polymarket Fees（类别化费率、2026-03-30 新参数、费用公式）：
   - https://docs.polymarket.com/trading/fees
3. Polymarket Geographic Restrictions（受限地区与VPN条款）：
   - https://help.polymarket.com/en/articles/13364163-geographic-restrictions
4. Queue Imbalance as one-tick-ahead predictor（LOB 微结构信号）：
   - https://arxiv.org/abs/1512.03492
5. Deep Order Flow Imbalance（深层订单流不平衡）：
   - https://arxiv.org/abs/1708.02715
6. MANA-Net（新闻情绪聚合同质化问题与加权方法）：
   - https://arxiv.org/abs/2409.05698

## 关键结论
- 策略必须按市场类别建模交易成本，不可把手续费当常数。
- 小资金策略的第一原则是“执行质量优先”，否则理论 alpha 会被滑点和费用吃掉。
- 情绪模型要做来源可信度与时间衰减；盘口模型要看深度结构，不仅看 top-of-book。

- LLM 最佳实践不是“全替代”，而是用于事件理解/复盘归因等高语义模块；风控与执行需确定性硬规则。
