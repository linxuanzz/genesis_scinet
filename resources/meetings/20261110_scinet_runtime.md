# 2026-11-10 SciNet 会议：SC Demo、Gate 指标、Foundation Model 与 Runtime 进展

> **日期**：2026-11-10，按用户指定文件名及“今天”记录。
>
> **材料与可靠性**：用户提供的英文自动转录，没有时间戳或可靠 speaker labels。按语境识别主要发言人为 Mariam、KK、Aroan/Aaron、Rafael、SB 和 Linxuan；部分插话无法可靠署名。人名、平台名、指标定义及代码状态以会上说法整理，不替代回听、proposal 原文或部署验证。附录保留完整转录。
>
> **记录重点**：保留各方进展及评论，尤其区分演示目标、已展示能力、proposal 中的数值目标与已验证结果。标题虽含 runtime，本次实际重点还包括 SC slides/demo、gate metrics、数据和模型、Phase 2 合作。
>
> **关联记录**：[11 月 4 日 NDT 集成讨论](20261104_withmariamkk.md)、[11 月 9 日组会 runtime 反馈](20261109_runtime.md)、[Telemetry Agent 代码检查](../notes/20261109_checktelemetryagent.md)。

## 一 核心摘要

1. **SC demo 采用少量 slides 加局部软件演示。** Mariam 将分享可共同编辑的链接，先送 ORNL 审批，再持续更新；UCR 准备一个带动画的 Network/Telemetry 展示页，可分三步展示架构、功能、一次小运行的输出。
2. **Aroan 展示 RPyC 跨 Python 进程调用。** 上下两个进程分别代表 VM 内部与外部 agent，演示远程调用和输出。尚未展示真实 VIT 的 topology/bandwidth 查询；KK 希望补上一个有网络意义的查询和可见的 VIT topology。
3. **Gate 1/2 的实现草案来自 Mariam 的梳理和 ChatGPT 辅助。** HEP workflow 与分布式 AI training 分别拟做 baseline→加入 agents→再比较；这些是待实现骨架，不是达标报告。
4. **KK 明确警惕 overpromising。** 25% 完成时间下降、GPU 利用率升至 80%、15% training overhead 改善等数字尚无 baseline 和算法支撑；建议先描述改善方向，再在更有把握后补具体幅度，并考虑与 PM 澄清目标。
5. **Rafael 计划在 Frontier 跑 workflow benchmarks，收集执行数据。** 数据既用于建立 baseline，也可能支撑后续模型。Mariam 希望构建理解 science workflow、网络和 compute 的 foundation model；模型架构、训练分工和三月交付范围尚未定。
6. **Telemetry 三部分已推共享仓库，runtime 大部分实现但仍需修改。** SB 正在增加 flexible averaging 与订阅通知；Network Agent 当前关注本地反应，超出 deadline 后与 scheduler 的协商尚未实现。本次没有正式 runtime demo。
7. **下周因 SC 跳过例会。** 下次会上再展示更多集成进展。Phase 2 合作方继续筛选，讨论 UETN/Utah 和 FABRIC，不能只围绕 ESnet 等待。

## 二 开场与 SC 日程、slides 形式

开场 KK 说，Linxuan 正在扩展 Network Agent 对运行时状态变化的反应，但今天没有正式 presentation。Mariam 原本想重点讨论 Supercomputing 的 slides 和 demo，已经有一个 slides 框架，会在会后发链接供所有人编辑。

有人提到 Harvey 可能缺席；转录没有可靠的完整参会名单。Mariam 也说仍在处理最后一批合同材料，HPE 相关材料已经有进展，另有人表示刚签字确认；本次没有逐一确认全部合同的最终生效状态。

Mariam 回顾 SC 的安排：

| 项目 | 会上说法 | 按本次日期推算 |
| --- | --- | --- |
| Presentation / workshop talk | Sunday | 2026-11-15 |
| NRE demo | Tuesday | 2026-11-17 |
| DOE booth | 同为 Tuesday | 2026-11-17 |
| 另一场 NRE demo | Wednesday | 2026-11-18 |

日期为对会上相对日期的推算，不是本次重新核实过的正式日程；转录没有给出具体时段。

她建议 demo slides 大致包含：

- 两页项目整体介绍。
- 一页介绍四个 gate metrics 及含义。
- 一页展示与 digital twin 的交互。
- 一页展示 UCR 的 Network Agent 与 Telemetry Agent。

她说 demo 通常只要约五页，再展示软件即可；上面口头列出的内容合计可能超过五页，“五页”应理解为大致规模，而非已经锁定的页数。

## 三 Aroan 的 RPyC 演示及反馈

### 3.1 本次实际展示了什么

Aroan 共享上下两个 Python 运行窗口，先调整字号。有人打趣说需要显微镜看，再要求放大，随后开始演示。

他明确说：**先假装上面的 Python 是 VM 内代码，下面的是 VM 外 agent**。演示内容为：

1. 安装一个依赖 RPyC（转录为 `our pie C` 等）。
2. 用少量初始化代码启动 server，并放到后台线程，使上面的 Python 进程可以继续做其他事。
3. 下方进程连接 server，指定端口。
4. 从远端进程取得 Python module/object；示例类似远端 `sys` 模块。
5. 在下方调用远端写 stdout 的函数，`hello world` 出现在上方窗口。
6. 说明只要远端定义了目标函数，外部调用后就可在远端执行，并取回返回值。

现场有使用命令历史、打字及焦点切换的小插曲，但不影响演示的基本结论。

**已展示的是两个 Python 进程之间的远程调用机制；没有展示实际 VIT 内部已经运行并返回网络数据。** 也没有执行资源 reserve/commit 或完整 agent 集成。

### 3.2 KK 希望补一个有网络含义的例子

KK 问，能否让 twin 回答一个简单、有意义的问题，例如：

- topology 中 node A 到 node Z 是否连通？
- 中间经过哪些 links？
- 即使不 reserve resources，能否先展示查询结果？

Aroan 说明，通信层面只需在远端定义相应函数，下方调用就能返回结果。KK 认可调用机制，但想把上方换成一个确实有网络意义的 twin，让下方 agent 查询；然后再介绍 UCR Network Agent 在这个简单客户端之上增加的功能。

Mariam 也希望画面中能看到 VIT/topology，明确观众正在与哪个网络交互；她赞同 topology 或两节点间 bandwidth 查询作为 demo。

### 3.3 VM 边界、远程运行和 API 的范围

Aroan 解释，可以在实际 VM 中准备一个小型 Python API，包含需要查询/设置的函数；外部连接后调用即可。除了读取，也可以远程修改环境。他用“shoot your foot level of power”形容这种机制权限很大、几乎什么都能做；本次没有据此确定生产环境的权限控制设计。

KK 指出，最终 twin 可能在另一台机器上，Network Agent 到 twin 应通过 RPC 一类方式交互，甚至提到把函数调用映射成 gRPC。Aroan 回答，RPyC 不要求同机，也可连接其他主机。

应区分：**当前演示用的是 RPyC；gRPC 是讨论中的另一种表述/可能方向，不是已展示的实现。** 也没有确定所有未来 twin 必须共享同一种 API。

## 四 UCR 的 SC 展示：一个动画页，分三步讲

KK 对 Mariam 说，此前不知道还要准备相应材料，所以暂未做专门的 slides；可以补做。他询问是只要介绍页，还是像此前那样实际运行 Network Agent 代码。

讨论倾向于降低现场运行依赖：用一个动画页展示，也可以使用视频/已录下的运行输出。口头说是“一页”，实际通过三次动画呈现三层内容：

1. **总体架构**。
2. **Network Agent 已有功能/操作列表**，每项一行。
3. **一个小运行的滚动输出/执行过程**，类似 Linxuan 之前演示的内容。

目的在于保留运行流程的可理解性，同时减少现场程序没跑通的风险；动画本身不作为新的实测或指标达成证据。

交付时间的讨论先出现“接下来两天”等说法，随后对齐到 SC 前的 Sunday；KK 表示到那时肯定能准备好。Mariam 提醒 ORNL 需要审批，因此会先取 Linxuan 以前 presentation 的一页展示 Network Agent，**当天先送审批**，之后仍可在实际 demo 前改进。

会末她说会发 talk/paper 和 demo slides 的链接，相关材料预计周六要上传。原文对“paper/slides”对象的指代不够明确，因此不据此恢复新的论文投稿 deadline；按日期推算该周六为 **2026-11-14**。

## 五 Gate metrics：项目验收指标，不是网络监控指标

### 5.1 为什么拿出来讨论

Mariam 已与 Rafael 讨论，先做了 gate 1、gate 2 的流程页，还会补 gate 3、gate 4，再发给团队评论。

KK 一开始以为这些内容都要公开放进 SC slides，问为何要向所有人讲项目被怎样衡量。Mariam 澄清：此处已从 SC demo 转到 **Phase 2 / 项目 gate 准备**；PM 也会来 SC，因此可以准备备用材料，也希望先与团队核对。

她特别说明这里的 metrics 是衡量项目进展/成果的四个 gates，**不是 link utilization、loss 等网络 telemetry metrics**。

共享屏幕时出现双屏/Presenter View 问题，KK 提醒换成真正的幻灯片视图；Mariam 表示可以断开第二屏解决。

### 5.2 Gate 1：HEP workflow 的 baseline 与优化

Mariam 重述 proposal 中的目标：

- 完成时间减少约 **25%**。
- GPU 利用率从约 **50–60%** 提升到约 **80%**。

这些是会上重述的目标，**不是当前已经达到的测量值**。KK 立即问，是否已有 50–60% 的 baseline；他认为实际 GPU 利用率到 80% 很难，尤其按他对 NVIDIA GPU 使用效率的经验，应谨慎承诺。

Mariam 说 Harvey 已发来 HEP workflow 的细节，ORNL 正开始把它组织成 Workflow Agent。她通过 ChatGPT 辅助梳理出一条可能满足 gate 的流程：

```text
运行 baseline，收集数据
  → HEP/Workflow Agent 识别 workflow、依赖与优先级
  → Network Agent 预测网络需求
  → Compute Agent 识别/预测 GPU starvation
  → Resource Optimizer 计算 allocation
  → 在 VIT 上做资源预留、验证策略并执行
  → 再测 workflow，与 baseline 比较
```

这条图是实现草案；**没有显示上述所有 agents/optimizer 均已实现，也没有用数据证明达到 gate**。

KK 问 Workflow Agent 谁负责，得到 ORNL 正在做的回答。他提出，为先跑通一个 workflow，可以暂时绕过完整 scheduler，甚至先不处理多 workflow 的 deadline 调度，让 Workflow Agent 直接调用 Network Agent。UCR 负责 Network Agent，之后通过上周讨论的 adapter 转成 VIT commands，希望 Aroan 帮忙完成这一层。

### 5.3 Gate 2：分布式 AI training 与协调

Mariam 重述第二项中的数值目标：

| 目标 | 会上表述及边界 |
| --- | --- |
| Distributed training overhead | 约 **15% 改善/降低**；后文 KK 称 WAN overhead。具体分母和 baseline 尚未明确 |
| Latency | 低于 **200 ms**；具体被测操作/边界未在本次定义 |
| Coordination | 低于 **1 s**；没有提供当前实测结果 |

她展示的 AI 辅助架构大致为：

```text
AI Training Workflow Agent：要求与 deadline
  → Communication Agent：gradient exchange / synchronization
  → Network Coordination Agent：WAN 资源分配
  → 带宽调度
```

她说名称与流程可以继续修改，仍然要有 baseline 再比较优化效果。KK 提醒，目前连 agentic AI/distributed training baseline 长什么样都还没有明确，更不能仅凭架构图承诺能把 overhead 降低 15%。

### 5.4 KK 的核心评论：接口骨架不等于优化算法

KK 反复指出当前进展的层次：

- 团队主要在系统化 architecture，构建能与 VIT/网络通信和交互的 agents/APIs。
- 降低 WAN overhead、满足 latency 目标、提高 GPU 利用率还需要算法与优化。
- 这些优化工作由谁做、怎样做，尚未解决。
- 连 HEP workflow 都还没充分理解时，应先找出实际瓶颈和可优化环节，再估计改善幅度。

他担心 proposal 数字被听众理解成即将兑现的保证，用“不要把脖子伸得太长”来形容 overpromising 的风险。另有参会者补充，KK 并非反对追求改善，而是希望措辞更保守：可以先写“减少 overhead / completion time”，有可信 baseline 和结果后再填具体百分比。

Mariam 回应：数字确实写在 proposal 中，但可以先让系统工作，再逐步推动性能；她是在梳理如何满足 gates。她也会考虑与 PM 讨论、澄清改善目标。

**没有在会上正式修改 proposal 指标，也没有获得 PM 批准的新目标。**

## 六 Rafael 的 baseline 数据计划与 Foundation Model

### 6.1 Workflow benchmarks 与数据缺口

Rafael 介绍自己有一些 workflow benchmarks，计划在 **Frontier** 上运行，变化 workflow 大小、需求和场景，并用采集工具尽可能记录执行信息。工具名在转录中类似 `o stud`，无法可靠恢复。

他说会尝试本周开始，也可能下周继续，但下周有 SC，时间安排需看实际情况。数据可以形成基础知识/表征，为 baseline 及后续模型打基础。

Mariam 认为，与 Rafael 讨论后发现项目需要的 workflow training data 尚不现成，这是起初没有充分预料的工作：必须自己运行 jobs、构建新数据集。她认为可以向 PM 解释这一实际前置成本，并据此讨论 gates 的目标和进度。

本次是数据收集计划和数据缺口报告，**没有展示新数据集已经完成、baseline 已跑完或模型已训练**。

### 6.2 Mariam 设想的模型输入与作用

Mariam 提到 proposal 中有 foundation model 的方向。她设想输入包括：

- 科学实验及 workflow 结构。
- Jobs、datasets、dependencies。
- Network state。
- Compute/GPU state，包括 compute-bound 等运行情况。
- Operational state 和 failures。

希望模型学习 workload、network 和 compute 的表征，从 workflow 描述预测网络需求，在不同科学 workflows/facilities 间迁移知识，并解释依赖与网络性能问题。Agents 后续可以使用模型辅助决策。

她将 Rafael 即将运行的 workflow templates/benchmarks 视为训练材料来源，并提到 ORNL 有一位曾与她做过某个 foundation model 的人，SC 之后可能尝试邀请其参与。模型名转录类似 `Oc Net`，不强行确定正式名称。

有人问 foundation model 是否也必须三月前完成；Mariam 回答 proposal 提过这个方向，并认为它有助 agent 决策。**本次没有明确确认完整新模型必须在三月交付，也没有确定模型规模、训练方式和最终人员承诺。**

### 6.3 KK 如何理解与 Network Agent 的关系

KK 说，对 Network/Telemetry 来说，团队一直设想要能咨询一个理解 scientific intent、workflows 和 network 的 LLM。例如：

- 某次状态变化或链路 failure，对特定科学实验会有什么影响？
- 这种影响应怎样理解，能得到怎样的决策指导？

他把这看作未来 Network Agent 的 agentic 部分，因为当前主要仍是 APIs 和 rules。他欢迎有人思考模型支持，也表示 UCR 很难把所有工作都包下来。

这里还存在实现口径差异：Mariam 谈的是学习领域 workflow 表征的 foundation model；KK 说自己把它理解成可咨询的 generic LLM。**本次没有决定从零训练 foundation model、微调现有 LLM、检索增强或其他具体路线，也没有把“数据收集由 Rafael 推进”自动等同于“全部模型训练已由 Rafael 承诺完成”。**

## 七 SB 的 Telemetry Agent 更新

学生汇报不使用 slides，仅用两三分钟说明本周做了什么、哪些代码已 checked in。

SB 说，按上周讨论的架构，三部分代码已推入共享 GitHub 仓库：

1. **Southbound**：使用 Telegraf，轮询 John 提供的 NRP Prometheus endpoint 中的一个示例 instance，获取接口最大容量及当前 TX/RX。
2. **Storage/cache**：将处理后的 metrics 写入 InfluxDB，供数据库与缓存读取。
3. **Northbound**：使用 LangGraph，根据 Network Agent 请求的 timestamp，从缓存/数据库提供链路容量。

他还在增加：

- 对不同指标做 **flexible averaging** 的请求接口。
- 订阅与通知，例如链路故障、congestion 或其他 downtime 时通知订阅 agent。

这些新接口的状态是 **正在开发**，不能记成已经发布。本次没有现场展示这些告警或平均窗口功能。

> **与代码核查的区分**：SB 口头说数据写入“cache 和 database”。此前独立 [代码检查](../notes/20261109_checktelemetryagent.md) 表明当前配置是写入 InfluxDB 表，由数据库维护 LVC。会议记录保留他的架构汇报，不据口述补成双写两套独立系统。本次没有重新 fetch 或重跑同事测试。

## 八 Linxuan 的 Network Agent Runtime 更新与 KK 补充

### 8.1 汇报内容

Linxuan 表示 runtime 大部分已实现，但仍需修改。主要流程为：

- 通过 Telemetry Agent 的订阅或周期性检查发现 deviation，例如 link damage/failure、congestion。
- 尝试本地修复，例如延长预留时间、提高预留速率。
- 将处理结果报告给 Scheduling Agent。

这段是实现/设计概述，不表示真实 Telemetry subscription 已经接通。SB 在前一段明确说通知接口仍在开发。

### 8.2 KK 强调局部调整与 scheduler 协商的边界

KK 用 deadline slack 解释本地反应：如果原来预估的完成时间比最终 deadline 提前很多，发生拥塞后，可以在允许范围内把完成时间向 deadline 延长。

如果情况恶化，超出这种本地余量，就需要与 scheduler negotiation。**这部分协商尚未做**。当前实现重点仍是收到 telemetry 通知或 query-response 后，对运行时状态变化做反应。

他说明，前一天讨论已经提出若干修改，所以代码还没全部整理好，今天没有 ready-to-show 的正式 demo。这里对应 [11 月 9 日 runtime 反馈](20261109_runtime.md)，但本次没有逐项重述、解决或验收之前对 borrow、raise rate、congestion reroute 等问题的意见。

### 8.3 展示安排

KK 说，如果离 SC 还有几周，也许可以把 Network 与 Telemetry 组合起来完整展示；目前至少已有代码，下一次机会可展示两者与 network emulator 的协作。

当发现下周例会取消后，他表示多一周可以做更多工作，在再下一次会议展示。没有承诺具体某天完成全部真实集成，也没有给出本次 runtime 性能数字。

## 九 下周停会与 SC 闲聊

大家确认下周因 SC **不召开例会**。按当前周推算，原周二对应 2026-11-17；没有在本次明确确认恢复日期。

KK 起初打趣问为什么星期二不能开会，其他人解释在 Chicago 参加会议有时差和大量活动，也希望能听报告、参与现场。有人开玩笑说“我们没你那么年轻”，还有坐着睡觉/躲人的轻松交流。

讨论提到 ESnet 和 SCinet 等现场事务；有参会者说自己今年不再负责那些工作，只当 observer。具体说话人无法可靠确定。

收尾时祝参会者旅途顺利。有人再次说自己不去 SC，最后一次去大约在 **1998 或 1999 年**，也谈到也许明年有机会再去。原文缺 speaker labels，不强行把所有旅行经历归给同一人；这一日期也不用于修正其他会议中“1999/2000”的回忆。

## 十 Phase 2 合作：UETN、真实网络数据与 FABRIC

Mariam 说已开始查看 Phase 1 获资助的 proposals/awardees，筛出可以考虑的 Phase 2 伙伴，会把名单发给大家，开始接触和协商。

她提到 **UETN，Utah 的教育/研究网络相关团队**，曾与他们在 OFC 做过 demo，所以有合作基础。会上有人问是否 University of Utah，得到肯定回应；口述混用了网络组织与大学，因此本文不把两者当成同一个正式机构。

她提到人员名类似 **Joe B、Daniel Le**，有人说 Joe 是 professor；拼写和职务未经核对。潜在价值是可以接触真实网络数据。

她认为，ESnet 对接方面存在困难，可以同时考虑其他 research networks。另有人指出，John 与团队也可帮助获得 **FABRIC** 数据/环境，不应只盯着 ESnet；如果 FABRIC 满足需要，就有很多可以开展的工作。此前尚未积极推动这一路线。

有人说，看过新公布的一批 Phase 2 名单，没有看到与本项目工作明显相似的团队。Mariam 说还找到一些可谈的 funded awardees，会继续分享。

**本次没有确认 UETN、University of Utah、FABRIC 或任何新伙伴已经加入，也没有决定正式替换 ESnet。** 当前只是扩大候选合作对象与数据来源。

## 十一 行动项与下一次需要确认的事

| 事项 | 负责人/对象 | 时间及状态 |
| --- | --- | --- |
| 分享 SC talk/demo slides 可编辑链接 | Mariam | 会后发送；允许团队继续修改 |
| 先用已有 Network Agent 页送 ORNL 审批 | Mariam | 计划当天先提交，之后仍可更新 |
| 准备架构→功能→小运行输出的三步动画页/视频材料 | UCR，KK/Linxuan 配合 | 争取 SC 前，口头对齐到 Sunday；未在本次提交成品 |
| 在 RPyC 机制上补 meaningful topology/bandwidth 查询，展示 twin 画面 | Aroan、Mariam，与 UCR 对齐 | 当前只展示通信，真实 VIT 查询待补 |
| 明确 Network Agent → VIT 的 adapter 调用 | Aroan 与相关开发者，UCR 提供网络侧操作 | 希望其协助；完整接口仍需实现 |
| 补 gate 3/4 的流程页并发团队评论 | Mariam | gate 1/2 仅为草案；未逐条验收 |
| 检查数值目标、baseline 和实际优化责任，必要时与 PM 澄清 | Mariam、KK、各模块负责人 | 未正式修改 proposal 或获批新目标 |
| 在 Frontier 跑不同 workflow/scenario 并收集执行数据 | Rafael | 尝试本周开始，后续受 SC 时间影响 |
| 明确 foundation model 的数据、方法、人员和 Phase 1 范围 | Mariam、Rafael及潜在 ORNL 合作者 | SC 后进一步讨论，未有确定模型交付承诺 |
| 开发 flexible averaging、subscription/notifications | SB | 正在做，未展示完成 |
| 按前一天反馈修改 runtime，准备后续展示 | Linxuan、KK | 主要流程已实现，仍需调整；scheduler negotiation 未做 |
| 下周跳过例会，后续会议再看更多集成进展 | 全组 | 因 SC 停会，恢复时间未正式确认 |
| 筛选并分享 Phase 2 合作名单，联系 UETN/FABRIC 等潜在数据来源 | Mariam、团队；John 可协助 FABRIC | 候选讨论，未形成新合作承诺 |

## 附录 A 术语、数字与归属校正

| 原始转录 | 本文处理 |
| --- | --- |
| Ling Shan / Lingan / link Sean | Linxuan，按项目语境整理 |
| Aaron | Aroan/Aaron，沿用用户此前称呼，不自行改人名拼写 |
| our pie C / ourice | RPyC；现场是远程 Python 进程调用示例，不是已接通 VIT |
| sys/cy module 等 | 按远程模块与 stdout 演示解释；不恢复转录未保留的完整代码 |
| theology / apology | topology |
| VIT / BIT / digital twent | VIT / digital twin；没有据此确认底层实现类型 |
| telegraph / influx TV / Langra | Telegraf / InfluxDB / LangGraph |
| round high stage | runtime stage |
| four gate metrics | 项目四个验收/进展 gates，非网络监测指标 |
| 25%、50–60%→80%、15%、200 ms、1 s | proposal/讨论目标，定义及 baseline 待核对，非实测结果 |
| workflowetcharks / o stud | workflow benchmarks 可辨认；数据采集工具名无法可靠恢复 |
| Oc Net foundation model | 模型名不确定，不补写正式名称 |
| UETN / University of Utah；Joe B / Daniel Le | 保留组织与人名的不确定性，不据口述核实正式关系或职务 |
| prototype 骨架、数据计划、foundation model | 分层记录，不把 API 能调用等同于优化达标或模型训练完成 |

## 附录 B 完整原始转录

以下保留用户提供的完整自动转录，包含重复、误识别与闲聊，用于核对整理内容；不添加虚构的逐句 speaker labels。

<details>
<summary>展开完整英文转录</summary>

```text
Steps on and Ling Shan has also been working on extending the capabilities in the network agent for real time operations in terms of reacting tools state changes so he can just say a little bit, but we don't have a formal presentation update today.


I actually wanted to talk about supercomputing slides, demo, all that to get the to do the demo stuff but I do have like some format of what the slides are going to look like editing please let us , I'll send a link after the meeting so everybody can then go in and start editing.


Okay, I think all is I hearts missing, right?


Something about Harvey is there I don't like some record so maybe he won't join he's usually there like two weeks before everything so I think he might not join okay then we can get started so okay so we're working through all the last bit of contracts um HB, also centered, thank you for that so I think we should be good.


I just signed off on it.


This is just a review of uh like what our data at SC um so Sunday is the presentation NRE demo is Tuesday and the uh doE Booth as well and then there is another NRE demo on Wednesday um so this is the format which I was thinking we could do for the devil so just have two slides on the whole project, just talk about what it is one slide on the four gate metrics and I have two slides to show later uh one slide on the four gate matrics and what they are, one slide on the interaction with the digital twin. Uh one slide on the UC River side work, the network agent and the telemetry agent. And that's it because so demos are usually five slides and then you show the software behind the scenes and that's it So this one on interaction with the digital twin is you something to show, do you want to show now I will probably do that pretty pretty quickly and easily here.


Okay, okay. Yeah so whatever you show whatever level, that's fine.


So I'll stop sharing.


Go ahead.


Okay, so I'm my window here . All right, so it's a good good size for everyone yeah so this is a demo yeah very small demo.


It's not it's very it should be fairly straightforward and easy stuff um so yeah let me know if anyone can't read this I can make it our make me need um concrete I need microscope better even more more little bit more please yeah okay good good good okay we'll go with that all right so basically actually let's uh let's make this area go.


It's a little better uh okay.


So basically the idea here is we're going to pretend that the python running on the top is the the the the code running inside our virtual machine um and then the the code running on the bottom is some agent outside of that that's trying to communicate with the agent on the inside. Is the yes so let's I'm just going to be using my history here. Um there we go.


So all that we need is we need a little bit of boiler plate.


I uh to start up a a thread in the background uh here we go and to this should be in a function right to just run a function yes so this is just simply uh oh uh maybe I should have mentioned um the one thing that uh the one dependency uh uh okay figure out that uh so oops it install.


So just run that, um and then you can get our pie C uh and that's that's what we we're using here. Um and that's going to start up a server in the background.


So we want to have that on a uh a thread simply so that we can still keep running our regular stuff and it'll go in the on the background . And then at this point we don't what too far up yeah, okay.


So now here we're going to make a thread and that will start the server like that. Now when we're down here, uh we can work ah I can't type There I go and then uh so we're going to connect and we need to specify the port number all right now we should be able to then say uh we can actually pull on the module so at this point we're already connected to the uh agent on the inside. Um I mean you're connected to this uh digital twin or yeah.


So uh so we' the bottom is already connected to the top.


We just don't have any output that I think I lost the focus.


There we go. Um so if I if I recall here equals uh here watch there we go. Um and now so so now ourice is basically the cy module from the remote uh python process at the top.


And so that means that we can now stay call the right function to right to to standard out for our little hello world and then just like that it's it's going up on the top.


And at that point, so the idea is that we can then basically just say ourist dot uh our function or whatever and it'll it'll actually run that on the remote side.


And that doesn's digital to tell you what is the connectivity between two nodes in its topology let us say from node A to node Z tell me what are the links or something like that is there some simple function you can show that the digital twin responds and says yeah this is what I have even if you're not deserving any resources or anything like that well that would been just be a function another deaf like we have a start server function up at the top.


We just have whatever function we want for quurring something or whatever defined in the python code uh appear um and uh we can, you know you know, maybe check something out of the apology or whatever and whatever that returns when we recall uh the same function down here uh then we get the results back down here.


Exactly.


So that's what I'm looking for to have something which is the top is a somewhat meaningful twin for a network and that the agent below is able to communicate with that network ator and then the next thing when we show we will talk a little bit about what are all the things that we have in our network agent, which would sort of be like flashing out your lower agent component good work so we also have like a window showing the VIT somewhere that shows that this is an apology we're talking to in this Aaron okay so so yeah, basically the the anything that we we we want for for functionality, we want to just make sure we have the relevant python code like if if we're not talking about connecting to the across the network, just have your own have this stuff on right within the same same system for the digital plan and everything on the act actual virtual machine we make all all of our own well well our own little miniature API for doing whatever we want there and then so long as we have a function that we can then call into, we can go down from the outside and then make a connection and then call those functions to get all of what we want.


And then that that way and we can go that can I can slice both ways.


So we can also, you know, you know, put we we can send things uh to the the top here so that if we want to change anything about the environment, we can actually set things remotely as well.


So we any communication we want to do between um the inside and outside, you know, crossing that VM boundary, we we can basically do with this this there's not this is this is this is very much the shoot your foot level of power.


We can pretty much do whatever we want . Yeah, but ultimately, what you want is the twin potentially to run on another nord and the digital twin uh is right now you're making it function calls maybe uh we would go from the uh network agent to the twin using the RPC calls or something so that it would translate almost directly from a function called to a GRPC call.


Yeah, I mean like we can it uh it doesn't have to be on the same system.


It can be any any any system anywhere.


Yeah. That's that's that's pretty much it that's it's be very, very simple very easy. Um hypostol one single package and then you're good to go.


Okay.


So yeah, so but I like K's suggestion so we should do some sort of a network pull between the two, like check theology or check current bandwidth between these two nodes.


So you are showing it talking to the VIT. So and that that could be the the demo of the the mock agent, the mock agent talking to the mock VIT kind of thing. And then we say here, this is what the real network agent might do.


Yeah, this is the extra intelligence we're adding now on top.


So for your slight that you're asking about the network and telemetry agent Miriam, I not prepared anything because we don't know needed to, but we can do uh but I was thinking it'll be a slide correct rather than the way that uh Aaron has shown the interactive was running his agent last time we could run his code also in uh say visual studio or something Should we?


I don't know about what what do you think would you uh like to have a slide just describing it with uh or or do you want to actually run it?


Maybe I can prepare some slides and you show some slide that means not slides one slide So you can put maybe some animation there so we can show the slide of what the architecture looks like animate it and then say here these are the sort of functions and then animated next step and show what you might have shown if you were running it Miriam.


So that way we limit the risks in terms of what runs and doesn't run and we show more or less as if it is the result of a run.


Like a video is fine fill up, but yeah.


So even though it's one slide, it's three slides in reality because of animation.


Yeah.


Okay.


So we show the overall architecture maybe, then just a list of the functions that uh uh Lingan has for the network agent with just one one line for each of those functions and then afterwards the third animation will be pop up the the thing as it scrolls the execution of one small little run that uh that Ling Sean has shown Okay that we you needed by when you need in next two days or something, right by Sunday Sunday Monday Sunday okay we'll get it ready by by then for sure.


So what I'll do I'll this format which I have so at orkate we need to submit it for approval so means we need to get it to you before that then what I'll do is I'll add like one slide fromyn's presentation over here to showcase the network agent. Um and submitted for approval today.


So that should do that process and then we can still update until the Arual demo.


Yeah.


Okay.


All right, good.


So that should be fine.


Okay, but this is the format um simple and uh yeah, it showcases some initial work.


Then uh I did some work on the gate metrics uh so I have prepared two gate metrics.


I discussed I also discussed some stuff with uh Raphael. Um So if you remember so uh this is the phase two preparations.


So these are the four gates that we have to show rics are not metrics in terms of network network metrics.


This is something to say how our project this is what we're being measured at, right?


To tell inputing we need to tell to the program manager, but why do we need to tell the world what we are doing?


No, this is not so I'm not talking about supercomputing.


So I've stopped here.


But I'm putting this just in case for because the program manager is going to come.


So if we want something to show her and I also want to discuss this with us . Um so these are the four gate metrics we had, um, which we had to like Okay.


Sorry.


Yeah.


So the first one is no, no no right now you are in you have two screens, right?


You have to flip the screen that you're sharing because I think you have a laptop and then you have a screen and you're showing the small window.


It's the presenters.


You rather than me disconnect the second screen. Okay.


So the first gate matrics, uh metric is the hep work flow that we are optimizing so we specifically said 25 percent reduction um GPU utilization rising from 50, 60 to 80%.


The second one is AI work flow using how many GPUs and then how much we are optimizing.


I will do two more slides for the third metric and fourth metric, but I want to show you what I did for the first two.


Yeah, for the first one riam uh is it that we are able to get GP utilization of 50 60% already I mean 80% utilization for the GPU is is a tall order, especially with the way N video uses its GPU it's so shitty that 80% utilization of the GPU might be very tough . So yeah, so let's discuss this gate metric so uh this is what I started working through. Um so the the thing is given above like um so the first thing is we run a baseline case we gather the data.


So Harvey already sent me details of what a head flow looks like so we'll start putting that together into like a workflow agent thing . So this is what I chat GPDed and it came out that this would actually satisfy this gate.


So the HEP agent identifies the workflow signs priorities.


So basically it understands and identifies what the dependencies are. It then talks to the network agent, the network agent predicts the demand Then the compute agent comes in, uh, it identifies or predicts where the GPU starvation will happen in this course. Uh then we have the resource optimizer that computes an allocation.


It makes all the reservations across the thing on the VIT and uh we can have a policy that gets validated uh and then you ex execute it.


So basically we show that executing on the network digital twin and then we do another measure of the workflow . So then we compare the baseline result with the optimization optimized result.


And that is gate one done.


Do you need to give all these numbers of 80%ization uh you have to show 25% reduction in completion time.


These numbers you have to make you have to actually commit to it is it I think we do because we said that in the proposal but maybe we show like some improvement and then see we push it afterwards like we at least get it working and then we keep pushing.


So the workflow agent who's going to do we're doing it at Oakange where we're starting to work on it. We can interface we were thinking of interfacing to ahed but we can bypass that for the moment because this is just one workflow that we are handling and maybe we don't even have to worry about deadlines and so on for scheduling.


And then just directly interface with the network agent for now. And then the network agent spits out with our primitives that we have that hopefully we'll have this little adapter that we talked about last week that will translate it to BIT comments, right?


So we will take care of the network agent and then interface that to the digital twent through the satapular that I'm I'm hoping Aaron will help with that adaptular.


So this is just gate one.


I also did another one for gate two uh gate two is a little bit more complicated because we said we will be improving agent AI workflows um so here we said we'll do improved 15% overhead of distributed training uh latency below 200 milliseconds coordination, uh below one second.


So this is the architecture it's spit out.


So the AI training workflow agent um synchronizes all the requirements and the deadlines.


It talks to the communication agent, so I think we can change this a bit as we write.


It calculates gradient exchange, synchronization.


That talks to the network coordination agent.


That does theAN resource allocation and then again, approved bandwidth scheduling.


So this is what it's currently spit out, but we can optimize this to to do this . Again, we'll have a baseline.


I'm looking more for making sure that we don't stick our neck out so much and try to minimize the amount of neck portion of the neck that would get chopped off because we're saying 15% ran overhead for training . We don't have a baseline yet of what that distributed training would look like for this agentic AI training.


I had a meeting with Raphael before uh and we were discussing on how we can get that.


So Raphael had some ideas.


They have some uh I don't know if he's still on um so basically, okay, so like.


So basically we have a bunch of this work flowetcharks that I could uh run on front tier, basically you know what next week because that's see, of course, but I could try to start running this week and then I'll run some next week and with different scenarios size of workflows requirements, and use a o stud to capture as many information as we could from the executions.


And then I'll try to build these um basic knowledge, you know, that could be used to to build a foundation of model.


So we'll get some idea of baseline, right?


Now, in most of what we have done so far on this project, it's basically creating functional agents that are basically doing the minimal EPIs for communicating with the VIT, not so much in terms of algorithms for making sure that we reduce the when obhead or making sure that we meet these latency targets so that requires algorithms and optimization to be done somewhere, right?


Question is who's going to do that how I think once we have the skeleton we can uh start putting more intelligence inside uh but this is like the basic basic skeleton I was trying to work out like how do we satisfy gate one Gate two, get three um So I only did for two gates so far. Um uh and then I'll do for the rest to gates and send it to you guys uh for comments. Um my my main comment and all this is how much risk we are taking with overpromising So we did this in the proposal So either we somehow say that uh so the good thing is what I found so far are talking to Rapel that this data doesn't exist . So the good thing is, we can say that once we started the project work flow training data didn't exist.


So we actually had to write, uh Raphael had to run jobs and we created a new data set.


So that is some thing leverage we can say that we didn't didn't anticipate before starting the project.


And so some of the gates have kind of changed.


I could talk to the program managerification of the goals of how much improvement we will achieve because this is still about first playing the groundwork for agentic capabilities for managing the network and multiple workflows, right soam KK is trying to say is that um um we shouldn't, for example, on your previous like, do you even have latency numbers here previous one and at least this much reduction and things right.


Even though you mentioned this as target , it might be interpreted as, look, this is what we are going to do.


So he just wants to play a little uh safer there.


It's not that he's saying we should not.


I mean, we should have pay and put all these things, but we uh since instead of just even 25% can just say expert introduction all.


So I would just reduction in the numbers then try to start filling in when we have more confidence about what At the moment, we are system systematizing I don't think that's even an English word, but we're trying to have a systematic architecture for how all these agents work, right?


And we're building the agents themselves to do the basic task of communicating and interacting with the network, whether it's a twin or a real network, whatever.


We haven't gone from there to saying, okay, now we need to figure out what are the algorithms and the optimizations that we have to develop, right?


That hasn't yet started.


So I'm a little scared about saying, hey, you haven't yet understood that Hep work flow, right?


And only after we understand we can even say hey, what are the opportunities that we might have for improvement and then say, okay, we think this part of it is really bad.


We think we might be able to optimize it and get this much reduction , right?


I found when we try to push GPU utilization up, it's a pretty tough task.


So these are things where if we if our neck won't get cut off, we can put arbitrary numbers, that's fine, but otherwise try to be a little bit conservative. All I was basically trying to work through the gates um yeah, and then I did some like how do we compare our results?


So we basically should have a baseline existing configuration and then once we start adding our agents, how much the improvement is happening so we could follow this, but I think that's all I had.


Oh, one more thing.


So we were talking about building a foundation model. Um So this is the data that the foundation model can take.


So the science experiment , uh the workflow structure with jobs data sets, network state, uh compute state, the GPUs compute bound operational state, failures, dependencies and then write a foundation model that learns the workload representation, what the network and compute looks like.


It predicts the network requirements given off of the workfor descriptions.


It can transfer knowledge between science workflows and facilities and explain the dependency as a network performance problem . So we build um so precursor to all the agents, we will have this foundation model that has learned of of the scientific workflows and then the agents will use this to make intelligent decisions.


So this um is part of what Raphael is uh going to be training. Um So yeah, so he will train this for the for the uh oh, sorry, the the workflow templates that Rapile just said he's going to run.


So we're going to use that to run the run for the foundation model. To be experience in this?


Yeah, I no so we have one person at Ochridge who developed the Oc Net foundation model with me um So if like once we go through this SC stage we can see if we can recruit him and start building this foundation model.


Is this something that we have to finished by March?


We did mention a foundation model in the proposal I based on all the agentic studies I did um having a foundation model helps the agents make decisions.


So I think we can have one even for us right for the network and for the telemetary agent, we've been saying yeah we need to be able to go consult.


I think of this as an generic LLM yeah that we need to go query right that has an understanding of the scientific intent, the workflows and the network that we can then go ask this LM to give us some guidance on decision making, especially for saying, what's the impact of this change or this link failure on that particular science experiment, what will happen and so on, right?


So that's the agentic part of our network agent, because right now, we've got EPIs and rules, but we need that agentic parts.


So it's good that somebody's thinking about this. Uh, it would be tough for us to do everything.


So I'm glad Raael is working on it.


Okay.


So yeah, so so we are making progress um I think that was all I had so um my students to three minutes.


They're not going to use any slice.


They just say what they have done this week.


Okay.


Go ahead about go ahead and say what you've been doing for the t what you've checked in.


Just tell what are the pieces that you've checked in.


Sure.


So as we discussed uh last week about the telemitter agents architecture, um, we have pushed that code as of now, and it has like three parts that we discussed.


One is the southbound component and the southbound component is the one which is built with telegraph and this this is actually pulling a Prometheus endpoint and we found an example, uh instance on the NRPAPI, which uh John had shared.


So we used that as a reference and we were able to poll the maximum capacity that endpoint poll is giving and what is the current TX and Rx device that is being transferred. Uh So we were able to record all of this using telegraph and uh the other component is the influx TV.


So the telegraph is basically writing all the processed metrics to influx TV, both to its cash and their database. And uh then we also built the northbound component.


So this is the one which uh uses the data from the cash and the data influx database and provides the network agent with um the the current link capacity uh based on the time stamp, which the network agent requests and uh the not API uh the component is implemented using Langra and uh these three parts we have already pushed the uh shared gititar rep or that we have.


And um as of now we are working on uh improving this elementary agent.


So we we are we are adding new AIs like the the one which gives users or any other agent with um with the way to request flexible averaging on these different metrics that we're sinking in and also provide notifications to the agents that can subscribe to it, uh like, for example, when a link fails or if there's a congestion or any other search uh down times, then the teletter agent can report it to the uh subscribed agent.


So this is something we are working on currently.


So I wish if this SC business was a little bit more weeks away than we could actually have both the telemetry and the network agent to demo but for now at least we will have we've got the code and the next opportunity we have we can show both the network and the telemeary agent working together with some network emulator and then link Sean has been working on some of the things that we've been thinking as important in real time during the runtime for network agent, the wrong highest stage is mostly implemented, but some modifications as still needed.


Basically, the network agent detects the nitric deviations, like linked damage or contextions through subscribe subscription or pic dicta inspection based on teleter agent, and in the contacts local repair of pass.


For example, extending the reserveved high, or raising the reserve the rate, then reported to the schedule agent. . His implemented some of the reactions to state changes failures, congestion, and then saying, can I take a local action, which is to say, well, if there is room in the deadlines and I was I possibly a little bit aggressive in setting the completion time to be lot less than the deadline than if there was congestion, maybe we can say that the completion time can extend till we get to uh the deadline . If it's worse than that, then we have to go through the negotiation process with the scheduler.


We haven't done that, but at the moment, just the reaction in the network age and two real time changes that we expect coming from either subscription to the teletary agent for notifications or doing a query, getting back a response from the telemitary agent about changes and then using that to react in the public that's that's what we've done so far.


We haven't gotten all that code complete because there are in in some of the discussions we had yesterday.


We said, hey, we need to change this.


We need to change that.


So that's why we don't have something ready for showing today.


But presumably next week, I think we'll have meeting next week.


No. No.


We'll be next Oh, okay.


Then afterwards, whenever the next meeting is that that is even better if you're off for a week, we have a little bit more work done and then we can show you the week after.


So I think the story is kind of coming together with all the bits and pieces.


It's still in bits and pieces, but uh yeah, I think we'll come together eventually. Uh okay, so I'll send round the slides for the paper and the demo , uh, the ones which I'll submit for um, uh to the to the Ochid system for approval, uh and then we can continue to improve them for the paper, they expect us to upload them by Saturday and yeah, so we have time afterwards.


Yeah.


Okay, so next week no meeting. Meeting. Not what is wrong with having meeting on Tuesday?


Lots happening there is time difference KK you're in Chicago man okay all right OK let's skip next we are not as young as you are. . I'm just sitting and sleeping so I don't eat but I think it's plus when you are in the conference you do want to want participate and listen yeah. Because I mean I think it'll be a chauffur basically foram It's not just uh the workshop and thing there is lotsages doing plus I think earlier I remember she I think she still is with all the ESnet stuff and things and uh the SC net itself Yeah, I know this year I'm actually not part of all of that so observer so uh but yeah, there is a lot going on as as SC.


So mostly hiding from a lot of people, but yeah, that that's a that that's our sickomos okay.


So this is another problem, which is how do you manage this honeypart effect for phase two I think so I actually started going over the proposals that were funded in phase one and trying to come out with the possible list on who we should consider for phase two. Uh I also was thinking of working with UETN so UETN is uh the networking folks based in Utah so Utah and education networks so we did a demo with them at OFC so we know them well.


We could actually University of Utah?


Yeah, yeah, University of Utah. People name Joe B Daniel Le uh and I could try to find out, yeah.


So but we the professors yourout and something else is a professor.


Joe is a professor.


So we can get access to real network data if we were to add them in the face to.


So this problem we're having with ESnet, we could start replacing with other research networks is what I was thinking . But with John and us, we could get data from fabric.


Yeah.


So we've not pushed on that.


We've just been thinking about yesnet, but if fabric is just as good, there's a lot we do with fabric so we could we could do fric.


So, um yeah, I think the next step is to identify who our phase do with so we can start talking and negotiating.


The new ones that you sent that list, I looked to know them and's kind of hard to see anyone in that phase two ones that were uh published.


Yeah.


Yeah, I don't see anyone doing similar work to us.


Right.


So I found more I' send I'll send the list to everyone. Like these are the list of funded awardies.


We could talk to.


Yeah.


Okay.


Okay, that is all the word today.


Thank you have nice uh trip if you all as well maybe I'll see you guys next week so Lots of HP people we won't be there soon.


I I am not going I've never gone the last time I went was 98 or ninety nine something that's all so I'm not gone.


I'm I wasn't planning on going maybe next year we should go if everything works out I remember this year. . All right, okay.


Thank you all.


Have a safe.


Thank you be safe okay, bye bye. 




Was this transcription useful or not useful?
```

</details>
