# Current Experiment Plan

> 一句话总览:Exp2 调研 SENSE-O Intent API 2.0.4 如何表达建立 virtual network link 所需的网络条件，并将本组 workflow/science-SLA 模型与之 harmonize：已有能力直接复用，只扩展经字段审计确认真正缺失的部分。

## 目标

回答一个可验证的问题：**SENSE-O Intent API 2.0.4 已经能表达哪些 virtual network link 条件，本组 workflow/science-SLA 中哪些概念可以直接映射、哪些需要在 adapter 中推导、哪些才是 API 真正缺失的最小扩展？**

本轮标记为 **Exp2**；按项目 tag 约定，因其属于接口可行性探路而使用 `probe_sense_intent_harmonize`。调研正文位于 [`runs/20260826_181552_probe_sense_intent_harmonize_847b6e8/sense_o_intent_harmonization.md`](../runs/20260826_181552_probe_sense_intent_harmonize_847b6e8/sense_o_intent_harmonization.md)，不把 Markdown 产物散落到 `docs/`、`resources/` 或临时目录。

## 假设、预期观察与价值

- **待验证假设**:SENSE-O Intent API 2.0.4 已覆盖 virtual network link 的大部分网络侧原语（如端点、带宽、服务时段/生命周期和路径或拓扑约束）；本组不需要复制这些字段，主要工作应是一个 workflow/science-SLA → network intent 的薄适配层，以及少量经审计确认缺失的 workflow/campaign 语义与可追踪字段。
- **预期观察**:link capacity、端点绑定和网络路径类条件大多能够直接复用；workflow deadline、task/file deadline、priority 等上层语义更可能需要先推导成网络请求，或作为关联元数据保留，而不应未经验证就变成新的网络资源原语。
- **为什么值得做**:它会把“workflow/science-SLA 与网络 intent 如何衔接”收敛为逐字段、可读回验证的接口契约，避免重复造 schema，并给后续 digital twin 原型一个最小而明确的边界。

以上仍是**实验前假设，不是结论**；用户已于 2026-08-26 指示开始 Exp2，并明确要求本次纯调研不走代码实验流程，直接创建并维护 run 目录中的 Markdown。

## 输入与证据优先级

1. **SENSE-O Intent API 2.0.4 官方 OpenAPI/Swagger、官方文档及官方示例**：用于确定 API 的真实字段、类型、必填性、语义和返回状态；不以二手文章替代。
2. [`resources/slides/How to Describes a Workflow.pptx`](../resources/slides/How%20to%20Describes%20a%20Workflow.pptx)：本组 workflow/science-SLA 模型的权威输入。
3. `/Users/lxzhong/Documents/GitHub/paper_reader/knowledge/20260820_wfcommons.md`：补充设计理由和字段细节；与 PPT 不一致时以 PPT 为准。

已确认的权威解释口径：bandwidth/latency 的**网络能力与观测值**分别属于 platform/execution；面向具体文件的“所需 bandwidth/latency”由文件大小、deadline 和拓扑条件推导，不重复声明为彼此矛盾的独立真值。

## 产物结构与验收标准

主产物 `sense_o_intent_harmonization.md` 至少包含：

1. **API 事实表**：逐项记录与 virtual network link 建立有关的 request/response 字段、JSON 路径、类型、必填性、官方语义和证据链接。
2. **逐字段 crosswalk**：把 PPT 定义的 WfFormat、WfPlatform、WfCampaign 概念分别归类为：直接复用 SENSE-O 字段、由 adapter 推导后写入现有字段、确认缺失需最小扩展、不属于 network intent API 的职责。
3. **最小扩展清单**：每个扩展必须写明 owner/schema、语义、类型与基数、为何现有字段/推导不足，以及应从何处 read back 或验证；没有证据的候选项不得进入最终扩展集。
4. **端到端例子**：把 PPT 中 APS → ANL → ORNL 的 workflow/campaign 场景翻译成一份 SENSE-O intent 示例，并标出所有推导步骤和扩展字段。
5. **边界与未决项**：明确哪些结论来自 2.0.4 schema，哪些依赖部署实现或仍需向 SENSE 团队确认。

验收底线：不新增任何已能直接表达或可靠推导的字段；所有直接映射和缺口判断均能回链到官方 API 证据及 PPT 中的 science-SLA 概念。

## 可行性与风险

- **版本漂移**:必须锁定 2.0.4；其他版本资料只能作为背景，不能混入字段结论。
- **schema 与实现不等价**:OpenAPI 能证明接口声明，不能自动证明具体部署行为；实现能力需单列为待实测或待确认项。
- **层次混淆**:workflow 约束、campaign 决策、network intent、execution observation 必须分层，不能把上层 deadline 机械复制为链路原语。
- **本次流程例外**:经用户明确指示，本次纯调研不创建 config/entry、不调用 `run_experiment.py`；直接创建唯一 run 目录并持续维护其中的 Markdown。该例外不修改项目骨架，也不自动推广到其他实验。
- **登记时点**:调研结题时再补齐同一 run 的 `description.txt`、`metrics.json`、必要的证据说明和 `EXPERIMENTS.md` 记录；研究过程中不把阶段性判断伪装成已完成实验结论。

## 步骤与进度

- [x] **S0 — 对齐**:用户指定 Exp2 研究问题、输入优先级和 run 内 Markdown 产物规则，并于 2026-08-26 明确要求纯调研直接写 run、不走代码流程。
- [x] **S1 — 初始化**:已直接创建唯一正式 run 与 `sense_o_intent_harmonization.md`；未创建 config/entry。
- [x] **S2 — API schema 审计**:已锁定并在 run 内固化官方 2.0.4 OpenAPI，完成 virtual network link 相关字段、生命周期、discovery 与 read-back 的第一次审计。
- [x] **S3 — science-SLA 基线**:已按 PPT 优先原则整理 WfFormat/WfPlatform/WfCampaign 中需要与 network intent 相接的概念。
- [ ] **S4 — harmonization crosswalk**:完成四分类映射并提出有证据的最小扩展集。
- [ ] **S5 — 端到端验证**:完成 APS → ANL → ORNL 示例，检查每个输入条件的来源、变换和可读回结果。
- [ ] **S6 — 复核**:独立重做一次字段覆盖检查；关键缺口只有在重复审计一致后才可标记为 ✅有效。
- [ ] **S7 — 结题**:通过入口 finalize，登记客观结果和 verdict；更新本计划的当前状态并停下等待用户决定下一步。

## 待办与决策

- **TODO(待验证/执行)**:SENSE-O 2.0.4 的官方 schema 入口与 virtual network link 创建操作的准确名称。
- **TODO(待验证/执行)**:哪些 science-SLA 概念属于直接复用、adapter 推导、真正缺失或职责外。

## 当前状态

**Exp2 S0–S3 已完成，S4 第一轮 crosswalk 已写入、等待共同审阅。** 官方 2.0.4 OpenAPI 及其 SHA-256 已固化在唯一 run；当前只形成阶段性观察与候选缺口，尚未完成第二次复核，未标记 ✅结论。

## 实验历史

- **Exp1（已结题，2026-07-28—2026-08-26）**:AI 驱动科学实验、autonomous experimentation、self-driving laboratory、digital twin、实验选择、设备控制、科学工作流、AI agent 与相关系统平台的背景调研；不运行实验。归档见 [`20260826_probe_landscape_exp1.md`](archive/20260826_probe_landscape_exp1.md)。
- **Exp2（进行中，始于 2026-08-26）**:调研 SENSE-O Intent API 2.0.4 对 virtual network link 条件的表达能力，并与本组 workflow/science-SLA 模型 harmonize；S0 已完成，尚无实验结论。
