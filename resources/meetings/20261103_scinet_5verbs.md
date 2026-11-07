# 2026-11-03 SciNet 会议：五类 Network 操作、Telemetry 选型与集成反馈

> **日期**：2026-11-03，用户称为“今天的 SCINET 会议”。
>
> **材料与可靠性**：用户提供的英文自动转录，无时间戳和 speaker labels，存在术语、人名及数字误识别。按上下文整理主要发言为 Mariam、KK、John、Harvey、Linxuan，以及负责 telemetry 展示的 SB；这不是完整参会名单，归属未经回听确认。实现状态、平台能力及行政消息均按会上说法记录，不视为本次已经独立验证的结论。
>
> **记录口径**：Network Agent 部分简记实现与 demo，重点保留其他人的问题和建议；Telemetry Agent 部分记录设计内容及反馈，不归为 Linxuan 的实现工作。附录 B 折叠保留完整原文。
>
> **关联记录**：[10 月 27 日 SciNet 会议](20261027_scinet_network_telemetry.md)、[11 月 2 日大组会的 SciNet 讨论](20261102_groupmeeting_finishall5interfaces.md)。

## 核心摘要

1. **Telemetry 的近期选型形成共识**：Phase 1 先采用 **Telegraf + InfluxDB**，优先以较少开发工作完成可集成的采集、存储和查询链路。ClickHouse 及其扩展性、性能优势作为后续研究方向，必要时纳入 Phase 2；本次没有进行性能实测。
2. **Telemetry 查询流程和数据职责更具体**：Northbound 先读 last-value cache，再查数据库，数据缺失或无效时返回错误；southbound 独立采集、清洗、标准化并写入存储。Telemetry 给出观测，Network Agent 维护自身预留与分配账本。
3. **Network Agent 展示五类操作**：`query / reserve / commit / modify / release`。重点反馈是：异步状态通知尚需纳入；`blocked` 容易让人误解为不允许传输，应表达为受到瓶颈限制；初始单 scheduler、单 Network Agent 的 demo 之外，还应画出多组织和分层 agents 的演进路径。
4. **SC 与 twin 集成继续推进**：Mariam 将查看现有代码和 NDT，在本周结束前判断 SC demo 如何调用现有功能，并计划次日与学生讨论 NDT agent 接口。UCR 不赴现场的安排得到理解，仍可支持 demo 和 slides。
5. **Phase 2 准备不能等到三月交付时才启动**：会上仍有 12 月或次年 1 月启动 call / proposal 的消息，正式日期未确认。团队希望用可运行 demo 支撑沟通，并请 PM 推荐有实际互补能力的其他 Phase 1 项目。

## 一 行政、SC 与 Phase 2 准备

### 1.1 合同与 collaborator 审批

Mariam 介绍，部分合同正在重新核查，当前主要涉及 HPE，采购人员可能再次联系相关方；没有表示所有大学合同都需要重新办理。

PM 要求提供项目所有 collaborators 的姓名及参与理由，准备逐一批准。使用 NRP 资源是邀请 John 合作的理由，Mariam 需要 John 再提供一些资料后交给 Carol。对于 UCR 学生，Mariam 表示此前相关请求应该已处理，如有新问题会再联系。

这是行政流程更新；本次没有实际办理任何新增访问权限或确定完整批准名单。

### 1.2 SC slides 与 demo 支持

Mariam 正在完成 SC 的 workshop talk 和 demo slides，将发给团队征求反馈。KK 询问，现有 Network / Telemetry Agent 是否有适合加入 demo 的部分，同时请求三人不必赴 SC 现场；主持人表示没有压力。

KK 表示，如果现阶段足够成熟，可以提供 demo 所需内容，也愿意帮助准备 talk slides；若过早，则不必强行加入。**本次没有把五类操作的整个 demo 确定为最终 SC 展示内容。**

### 1.3 三月交付不等于三月才写 Phase 2 proposal

Mariam 提到，与 Raphael 等人的交流仍预期 Phase 2 call 可能在 **2026 年 12 月**或 **2027 年 1 月**出现；另有参会者根据近期交流，认为可能推到 1 月底。

这些都是尚未确认的时间消息，**不是新的正式提交截止日**。尽管六个月交付已排到三月，proposal 准备仍可能需要提前，不能等到三月才开始。

与会者认为，即使尚未完整，能向 PM 展示可运行 demo 也有价值，可帮助说明当前进展和继续发展的可信路径。

### 1.4 寻找有实际互补能力的 Phase 1 合作团队

有参会者建议，与其他一两个 Phase 1 团队共同形成 Phase 2，比仅扩大本组 collaborators 名单更有帮助。KK 问，是否有类似其他资助项目那样的跨项目可见性，使各方了解彼此实际做了什么，而不仅是 abstracts 或宣传文字。

讨论认可，可以直接请 PM 根据其 portfolio 推荐相近项目。Mariam 表示，将在获得 John 的资料后，本周汇总给 Carol，也询问潜在合作方建议。

会上强调，合作应具有真实互补和执行能力，避免只增加协调负担。有关过去与 ESnet 沟通的困难及对部分参与者投入的顾虑，均为参会者的评价，不作为对方工作状态的客观认定。

John 提到 **SDSC / Daniel Diaz** 的另一个 Genesis 项目，涉及 Nautilus 上的 agentic AI 和 IRI 跨站点连接，可能有重合点，分享了聊天链接。Mariam 表示会查看；转录附件未保留该链接，**本次也没有形成正式合作承诺**。

## 二 NRP、模型资源与 American Science Cloud

### 2.1 需要具体集成资料，而不只是平台通用介绍

John 问需要 NRP 提供哪些信息：American Science Cloud / IRI API 的说明，还是 NRP LLMs、persistent services 等通用合作介绍。Mariam 明确更需要 **NRP 与 American Science Cloud 集成的具体文档**，以支持向 PM 说明合作理由。

Mariam 表示，在 Google 主动接洽项目资源的情况下，自己倾向优先使用 NRP。其他人讨论了接受额外服务可能带来的协议与后续合作期待，但没有达成新的资源使用协议。

### 2.2 模型选择与访问支持

会上提及 NRP 可运行适合其硬件的 open-weight models，网络 agentic workflows 未必一定需要最大模型；HPE 也有较大的内部模型服务，UC 系统的机构安排可能提供其他 foundation models。

John 表示，如果学生近期需要 NRP 模型访问，可以联系他帮助开通。KK 说明目前主要依赖本地及 CloudLab 环境，尚未明确提出新的模型资源申请。

具体模型名、量化位宽和供给计划转写不稳定，本文不恢复清单。关于某些模型在部分政府项目中受限制的说法，只记为会上提醒，不据此宣布通用政策或本项目已完成合规判断。

### 2.3 IRI 与 AWS 连接是可用选项，不是当前决定

John 介绍，近期与 Eustace 的交流涉及通过 IRI 使用 AWS，并利用 AL2S 编程建立 layer-2 连接，可以探索 SDSC / NRP 与 AWS 的联合使用。

KK 问，在已有 CloudLab、NRP、FABRIC 等环境的情况下，为何目前需要 AWS。John 澄清，只是在介绍一个已有服务选项。**本次没有决定将系统迁移到 AWS，也没有取得新的 allocation。**

## 三 Telemetry：Phase 1 采用 Telegraf + InfluxDB

### 3.1 将 collection 与 storage 两层分开比较

SB 将上周混在一起的工具比较拆成两层：

| 层次 | 本次介绍的候选与判断 |
| --- | --- |
| Metrics collection / processing | Telegraf；OpenTelemetry Collector |
| Metrics storage / query | InfluxDB；ClickHouse |
| 组合方案 | 介绍中提到 ClickStack 将 OpenTelemetry Collector 与 ClickHouse 等组件组合 |

SB 澄清，ClickHouse 本身不是负责轮询各类网络指标的采集系统，不能简单当作 Telegraf 的一对一替代。需要比较的是整条 pipeline 的能力与集成工作量。

### 3.2 近期选择的理由

SB 和 KK 的主要考虑是：

- Phase 1 先把能与 Network Agent 等模块工作的 telemetry 系统快速做出来，同时满足必要的查询性能。
- Telegraf 已有针对 Prometheus、SNMP 等来源的 adapters，并支持自定义命令、处理和聚合；与 InfluxDB 的组合预计需要较少开发工作。
- 当前预期规模可能暂时不会暴露主要 scalability 瓶颈；ClickHouse 某些长期能力可留待 Phase 2 深入，未来也可能与 Telegraf 组合。

SB 介绍了对 OpenTelemetry 某些接入组件成熟度的担忧，涉及所查看的 SNMP / Prometheus 支持及 adapter 版本。**这是本次调研的判断，未给出具体版本或官方状态证据，不能扩大成所有 OpenTelemetry 接入都处于实验阶段。**

Harvey 等人认为先快速集成的思路合理，建议也可听取已有 Telegraf 使用经验者的意见。随后多位参会者表示对当前路线没有异议，KK 让 SB 跳过更细的数据库比较 slide，把时间用于 agent 设计；比较材料可放共享 Drive 供后续阅读。

**本次形成的近期共识是 Telegraf + InfluxDB，不是宣称该组合的性能已经优于 ClickHouse。**

### 3.3 存储名称与 cache

展示中将拟用存储称为 **InfluxDB Core**，并介绍 last-value cache 和 persistent storage。转录对版本名不清楚，本记录不自行补为某个已确认版本。

这些是所选设计的组成和预期使用方式，会上没有展示实际部署、数据保留配置或查询性能测量。

## 四 Telemetry：数据职责与执行流程

### 4.1 Northbound / storage / southbound

| 部分 | SB 介绍的职责 |
| --- | --- |
| Northbound | 当前主要接受 Network Agent 的链路指标请求，从 cache / 数据库读取结果，按双方约定的 `link_samples` contract 格式返回 |
| Storage | 保存观测指标，提供 latest-value cache 与持久化查询 |
| Southbound | 轮询 Prometheus、SNMP 或执行自定义命令；清洗、标准化、映射后写入存储，并更新配置的 cache keys |

当前主要 use case 是服务 Network Agent，未来再扩展其他指标；本次没有确定 scheduler 等新调用方的独立接口。

### 4.2 `link_samples` 请求及时间有效性

SB 展示的请求包含 link IDs、起止时间，以及用于判断观测是否有效的查询时间。示例中，用拓扑映射找到真实链路，读取总容量、测得的 background traffic、链路 up/down、采样时间和有效期等信息。

Telemetry 可由观测推导所需的链路容量信息；Network Agent 收到后，再结合其自身维护的分配、预留和账本状态，计算请求能使用多少资源。**Telemetry 的测量存储与 Network Agent 的资源会计不是同一份状态。**

过了有效时间的观测不能继续按新鲜值使用，需要重新从来源取得指标；本次未定稿各指标有效期的具体配置。

### 4.3 Northbound 的 LangGraph 查询流程

拟实现的顺序为：

1. **Validate request**：格式无效则返回错误。
2. **Read cache**：cache 中结果完整且有效，直接返回。
3. **Read database**：cache 不满足需求时再查询持久化存储；数据库结果有效则返回。
4. **Respond**：两处都找不到合适样本时返回相应错误，并按 `link_samples` contract 统一格式。

介绍中也说过时数据需重新采集，但该执行图展示的是 cache → database → error，**没有明确画出同步请求是否会直接触发 southbound 刷新**。请求路径与刷新机制如何衔接仍需实现时对齐。

### 4.4 Southbound 是并行的数据同步过程

SB 认为，这部分目前大多是确定性的 polling → cleaning / normalization / mapping → store，可按 endpoint 分别运行，不需要为了该流程本身建立 LangGraph 或 LLM agent。

这不妨碍以后在查询解释、诊断或 probe 决策中引入 agent 能力；本次并未决定整个 Telemetry Agent 都只能是确定性代码。

## 五 对 Telemetry 的反馈：解释、基础设施理解与可靠性

### 5.1 请求方要知道“得到了什么、为什么”

有参会者指出，处理请求时的一些决定并不简单，调用方需要知道结果及原因；agent 可以帮助组织这样的解释。

KK 表示可将该方向纳入：除采集、保存和返回数据，也考虑历史、原因和 inference。Telemetry 可能掌握部分观测侧知识；Network Agent 因为直接连接网络和 scheduler，还需要更深入的 topology awareness 及诊断能力。**具体 root-cause 推断如何在两者间分工，本次未定稿。**

### 5.2 Harvey：保留一条“infrastructure awareness”的工作线

Harvey 强调团队对真实基础设施的理解：应考虑全局拓扑测试、为系统稳定性保留多少 headroom，以及 background traffic 所用拥塞控制协议等因素，而不仅是数据库和接口。

他希望把这些理解和准备持续记录下来，并最终放入 decision process。KK 认可这类知识既可能来自 telemetry 的历史和处理，也可能更深入地进入 Network Agent 的判断。

本次没有给出 headroom 数值、拥塞控制模型或已经完成的 global tests 结果。

### 5.3 近期实施与指标扩展

SB 表示正在实现上述结构和 API，先建立 mock Prometheus endpoint 验证链路，再与真实基础设施 API 连接。

同时会与 Linxuan 对齐更多交互：在链路容量之外，考虑聚合指标、端到端 RTT、flow completion 等测量，以及复用 perfSONAR、iperf 等 custom probes。**这些仍是继续实现和对齐的方向，不是已完成的集成功能。**

### 5.4 John：把备份纳入 pipeline，并提供真实 Prometheus 入口

John 分享自己使用 InfluxDB 记录设备 / payload telemetry 时遇到数据损坏的经历，建议定期做备份并转存 offsite；举例可每日甚至一日多次。该建议未在本次形成确定的项目备份频率或恢复目标。

John 还在聊天中提供了 NRP Prometheus endpoint，称 Grafana 中相关节点网络观测可经该入口获取，有助于初始接入。**该 URL 未保存在用户本次转录附件中**，不能据此补造链接或认定访问权限已开通。

## 六 Network Agent 五类操作与主要反馈

### 6.1 实现与 demo 的简要进展

Linxuan 报告，在上周 query 及基本框架之后，已补充 **reserve、commit、modify、release**，并称代码已推到共享仓库。本次没有读取远端复核提交状态。

整体图包括 duplicate-request 处理、过期项清理、按 verb 分派至子图，以及各操作成功/失败后的状态记录、响应或 rollback。查询提供候选方案，不扣预留容量；reserve 与 commit 分成两个阶段，release 释放资源，modify 调整已有安排。

Demo 从简化拓扑、background traffic 和两次 transfer 请求开始，展示多个候选方案及 reserve。后续 commit、modify、release 被列为同一示例余下的步骤，但因会议时间限制没有继续逐一展开。

转录有 `quote` / `query` 混用，本文按当前命名统一记为 **query**，不将它们列成两个不同操作。具体数据量、节点名和时刻转写不稳，不登记为性能结果。

### 6.2 Harvey：需要配套的异步状态变化基础设施

在讲到 bookings 和状态切换时，Harvey 提出，真实的全球异构 testbed 或 production system 需要配套基础设施，能在必要时产生事件或 interrupts，通知系统发生了什么状态变化。项目不必自己承担所有底层基础设施，但整体架构中必须有它的位置。

KK 认可：除了主动请求 telemetry，还需从网络本身直接或经 telemetry 接收**异步通知**，更新正在跟踪的 allocations 和 outstanding requests。

KK 明确说当前尚未覆盖这一点，现阶段主要处理由当前 Network Agent 管理的请求；将来需要把异步事件纳入。后面谈到 modify 时，也举了异步网络通知或 telemetry 信息促使修改资源安排的情况。

**本次没有确定事件 schema、传输机制、订阅范围或故障时的完整状态机。**

### 6.3 `blocked` 建议改为“受到限制”，避免含义误导

在候选 offer 的说明中，KK 认为 `blocked` 容易让人以为传输不被允许，而实际想表达的是**速率受 bottleneck 限制或存在上限**。建议采用 `limited by ...` 一类措辞。

这是术语反馈；本次没有敲定对应 schema 字段的新名称，也没有在会议记录任务中修改 `blocked_by` 等代码。

### 6.4 Mock scheduler 与当前 demo 边界

KK 确认，当前 scheduler 主要是 mock 驱动请求，并没有在其中实现显著的调度逻辑；Network Agent 自己维护资源 ledger。

两阶段的 reserve / commit 也在结尾被再次确认：先预留、再正式承诺，之后上层才使用资源。与会者对当前方向给出正面反馈，没有要求本次完成真实 scheduler 或生产级状态同步。

### 6.5 多组织和分层 agents：要把演进路径画出来

Harvey 指出，实际环境跨多个机构，可能有 local、regional 和 central agents，分别管理基础设施并相互提供判断与反馈。

KK 说明，本组初始 demo 先采用**一个 Network Agent、一个 scheduler**，隐含较单一的基础设施/组织边界；长期确实考虑多个 agents 对接不同网络或基础设施片段。

Harvey 表示，这种简化起点没有问题，但应把后续工程阶段画出来，准备额外 diagrams，让评审知道团队已经考虑跨组织的真实环境。他特意说明，这里说的演进 stages 不必等同于 Genesis 的 Phase 1 / Phase 2。

与会者也建议，在向 PM 汇报时逐渐传达这些后续思路，为 proposal 铺垫。**本次没有实现或定稿多层次网络协调机制。**

## 七 SC 集成、NDT 和下一阶段工作

KK 问，是否需要把当前实现打包供两周后的 SC 使用。Mariam 表示，将在当天和次日继续看代码及 NDT，在**本周结束前**反馈；可能直接调用现有 agent 的函数，不一定需要额外打包。

Mariam 还表示会在次日另约学生，讨论 NDT agent 的形态和对接。按会议日期，“明天”为 **2026-11-04**；具体时间本次没有确定。

Linxuan 表示接下来将进入 runtime 和 learning 阶段，runtime 关注传输变慢、链路 outage 等情况的检测和诊断。当前实现工作及与 telemetry / twin 的接口仍需逐步推进，**本次没有展示已运行的 runtime / learning 闭环**。

## 八 行动项与待决事项

| 事项 | 负责人 / 会上安排 | 边界与时间 |
| --- | --- | --- |
| 提供 NRP 与 American Science Cloud / IRI 集成的资料 | John；Mariam 汇总提交 PM | 资料内容以集成为重点，而非仅平台通用介绍 |
| 向 Carol 汇报 collaborator 理由，并询问相近 Phase 1 项目 | Mariam | 计划本周汇总；无已确定的跨团队合作协议 |
| 查看 SDSC / Daniel Diaz 项目的互补性 | Mariam 表示会查看，John 提供线索 | 聊天链接未含在转录附件中 |
| 完成 SC talk / demo slides 并征求反馈 | Mariam；团队可提供素材 | SC 约两周后；最终展示范围未定 |
| 按 Telegraf + InfluxDB 路线实现 northbound、存储和 southbound | SB / Telemetry 负责团队 | 近期共识；先 mock，再接真实 API |
| 对齐聚合、端到端指标与 custom probes 的需求 | SB、Linxuan | 包括 perfSONAR / iperf 等测量；接口和优先顺序待定 |
| 考虑定期、offsite 备份 | John 建议 Telemetry 团队纳入 | 频率、部署和恢复要求未确定 |
| 纳入异步状态变化通知与状态更新的设计 | Network / Telemetry 及相关基础设施团队 | 当前实现尚未处理完整事件链路 |
| 记录 infrastructure awareness，并补充分布式、多组织演进图 | Harvey 提出，团队继续细化 | 没有新的性能结论或完整多层协调实现 |
| 评估当前代码怎样供 SC / NDT 调用 | Mariam 与学生对齐 | 次日拟约讨论，本周结束前给出 SC 集成反馈 |
| 逐步实现 runtime / learning | Linxuan 报告后续方向 | Runtime 先关注性能退化、outage 的检测和诊断 |

待决重点包括：Phase 2 正式 call / 提交安排；telemetry 数据缺失时的刷新机制；端到端观测与解释/归因的职责边界；异步通知和 ledger 同步；单 agent demo 到跨组织环境的演进方案；SC 最终采用哪些可运行部分。

## 附录 A 转写存疑点

| 原转写 / 项目 | 本文处理 |
| --- | --- |
| `HP`、`NRP/an RP`、`SSC/SDSE` 等 | 结合语境整理为 HPE、NRP、SDSC；不据此恢复完整组织/参会名单 |
| `telegraph`、`influx TV / DV`、`cash` | 分别整理为 Telegraf、InfluxDB、cache |
| `influx stream DB co` 等 | 按反复出现的存储名称整理为 InfluxDB Core，准确版本待核对 |
| `open telemetry`、`click stack` | 整理为 OpenTelemetry Collector、ClickStack；能力判断仅记为会上调研说法 |
| `code/court/quote/curry` 等 | 查询操作统一记 query，代码语境仍理解为 code |
| `comet`、`round high` | 按五类操作及阶段语境整理为 commit、runtime |
| `NDT/NDD/ND...` 等 | 统一记 NDT / network digital twin，具体 agent 接口仍未确定 |
| 模型名、精度、政府项目限制 | 不清楚处不恢复，不把口头提醒扩大为通用事实 |
| 聊天中的项目及 Prometheus 链接 | 本次附件没有 URL，正文不补造或假称已取得访问 |

## 附录 B 完整原始转录

<details>
<summary>展开原始转录</summary>

以下完整保留用户附件原文，不修正语法、术语、数字或发言归属，包含末尾转录工具反馈提示。

<!-- BEGIN RAW TRANSCRIPT -->
A have a little bit of update to provide today so we can do that a little bit on the telemetry work and I also enhancements to the network agent.


Okay.


Sounds good.


Okay, Raymond's here, so I think beneath will be joining that's only one left I'm I'm not sure, actually, if who needs joining today.


He's out of like an internal conference thing. Sounds good.


Okay, so I think only Aaron is missing sol do an update to him when I see him later um so okay so I think we can get started so welcome everyone uh for our weekly meeting . Um so if you um notes to start with before we begin, so I've been involved in a lot of administration work this past week um . So we've been uh so there is something going on with some of the contracts so HP and uh so some we are going over again uh so the procurement officers will contact you guys again to see what is wrong so that is happening in the background um or only with HP or is it also with uh the universities I think for now it's only with HP we're figuring that out and then there and then further the program manager has asked for all the names of all the collaborators that are on the project and she's asking for reasons why people are.


So I've already spoken to John uh earlier today um so we have a like we are saying that we are going to be collaborating with John because we are using an RP resources so we have a good reason.


So I just need uh some more information from John so once we have that, I'll send that up to Carol uh so she wants to approve everybody who's who's collaborating . So that is why I'm having to double check everybody on the on the on the team.


So yeah, so uh you might see some extreme emails coming from me to you guys . So are students on our side or anything?


I think uh I think the past requests are already done for UC Riverside.


Okay.


So, uh so I think if there is something come up comes up, I will contact you..


So with that, um then we have SC in two weeks, so I'm finishing up the slides of to be presented so I'll send them round to everyone and ask for feedback. Um to see if if everyone agrees.


So so those slides wouldn include the ind stock as well as the demo slides that we are going to be doing.


Okay.


So I think that's all any questions from anyone before we uh I think we can pass it on to you uh the students . So for the demo that you are planning at the end of today maybe we can look at whether there's anything out of the network agent and the Talemitry agent that you want to also show but I think uh if you can please excuse the three of us from attending uh SC, it would be good.


Okay.


Yeah, yeah, no pressure.


But we can put whatever you need for demo if you're planning to include anything related to these to activities, if it is premature maybe we shouldn't . But if you if you need any help, please let us know and certainly be happy to help you out with the slates for the talk.


Sounds good.


Yes, uh that's fine.


John, you have a question.


Yeah, um what do you need from NRP?


Do you want uh Frank to uh describe well, maybe Frank and Eustace to describe the American science cloud integration, IRI, API, or um just kind of provides some boiler pay on NRP collaboration , uh, using NRP LLMs and persistent services for the test bed.


So, um, for example, Google has been reaching out for us to use their resources for this particular project . If I get an option, I would rather use NRP resources than Google, but you mentioned that NRP is going to be part of uh American Science Cloud.


So I just need some documentation on that it's more specific to American science cloud than the general services.


Yeah, so then I can tell that if Google is offering services, uh we should be able to get free LLM tokens, right?


Yes, that might be very helpful.


They have bigger models than I can run.


Yeah, but what what is the that is nothing comes for free, right?


Yeah, they will expect to be part of the I will have to do agreements and then I will they will expect to be part of phase two main reason that people are you know a honey pot, right so yeah I mean phase two I think naturally we would want to have more assistance but that doesn't mean that you know some people uh might just be there for the honey right but not to produce the honey. And the nice thing about NRP is you can run any open weights model you want as long as it fits into the machinery we have and uh for a network agentic workflows a smaller model might be actually better.


And and if we want't bigger models since HPE is part of the team, they have a bunch of these large open weight models that are available, including ti seek and so on.


So, you know, we we have a team member who actually has a pretty large uh you know in-house LLM service with lots of large models we run variants of deep seek, but you gotta watch out for that one because the government has banned its use in some programs.


But we have Kimmy variants and other things.


We just can't run the full uh 16 bit Kimmy K3 and like the uh uh reflection.


AI, um beam, uh, we're gonna be running a smaller version of that during supercomputing and we actually Mohammed is already running a variant uh forbit, I believe, precision. Um on NRP.


So you know, we do have things that the uh American science cloud and DOE will like, uh, uh a western open weights model like the the uh reflection dot AI would be very beneficial, I think.


Okay, sounds good.


And UC system uh is working with both Google for Gemini and for open AI so if on our end, at least and I suspect that would be the same with the Harvey as well it should be able to get access to these larger foundation models that needed through our university arrangements.


Does anybody need access to the NRP models uh sooner than later?


I have to drop off the call early today.


Um I've got a bunch of s superopedian stuff.


I got wrangle.


Yeah.


We probably need, but I don't know at the moment that like the students are we are using our own environment as well as the cloud lab environment. These are the things that we are depending on at the moment, but let me know if you do need anything and I can, you know, make sure you get access to it quickly.


Okay.


Thank you.


Sounds good.


But before John leaves I think we would like to go through this teletry stuff a little bit so that we are all in uh we have I think uh yeah we can uh so I think I forgot to mention one more thing. Um So I was talking to Rahael yesterday.


They are still expecting the call for the face two to come in December or Raphael was saying January maybe um so even though we have pushed the deadlines to deliver in March, expect that we still need to do the phase two proposal earlier wouldn't that mean that we should at least have some kind of demo to this program management person information on this I say even if it's not complete, I think it would be extremely useful that yeah they keep saying still the December deadline but the last conversation last week we had a review for both modcom and America says cloud and they're talking now really pushing to end of January because there is the delayed you know and actually believe or not there are projects that they still haven't started yet the ones that are led by universities some of them because of some breach agreements there has not been signed though that's why you know they're telling to Bush and also with the elections, you know budgets, all of these things, but that's why they are pushing probably they're gonna push it back so have the demo would be extremely useful and no increase our chances a lot another thing that it can be very useful that I heard is that if we try to combine ourselves with other RA phase one teams instead of just us make us larger with a new collaborators except if we can explain her well where we have it but uh they would really appreciate if the we would find one or another team or two other teams do it work together then know and come up with a face two out of some face one projects tell you something that deal he would like to emphasize in other efforts like this that were led by NSF that I was involved with in the tip efforts there was some visibility that everybody in phase one had of what other people were doing in phase one so that if possible some partnerships could be formed is there any such thing that DOE is planning to do for genesis to get cross project visibility?


I mean we don't want to depend on just the marketing stuff that people have for their projects, but we really want to see if they have something that is meaningful that can complement what we do not just buzzwords it's partially available are the abstracts of allowed look at our project abstract and look at what we are doing rights you if we do something meaningful that's quite different than our project abstract, right identify some people out to them to know try to have a call and say it guys doing what're doing, trying to see if that is any potential for collaboration. Finding somebody trustworthy who is actually someone who does real work would be good. Yeah OK let's see how that goes. Tell her to repeat you got cut off maybe some critical words got cut off in the beginning. Manager and ask her to know if she because she knows all the projects she's talking to everybody in her port photo so she might be able to want you to know to one or two projects that are closer related . It makes a little bit easier the interface something that it might be something that she might want to see connected you know basically she telling you how to partner without telling you how to partner really shocked's straight to the point so I think yeah again we could trust her on that if you don't we had restart to ESnet we restart to ES net even before we reached out to Kiran and then of course Kiran has been trying to talk to the ES net folks right the big saying repeatedly go pound sand let's reach out to Carol and see what she suggests so I'll I'll send her an email when I get stuff from John as well so I'll try to compile everything and send it to her this week and see what she says We have to be strategic to who we work with because we don't want to increase our workload um and anybody we get partnered with she's eventually going to put us with them in space to also I don't I if they see this team is performing well they'll say okay you guys should work together in phase two so we have to look at that also in just this group right we need more people but at the same time we don't want people who are just only going to listen right yes okay sounds good uh a link in chat uh SSC also received a genesis mission, um award, uh Daniel Diaz.


They're working on agentic AI using nautilus so maybe the overlap is enough to uh partner up with the SDSE group that's doing stuff.


Okay, I'll check these also.


Okay.


Sounds good Any other questions before we hand off to the students?


By the way, they're also looking at using the uh IRIAPPI to make connections to other sites.


So there's a whole bunch of overlap . We had a meeting with Eustace, uh, yesterday and uh he can give us uh AWS uh access through IRI currently and uh so we can do collaborations between SDSC NRP nodes and things out on AWS and and IRI can program AL2S paths so you can get layer two linkages into Amazon. Check into this.


Why would I want to need use AWS for now if I can use cloudab NRP fabric it's just a service that's available through the IRIAPPI.


That's all I'm saying.


Sounds good.


OK OK sorry about Lynchang.


Do you want to start sharing why don't you go over what you've been looking at especially because we want to make sure that we talk about what we found with telegraph and clickhouse sure um yeah have everyone um um as just as I have a recap for um what we looked at um last week so um I think last week we just reviewed about over the telegraph as a framework for uh collecting and processing the metrics that we saw from let's say Prometheus or SNNP uh endpoints and um for the storage part, I think um there was also a suggestion that we have we can check the clickouse framework uh instead of telegraph and um we actually investigated what capabilitiesreekhouse is providing and um what is the performance and what trade-offs it has with respect to uh another storage called the Influx tv . Comes as part of telegraph, right?


Yes, yes.


So influx TV is the the default recommended database for with and we use telegraph framework, clickhouse is a separate uh database that we found um and I think um just to uh set up this scope um what we think is for phase one we may I want to focus more on uh developing the uh initial system uh quickly and but also ensure that we we get good quite performance whenever uh we retrieve these metrics from the database or from inmeories stores.


And um uh I think um maybe scalability and maybe highper performance is something we can focus on for face two and this is something we think uh is is like a a good way to start with our teletter agent.


So right now, the thing is to make sure that without a lot of development effort, we want to get a meaningful phase one telementary agent working with the network and scheduler agent and all the other pieces that have to work so we looked at how much work we would have to do to integrate clickhouse with all of the metrics collection that has to happen how to make those metrics reach clickhouse and so on and whether that is an easy way of integrating the functionality that telegraph has along with clickhouse and that is why we eat wanted to make sure we make the right choice and based on all the looking that we have so far we thought that you know at the moment in flux DB, which has in memory cash and telegraph seem to be already integrated.


We don't have to do a lot of development work for now.


We do see a path for being able to take telegraph and integrate it with click house to get maybe larger scale and there are some features that are there in click House that would be desirable for the long run and we probably will need to look into it for face to, but for phase one, we were thinking uh go with telegraph.


But there is a few features in the next slide thataura can walk through to say what's the difference between those two.


One.


Go on. You have to little bit faster. . I'm looking.


I'm looking for the window to turn off the sound.


I have a call that I must take, but I also have 50 windows open. The telet itself we can split this into two layers.


One is the metrics collection layer and one is the metrics storage layer . And in the collection layer, we found that are two types of frameworks, one at two frameworks.


One is the telegraph, which we explored last week, and one is the open telemetry collector.


And for the stoliage we have about teletary collector is that that got integrated with clickhouse in this click stack thing, right Exactly.


So yeah, we came across this open telemeary when we tried to understand this click stack and this click stack is a product from clickhouse where clickhouse combines this uh open teletry collector for processing the pulling and processing the metrics and it uses click houses the data too. The clickhouse itself we found as by itself, it's not a a polling system, uh or like metrics collection system.


It's just a data tool and it's very similar to influx to be in terms of how it's storing in a columnar format So we had to understand what trade-offs exists between these two two two different storages.


But even before that for metrics collection itself, uh we found the term open telemetry has uh some sort of an experimental support as of now, when it comes to reading from SNMP uh endpoints or even from Prometheus endpoints also.


So this means if we have uh even more different uh sources from which we want to read metrics, maybe we have to evaluate each adapter's version.


But this sort of uh uh a problem does not exist, but telegraph. Um they seem to have a more mature support uh with good adapters for both Prometheus and SNMP and it also has this uh features for running these custom commands and also having a well-def defined data processing pipeline with advocators as well as with transformations.


I think keeping these things in mind, uh we are going with uh telegraph itself for met thing going with telegraph and we want to make sure everybody's on board with that doing switching to playhouse means that we've got to do quite a bit of work rather than using the pipeline that they already have with telegraph and their influx DB database that is integrated with it and with some sche that's if I'm not mistaken, I mean,ust says worked with telegraph a lot, probably also Mohammed in.


So we can, you know, get the judgment, but I think the idea is correct . And the thing about clickhouse is it emphasizes scalability properties and performance.ug, you know, during our phase one, we either will or will not encount probably not encounter scalability issues that we can deal with those later.


And if necessary, we can fold it into our phase two proposal.


It's exactly the start process we were having.


What are echoing is exactly what we had in our mind. On.


Yeah, the next part was choosing between the base itself with we found, I think my suggestion is that we leave the slide if everybody is okay, uh just taking the suggestion that we use this influx stream DB co database with its in memory cash and work with that for now uh if everybody's okay with that this slide when we put it on the uh Google drive they can look at I would like you to actually spend the time talking about your design for the telemetary agent.


I have no problem with the the influx and uh open telemry, telegraph stuff.


Okay.


Same same here.


Yeah.


Okay.


Okay.


So if we go we have consensus, then let's go forward with our telemetary agent design . So here's the of a broad overview of the different parts of a telemetter agent. Um we have this notbound interface epicetum and its main purpose is to interact with uh different agents . Um and for now it's the network agent that we have main use case form, which is to serve theear link capacity values and further more metrics we are thinking of.


And for then, the northbound interface accepts those requests and quas these information from the data to other people using the influx to be core and uh it has since it provides all the last value cash and also the persistence storage. Um uh this and this is something not wrong uh API can quit uh In Parlin, the southbound interface is something which performs the data and sync process.


It keeps polling the Prometheus endpoints SN ambient points and can also run these custom commands to to fetch the metrics and also clean them, normalize and then store these metrics and the influx DV could.


And um the the data processing part the data normalization, all of this helps us in um having a having a storage which the it northbound EPI can use for uh for providing metrics to the network agent.


So this is like the broad outline for our design where we have the northbound, the storage and the southbound layers and um uh here's an example um requested me uh and I use case which we think where the network agent is interacting with the teletry agent , the network agent can request the purling capacity between these two times stoms and which is valid as of a given time stamp and for a specific list of links, and for example, let's say there is a link with link ID l2 . Now, when these parameters are given to the uh not bound interface, the telemetry agent could have a dataoon, which has the first three columns in its um store, where it says, what is the length ID mapping to like what exact link it is?


These are representative, but if let's say we have the actual uh uh the network topology, we can map these to the actual link IDs and get the uh metrics.


And then we know between which time stamps, what was the capacity that was totally present and what was the background traffic that was measured?


And through that it can it can derive the actual available capacity . Now, these three columns are something they network uh did not bound API can fetch from the data stood and it can also set the different fields that at this during this time interval, whether the link was up and at what time the these these different metrics for sample, and until when the metric is valid.


So these this ensures that uh the network agent gets the up to date information and in case the query time stamp is beyond this valid time, then the fetch would fail and we would get the metrics have to be refetched from either the sources. Um from from the sources basically to ensure the valid the values are up to late.


And um once the metrics arrive at the network agent, this is where the the fourth column is something the network agent does internally.


It's not something specific to our teletry agent, is that the network agent is the one where the data is the uh state is maintained of the different uh link components, but the telemetry agent is basically giving you the current metrics that are collected and stored in its cash.


Yeah. It can go on.


Yeah. Um and here's what how we plan to implement this flow using theangraph model.


So this is the entire chain of work flow for uh satisfying the link samples request.


So in the teletary agent , uh we would go with the validate request function first and in case the request is in the is not in the proper format, it would err it out.


But then we would read the cash.


This is the cash which the influx TV is providing us, so we call it last cash AP and in case the cash is valid and it's it's complete, then we will return those samples directly.


Otherwise we then make the next call to the database and if the values are present and if they are valid, then we return those samples to the network agent. And if the values are still not present in the store as well, we will err it out, saying the samples are not present and uh the response a function handles proper formatting in the link samples contract that exists between the network agent and the teletary agent.


But uh this is the overall uh landraph structure of the uh link samples APL that we are planning to implement as part of the teletary agent.


And um uh this is the other part of which runs in parallel to the north, which is the south bound API.


This I this big thing uh we don't need an actual landaph uh structure for this because this is mostly our data synchronization process.


And maybe we can have this polling set up for each different endpoint that we have and then we um fetch these metrics and perform the normalization, perform the cleaning up of these metrics and maybe set up any mappings that we have to perform and then store these as whether these metrics were customomed varied uh values or whether these were uh normalized values from endpoints like Promeives or from SNMP.


And finally write these to the influx to be, which also updates the uh last value cash for those keys which we configure in the cash . Um I think these this this flow is mostly determinedistic.


We don't really think uh think as of now and uh at agent would be needed at this point, but we're open to suggestions on that front issue when people make requests, they need to know what happened and why and so as you make these decisions, which are not trivial, you have to respond with this is what you got and why.


And so an agent can do that.


So definitely something that we will incorporate and do what was in the previous slide for basically taking the metrics that are collected and then managing storing and responding to the network agent and providing some inference capability as to the root cause what we provide the next.


I have to add some comments which are outside the software.


So one thing that our team has is real infrastructure awareness . So what I would like to say in this case as an example is you prepare you look at your entire topology.


I mean, we have global tests.


We run and find out what are the head rooms that are needed overall in order to ensure stability and we build them in to the decision process. For example, it depends upon the congestion protocol of the background traffic.


So if you're talking about overall capacity um so I mean, I has that high touch can do that so we just need to keep a side thread that that documents are infrastructure awareness and our preparation.


And for that what we need is some of that infrastructure awareness is potentially within the telementary agent not not so much in the raw data collection but processing and storing both history uh causes and uh inferences that come from having it go constructed in LLM to find the root cause and so on and then it was uh another component of that that is likely to be uh much more in depth in the network agent which uh lengu on is doing for making sure that we have all of the topology awareness in the networkation because that's ultimately what is interfacing with uh the network as well as the scheduler so uh we'll see that when um link we are talking about how we can actually have that consult L LM to keep track of the uh the diagnois that needs to be provided for why something is successful or not okay so you just have one more slight buba it's just to mention what's the focus now that we are trying to implement this um design that we have for the structure yeah we are implementing this model that we just described as well as the APIs.


So that we can syn the metrics from the uh two end points.


I think for now uh we we're we're looking for a mock Prometheus endpoint to setup so that we know that the system can work. But then we can integrate this with actual infrastructure AIS and test out the real uh thertrics that we can sink in.


And we're also working on um having more int interactions with with the network agent so that along with the link capacity request, we can have maybe some aggregated requests or even into an RTT requests and so on.


We are we are thinking on having more such interactions.


That especially to exploit the information that you get from things like Perfsona, right?


It is that we can make custom probes, right.


And if you wanted to run, I for whatever and get like collect some of those measurements . So that is as far as the telemetry agent is concerned, I want to make sure we cover that and then we can go over the enhancements to the network digit why bring up a suggestion I use I use influx TV for um recording telemmetry from Luran uhadios and payload telemetry payloads.


And we've had a couple of problems where we've had uh corruption and so I highly recommend doing influx backup and uh transport that to an offsite uh in case you lose storage uh it's very difficult to uh to reassemble it unless you have a clean backup.


So I I would put that into your your pipeline is uh to um regular backups daily, maybe multiple times a day, even. Uh one other thing is, if you do need Prometheus endpoints, I just past a link uh We have a a everything that we have in Grifana for all the network telemtry from all the nodes, uh is available through through this Prometheus endpoint. This would be helpful for us to get that bootstrap.


Yep, yeah.


Thank you.


You want to go over things a little bit, uh link if you can stop sharing yeah sure yeah, okay.


Let me update on the network edge in the part.


Last week we implemented the hentic framework and the query verbs, and this week we implemented the remaining four verbs between network agent Aliceit agent, including reserve, comet, modify, and the release, and of course, the same verbs between metrogigend and the and hang on, hang on uh the j Harvey you had something to say or no okay.


Keep going keep going. And uh for the cold, we we added this person files, commit, modify, release and reserve for the verbs.


And I have already pushed them ifirgin to our hary.


Here is the world forograph for the whole overview. Here for the just a little bit, walk through it just a little bit because this is big slide so walk through just a little bit well they' car around the schedule agent, the network first will do the the top the uh theates the request in case of like theoon agent within the or to the same request.


I identify duplicate and remove them.


Yeah, yes.


And then the way they expired request because like, for example for and for the reserve, the.


So it will sweep the expired request.


And then it will roll the verbs to the their their own graph . For example, for a quote, it refer to validate the the court is basically asking for the questioning a particular resource be at the Sorry, see, they both will validate the request if meet the with the format and then he will check if it's fresh or if it still, it will you will get a new data from the telmentary agent. And uh Network agent will find the path for the request. And estimate the finished high.


Fin only throughout to give the offer to the schedule agent. And the further reserve seems similarly it will value the format and the checks the c capability and the place the pass to the physical or kid.


Here is the either hook where we can do ormer circuit reuse and defend multipass and the priority based preemption or or scheduling for multi work clothes.


It is part the if the hook and the need to write the surface surface service intent for for the service and depete the the lead and the there's some good things going by here.


I mean nature about confirming bookings you know I'm thinking in a to make a system which actually works in this complex environment um stability is very important and state changes are important, but I'm thinking that we need a kind of partner infrastructure that says that, you know, I mean, can generate interrupts if necessary can can feed you state changes, which you can interpret things like that.


So I don't think we want to take responsibility for all of that, but I think that the bigger picture , if I have a global heterogeneous test bed, which we do or a or a production system, that that implementary infrastructure needs to be somewhere.


Yeah, we need an interface to be able to get not just from teletry information, but also you say from the network itself. Whether it is true elementary or indirectly notifications that then update what we are tracking in terms of the allocations and requests that are outstanding.


So we we've not addressed that yet at the moment, I think uh Harvey, but at the moment we are basically only working with requests that are managed by this network agent to use the teleter information, but certainly we have to factor in the asynchronous notifications that would come that we need to then account for.


Yeah.


Thank you.


Okay, I see.


Okay, this is the reserve part so if it's uh it's successful in the sense part, it will record the reserve and the right the new information to the leader.


And it's stilled and you will go back anduddenly returns the reserve is reserve is a K to the schedule agent.


The acknowledgement that you have made the reservation goes back to the schedulator.


Okay.


And for the comed, that means the scream agent, uh decide that you use this pass and make sure confirm this reservation, so, of course, validate the format and the commit in a sense, HI. And they' okay, you confirm them later.


You knowow back, and response.


E respond back to the scheduling agent, right?


Yes, yes.


And uh, of course, the release, is uh if the pass if the data transfer is finished it, it before that in light, we will will release the past actively.


First by date and cancel it leisure release and respond.


And the unm modify because an agent might be doing some change to to the to the to the current network because there might be some problems in the network and the it needed to do the rescheduling this would be worked when you get a notification that is a synchron, then we might end up needing to modify or we get up page from the telemitary that then causes us to do modifications.


Right?


Yes.


So, first mortage and the of course re checks the capacity, if you want to change the want to change the the the the capacity and uh modify the later and the core the sens HI to modify it and the for okay, record it for the field,ow back, and the pen on respond . This is the rollograph and here is a simple demo for it Uh this is theropology . We will send it wrong in a or two to RO one It will go through102 and So this the demo is this part is about the basically information, like theology information, including the nodes, the links, links capacity, and the background traffic and the coronator.


And at 9 a the schedule agent will send the curry requires to schedule to the metwork agent.


This is a cur format there are two transfer.


First transfer is in the seity, TV data from two from and they are two to learn one from night to 3 PM.


The say transfer is since one TV did have from you in the same pass from also 9 to 9 AM to 3 p.


So little work agent who will send the offer back for each transfer to three offers.


They see for the Tan, they see the for the tu.


They includes a capacity and a thar high, and the reason they be blocked for the bottle leg . Yeah, but to save blocked probably the world is not quite right.


We should be so limited by your bottleneck something so that it doesn't infer that you will not be allowed to do this.


This is limited.


What is the upper limit right?


Yes.


Another specific pass in offer.


So the major coronate didn't change because if just a provide offers, the signation didn't do the reservation and for the first part, agent will reserve some offers.


For example, you choose human Q T12.


This offer and Q21 and this offer. An agentose that this two offers and the the agent send is the reserve ASAK and the provide the expired high.


You have a sort of mark sched agent, right?


You haven't actually done anything significant insight the schedul agent at the moment . Yeah, there is the mark network and the mark mark, sojust deb the capacity.


So the scheduler, I mean the network agent is maintaining this ledger of what is available. This is interesting in that environment involves many organizations.


So although we want to keep our demo straightforward and not toologically complicated in reality, you'd imagine that you have local or regional agents and you have central agents which are overseeing the inter intercommunic overseeing what the agents, the local and regional agents are doing and providing some judgment and feedback and, you know, allowing uh a wide ranging infrastructure, which is run by different organizations to operate together . So how we we been thinking that for our initial demo, we will work with a single network agent with a single scheduler, all of that uh by implication is that we've got just a single uh infrastructure one organization. Is find phases.


I mean, not genesis phases, but phases where, you know, we obviously a thought of all these things and we don't want reviewers to say, hey, you didn't think about this, you didn't think about that.


I mean, yeah, you know what I mean?


We just need additional diagrams and stuff. Definitely have been thinking that this whole thing would be a distributed environment with network agents interf infrastructures, maybe pieces of the infrastructure even if it's largely distributed.


So, yes, we have to uh this is our sort of initial effort at the moment.


We want to roundout network, teletry and scheduling agent on our side and then work with what Kiran would have on NDT but.


So this is all the thing is that since our interactions with the um with the program manager work managers, you know, you can tell them what's coming.


So by the time you reach a phase two proposal , a lot of this and our thinking will already be somewhat known. . So I think, uh do you have a lot more um we have I have to stop um at 11 I think it's yeah do you have any more uh significant things of name?


Otherwise, I want to actually ask uh one question of Miriam, which is do you want us to package this in some way for you to show uh I see in two weeks or we can just see that could be.


Yeah.


So let me uh, I'm working through the code today and tomorrow also with the NDD I'll tell you by the end of this week.


I can call some functions of the agent you guys have here so we don't need to package it.


Something like that the network we call network agent network agent says this is this something like that.


yeah. . So you you're pretty close to finishing what you have, right?


Ling?


Yes, just example.


And after the after the reserve, it come and modify and the release, that's all.


Yeah.


But you're going through this true phases of making a reservation, making a commitment before you actually tell the uh workflow agent to actually use those resources, right?


yeah. . Sounds good.


This looks good.


Yeah, and yeah.


So for the next week how we are we are going to implement the round high and round high stage and learning stage.


In the round high stage we will go to do the darkonosis and the detect the probleml happening in the little work, like that the thing is low or link outage.


Okay. Sounds good.


Okay, we should have yeah, I'll work on the NDT with so I sent an email in the morning.


I'll schedule some time tomorrow to talk to the students and go over how the entity agent is gonna look like um yeah so and then I'll go over the code and the demo and see what we're actually presenting in two weeks.


Okay and stuff.


Okay.


Okay.


Right. Uh I think we're on time so I'm gonna let everybody go so thank you thank you very much 




Was this transcription useful or not useful?
<!-- END RAW TRANSCRIPT -->

</details>
