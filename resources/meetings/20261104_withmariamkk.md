# 2026-11-04 与 Mariam、KK、SB、Aroan 的单独会议：VIT 启动、NDT 接口与职责、SC demo 和 Phase 2

> **日期与参会人**：按用户指定日期记为 2026-11-04；参会者为 Mariam、KK、SB、Aroan，以及 Linxuan。转录中 Aroan 多次被识别为 Aaron；截图邮件列表中出现 `Welch, Aaron`，本文沿用用户给出的 Aroan，并在相关处保留 Aaron 的对应关系。
>
> **材料**：用户提供的完整英文自动转录、三张截图，以及 RPyC 文档链接。转录没有时间戳或可靠的 speaker labels；下文能从上下文判断的发言注明姓名，无法可靠区分学生发言的地方记为“学生方/有人”。署名依据语境，未经回听确认。
>
> **记录范围**：包括安装与屏幕共享操作、技术分歧及澄清、资源申请、SC demo、HPE、Phase 2、个人经历与玩笑；附录保留完整原始转录。没有把先前问答中的建议补写成会议决定。
>
> **截图保存状态**：三张截图在本次消息中可见，但可访问的附件目录只有转录文本，没有原始图片文件。因此本文在对应位置逐项记录截图内容，未创建伪造截图、未使用缺失的图片引用。原图尚未落盘到 `resources/imgs/`。
>
> **关联材料**：[11 月 3 日 SciNet 会议](20261103_scinet_5verbs.md)、[NDT 会前问答](../notes/20261103_withndt.md)。

## 一 会议形成的当前理解

1. **先把 VIT 跑起来，再解决宿主机调用 VM 内代码的问题。** 现场完成了 OVA 解包、VMDK 导入 UTM 及虚拟机启动过程；会末认为这一启动步骤已取得进展。但转录没有展示 Network Agent → adapter → VIT 的完整控制和反馈闭环。
2. **需要区分 NDT 本体、简单的 NDT adapter，以及更高层的场景比较/调度。** KK 认为 adapter 只负责 API 转换；Mariam 最初设想的“运行多种请求组合、返回评分或优化结果”的 agent 与 scheduling / Network Agent 有重叠，建议把其中的调度部分与 Scheduling Agent 合并考虑。
3. **当前设计是模块化协作。** Scheduler/admission control 处理竞争请求及选择，Network Agent 维护 ledger 并提供网络 offers，adapter 把网络控制请求转换给 VIT，Telemetry Agent 提供观测。会上画出的图是当前讨论稿，明确可能继续变化。
4. **真实 SENSE 调用不是近期必须完成的演示目标。** 现阶段重点是在 NDT 上展示能力；但 VIT 支持哪些控制和 telemetry 接口、与 Mininet 相比的必要增益，都还需向 VIT 团队问清。
5. **SC 可以展示可运行的局部链路。** 不要求整套系统完成；Mariam 希望至少让 virtual infrastructure twin 和接口部分运行，结合现有 Network Agent demo 讲清故事，并核对 gate metrics。
6. **Mariam 强调交付与 Phase 2 的紧迫性。** 她报告管理层认为其他团队已展示 gate 进展、资源使用和合作布局；拟推动资源申请、ESnet 等合作、Google/NVIDIA 等潜在产业合作，以及更鲜明的 demo。

以上是本次讨论的阶段性理解，不等于所有接口、组件归属、资源申请和里程碑验收已完成。

## 二 开场：寻找镜像、共享权限与 UTM 配置

### 2.1 从 OVA 找到 VMDK

Mariam 已下载 UTM，面对“创建新虚拟机 / 打开已有虚拟机”的选项，先问是否应该打开已有虚拟机。学生方说明，之前成功采用的是新建虚拟机：**Create New → Emulate → Other**，然后使用现有磁盘镜像。

大家在共享的 Google Drive 中寻找 VIT 文件：

- 一度打开了 Python 相关文件夹，又转到 `VIT source` / `STKVIT` 相关目录。
- 转录中 OVA 文件名类似 `STKVITV one002.ova`，后面又说 `STKVIT one OVA`；没有足够依据恢复唯一准确文件名。
- 有两个候选文件/目录，学生方认为两个 OVA 应该都能用，并指出都包含所需磁盘文件。
- 屏幕上两个文件显示相同大小“6.93”；转录没有说清单位，不能据此认定精确字节数。
- 需要先下载并解包 `.ova`，取出里面的 `.vmdk`，再给 UTM 使用。

Aroan/Aaron 此时加入。Mariam 问他是否能打开共享目录；他回答目录受限，已登录账号并提交访问请求。Mariam 当场处理权限，表示现在应能访问。等待下载时，话题转向 Genesis 可申请资源。

### 2.2 返回 UTM，逐步设置

资源讨论后，Mariam 表示 OVA 已下载，问是否要“unzip”。学生方建议用 `tar` 解包；转录中的参数口述类似 `xvf`，没有保留完整命令和文件路径。解包后成功看到了 VMDK。

现场指导的配置为：

| 项目 | 会上设置/说明 |
| --- | --- |
| 创建方式 | 新建 → Emulate → Other |
| Architecture | 保持 x86_64 / Intel 对应项 |
| CPU | 2 cores |
| RAM | 约 6 GB |
| UEFI boot | 取消勾选 |
| 启动介质 | 先选 drive image，再浏览选择解包得到的 VMDK |
| 名称 | 可自由命名；现场使用类似 `VIT test one` |

这些是会上为启动尝试采用的设置，不是经过测量的最低资源要求。KK 听到 6 GB 后打趣问为什么要这么“大得吓人”的内存；学生方解释只是最初测试时这样设置，**没有测过实际内存使用量**。

操作中的小插曲也包括：

- Mariam 一度共享错窗口，停止共享后重新选择正确画面。
- 浏览磁盘文件时，Mariam 说文件似乎之前自动消失/被删除过；双方重新定位并选择 VMDK，没有明确查明原因。
- 学生方先让浏览文件，随后纠正为先选择 drive image 再浏览。
- 虚拟机启动需要等待；期间开始讨论 agent 接口。后续有人看到它在启动 Ubuntu，具体系统版本未出现。

## 三 Genesis Partnership Exchange：可申请资源、账号与收费顾虑

### 3.1 Mariam 展示资源入口

等待镜像下载时，Mariam 展示 Genesis Mission 的 partnership/resource exchange，说明项目可以请求合作伙伴贡献的资源。她搜索 `google`，页面返回三个结果。

**截图 1 可读内容：Genesis Mission Consortium 资源目录**

- 地址：[资源目录，搜索 google](https://partnerships.genesismissionconsortium.org/resource-inventory?q=google)。
- 页面说明：浏览 consortium 成员贡献的资源，判断是否符合项目需要，再提出申请。
- 结果数 3，页面每页显示数量选择为 8。

| 资源标题 | 提供方与类别 | 截图中的用途说明 |
| --- | --- | --- |
| Agent Compute Units (ACUs) - Devin Platform Compute | Cognition AI, Inc.；TOKENS / CREDITS | 与模型无关的云端计算单位，用于自主 AI 软件工程 |
| Google Cloud Frontier AI & Credits for Scientific Discovery | Google；TOKENS / CREDITS | GCP credits、Gemini Enterprise、Google DeepMind AI for Science 工具、模型及配套 GCP 基础设施；列出 AlphaEvolve、AlphaGenome、AlphaFold3、WeatherNext、AlphaEarth Foundations |
| W&B Weave | CoreWeave Inc.；IP / SOFTWARE | 逐步追踪 agent session，评估输出质量、发现失败，支持团队已有的 agent frameworks |

Mariam 口头认为 Cognition 的资源可能用来运行模型/agent；截图的具体描述则指向 Devin 的自主软件工程 compute，因此两者不能自动当成同一种通用模型额度。

她把 W&B/Weave 介绍为 LLM/agent 的观测与评估软件：查看输出质量、agent 做了什么、调用次数等。这里的 telemetry 指 agent 执行追踪，不是已经接通项目的网络 Telemetry Agent。

她还浏览了 Frontier 等 compute 资源，认为可以申请 GPU compute hours 来运行 AI agents。另一个资源名在转录中类似 `valenter`，无法可靠恢复。她认为 NRP 后续也应进入类似资源渠道，但当前页面尚未看到它，并说仍在等 John 提供正式文档。

### 3.2 申请方式与登录

KK 问资源是按时间限制还是其他方式提供；Mariam 回答类似向 HPC 系统申请资源，需要填 GPU/compute hours 等信息。她希望学生看看目录，提出项目需要申请什么，让项目后续有 tokens/credits 可用。

学生方有人尝试打开网站但未成功，问是否需要账号。Mariam 解释：

- 网站需要登录，各人应创建自己的账号。
- 她已注册，并拿到一个 Genesis ID。
- 她不确定该 ID 能否共享，猜测项目内可能使用同一个项目 ID；又说表单中的该项似乎可选。**本次没有确认“同项目必须共用 ID”的正式规则。**
- 她会邮件发送入口，大家注册后浏览资源目录。

KK 说明，当前实现大部分只需普通 compute，还没有真正调用 LLM，因此一直用 CloudLab。但团队很快会需要 LLM API access，可以考虑 NRP 或 Genesis 资源；他向学生确认这一点。

Mariam 建议，即使暂时用不到，也可以考虑先申请一些 tokens、科学发现 cloud credits 或 compute hours。她浏览的申请信息包括项目起止日期、项目说明、所需算力/额度、collaborators 等。

### 3.3 Google credits：先弄清计费、有效期与数据使用

Mariam 读到 Google 项目可能提供 GCP credit allocation，获批方要签 engagement agreement，涉及从额度分配起约一年的使用期；口述部分受转录影响，具体合同条款并未独立核实。提交申请也不保证获批或分配额度。

由于 Google 联系人一直给她发邮件，她会直接问：如果项目申请这些资源，是否会向项目、个人/团队或所在机构收费。

KK 对费用和平台依赖有明显顾虑，讲了 UCR 过去的 GCP 经历：

- 他回忆学校曾有大约一百万美元的 allocation，并支付了大约一百万美元。
- 据他的叙述，额度约一个月就用完，一些教师已经依赖该平台，后续很难退出。
- 金额、时间和因果是他的现场回忆，不是本记录核实的采购事实；他的主要意思是不能被优惠额度吸引后陷入持续收费。

他表示，如果资源真的是一年内可用、使用条件合适，例如有足够或不限量额度，Phase 1 可以考虑采用，到 Phase 2 再评估后续安排。**没有在会上确认 Google 实际提供 unlimited use。**

KK 也说 John 提到的 NRP AI 服务可作为免费起点；如果 Google 提供资源，或加州大学系统与 OpenAI 的安排落实，也可能使用。后者是会上提到的潜在安排，不是已经获得的项目权限。

隐私方面，KK 表示 UCR 账号使用 Gemini 有“不把内容用于训练 Gemini”的保障，但不知道这次 Google credits 是否适用同样条件。Mariam 表示会一并询问并记下这些问题。

## 四 展示当前 mock 网络和 SENSE 风格接口

虚拟机启动期间，KK 问怎样写一个能调用 VIT 的 agent。讨论回到 Linxuan 当前代码：现在用简单的 Python mock 网络，里面有 topology 和少量接口。

Linxuan 屏幕展示 mock/SENSE 相关代码和 API 定义，介绍 `propagate`、`commit`、`cancel`、`modify` 等四五个关键操作：`propagate` 对应资源预留，再经 commit 提交；可以取消和修改。他还展示 service instance ID 和 action 的 API 形式。

KK 确认自己的理解：现有代码与这些 SENSE 操作相映射，mock 也提供类似的接口。如果 VIT 理解同一接口，就能替换调用；但他预计 VIT 未必符合 SENSE API，因此需要一层针对具体 twin 的适配。

Mariam 一度问，是否 mock 会写一个 Python 文件，再由 VIT 读取。这是她在探索调用方式时提出的问题，**没有形成“系统通过写 Python 文件交换请求”的决定**。KK 随后开玩笑说自己先闭嘴/静音，让学生解释。

> **术语精度**：这里记录的是现场对“SENSE 风格接口”的说明，不代表项目中的 Python 方法签名就是原生 SENSE API。二者差异另见 [NDT 问答 Q6](../notes/20261103_withndt.md)。

## 五 VM 内外怎样通信：每次启动，还是常驻服务？

Mariam 说共享目录里已有一些 Python 示例，问是否可以将 NDT agent 映射到这些脚本。她最初设想的流程是：

1. 外部 agent 调用 NDT agent。
2. NDT agent 启动 VirtualBox/虚拟机。
3. 装载参数，运行 simulation。
4. 收集结果，关闭虚拟机。
5. 向调用方返回结果。

学生方提出另一种方式：**VIT/VM 持续在后台运行**，上层 NDT agent 与 Network Agent 交互；当 Network Agent 发出 SENSE 风格的控制请求时，适配层在 VM 中的 VIT 网络执行预留等操作，并返回 acknowledgement，不必每次重新启动 VM。

Mariam 接受常驻运行可以是一种选择，但表示自己没做过从本机 API 调用 VM 内程序，需要研究宿主机怎样把参数交给 VM，VM 内程序怎样执行修改并返回结果。

被讨论的实现方向包括：

- 用本地或远程托管的共享目录存脚本/请求，让 VM 内程序持续读取。
- 有人希望采用 event-driven 方式，觉得比不断读目录更有效率。
- 现阶段不一定把效率作为首要目标，但需要在可接受时间内拿到响应。

**本次没有定下共享目录轮询、RPC 或其他通信方案，也没有展示远程调用已经成功。** 用户随会议材料提供的 [RPyC 文档](https://rpyc.readthedocs.io/en/latest/) 与这一问题相关；转录没有明确出现 RPyC 名称，故不能据链接推断会上已选定它。

Mariam 还强调当前 guardrails/项目范围首先要求在 NDT 中演示，不要求立即执行真实网络上的 SENSE 调用。SENSE 接口设计可以保留，但最终需要接入模拟环境。

## 六 关键争论：NDT agent 是接口适配，还是场景优化器？

### 6.1 Mariam 最初设想：比较竞争请求的多种组合

Mariam 对 NDT agent 的期待不只是启动 VIT：给定一组配置或多个提交给 admission controller 的请求，NDT agent 应运行不同场景，比较怎样组织这些请求，再返回优化结果。

她用类似 timetabling 的比喻说明：请求按 AB、BA、BC 等不同顺序/组合组织，分别在 NDT 中仿真，得到不同结果；可以返回一个优化 schedule，也可以返回三种场景及各自的 score，让 Network Agent 决定采用哪个，再 commit。

她明确说这个 NDT agent **还没有写，正准备开始**，所以先来弄清 VM/VIT 怎么运行和调用。这里不是已有 agent 的功能展示。

### 6.2 KK 与学生指出：这会覆盖已有的 scheduling / network 决策

KK 认为，Mariam 所描述的一部分功能已在 Network Agent 的设想中：理解多个请求的资源需求，判断使用哪些 links、多少容量，并结合优先级等信息。因此两个 agent 的功能有重叠。

Mariam 提到区别可能是 Linxuan 目前自己创建 topology、填入数值；学生方澄清，之所以使用 mock topology，是暂时没有接入真实网络或 emulator，并不表示 Network Agent 要永久充当网络环境。NDT 应成为提供真实/模拟网络拓扑与行为的环境。

学生方也区分：

- Scheduling Agent 决定哪些 transfers 要运行。
- Network Agent 提供可行的路径、时间和带宽 offers。
- Emulator/NDT 按选定配置执行或模拟端点间的传输。

当 Mariam 再次描述由 NDT agent 比较多种顺序、返回优化 schedule 时，KK 指出，它又包含了概念上 Scheduling Agent 的工作，以及当前 Network Agent 的部分工作。有人问，为什么还要另行生成这些场景，既然 Network Agent 已经在选择路径和输出 offers；双方继续澄清层次。

### 6.3 KK 用多实验请求重新解释模块关系

KK 画图并给出如下例子：

1. Scheduler 收到多个实验请求，请求同时涉及计算、实验设施和网络资源；此处先只看网络。
2. 实验一需要在某时间从 A 到 B 传输，实验二从 C 到 D 传输；两者可能共用一部分 links。
3. Scheduler 把需求交给 Network Agent。
4. Network Agent 从真实网络或 NDT 获得 topology/capacity，从 Telemetry Agent 获得各 hops 的观测，再为每个实验返回可行 options。
5. Scheduler 根据优先级等因素选择，再要求 Network Agent reserve/commit。
6. Network Agent 告诉真实网络或 NDT，要在哪些 links 上配置哪些资源。

KK 原先理解的 NDT 前端只是把第 6 步的控制请求转换为 VIT 接口，**不做额外的调度或优化决策**。为避免名字造成混淆，他临时把 Mariam 设想的高层组件称作 **“Mariam's agent”**，建议它可以承担 Scheduling Agent 的功能。

这样，Mariam 的场景比较/请求协调与 scheduler 一起考虑，Network Agent 继续负责 topology、容量、offers 和 ledger；简单 adapter 负责把控制请求交给 twin。

### 6.4 是先仿真再选方案，还是用容量账本估计可行性？

Mariam 仍关心谁来实际运行全部 scenarios。她解释选择这个 VIT 的原因：据她了解，它基于真实 DOE 网络的历史数据/实验数据，模拟或 emulates 网络传输，并了解 topology、链路容量及网络行为。她不知道它是否会拉取最新数据，需要再查资料。

会上举例，一条链路可能是 50 Gbps，另一条 10 Gbps；在 100 Gbps 链路上传送约 80 Gbps，可以观察约 0.8 的 utilization，以及 loss 和 delay。**这些是解释功能时的举例，不是现场测得的 VIT 输出。**

KK 说明自己的原先假设：

- 以 ESnet 的虚拟电路/预约资源为背景，Network Agent 根据容量账本及端到端时延估计判断是否满足 SLA。
- 不一定对每个候选组合都运行完整 packet/traffic simulation，去测 bursty flows 导致的排队、延迟和丢包。
- 如果确实需要仿真来核验可行性，可以在 Network Agent 与 NDT 之间增加该能力；但要明确它与现有容量估计、调度选择的边界。

双方没有在会上证明“纯估计已足够”，也没有选定“所有 offers 都必须先仿真”。这是两种方法及其职责的讨论。

### 6.5 即时流量是否超出了 ledger 的适用范围？

Mariam 问，ledger 更像提前预约；临时到达、需要马上运行的 just-in-time/on-demand flows 怎么处理？这些流量事先没有 reservation，需要利用 topology 找到位置。

KK 回答，新的 on-demand flow 也可把需求交给 Network Agent，例如从 X 到 Y、至少需要 N bits/s。Network Agent 检查当前账本是否存在满足最低带宽的可行路径，再把此次分配加入 ledger；后续请求只看到剩余容量。优先级等问题可以再继续讨论。

这是 KK 对模型能力的解释，没有现场新增 on-demand 实现或测试。

### 6.6 当前落点：简单 adapter 与较高层的 Mariam/scheduling agent 分开

KK 最后强调，如果 VIT 有特殊 API，adapter 的工作就是翻译 Network Agent 的 SENSE 风格请求，交给 VIT，并传回结果；不需要额外 intelligence 或 decision making。会上称其为 “dumb/simple adapter”，指职责简单，并非评价实现没有工作量。

Mariam 复述并确认当前理解：

- Scheduler/admission control 与 Mariam's agent 的调度部分一起考虑。
- Mariam/scheduling 层调用 Network Agent。
- Network Agent 调用 NDT adapter。
- NDT adapter 调用 VIT/NDT。

她问大家是否同意，也明确说随着开发这张图仍可能变化。会末她又表示，短期不同 agents 的功能有些重叠也可以先推进，后续再拆清。因此不能将本次讨论写成“已正式删除独立 NDT agent”或“所有重叠职责已完全解决”。

## 七 Telemetry、拓扑与真实流量：图上的数据从哪里来？

### 7.1 VIT 是否同步当前 ESnet 流量？

SB/学生方问，NDT 仅表示 topology，还是也反映此刻 ESnet 正在发生的流量？Mariam 回答，不是直接表示今天真实 ESnet 的实时流量；她理解现有文件主要对应历史实验/数据，把其中的 transfers 放进 VIT 执行。她需要重读材料确认。

她还说，之前 VIT 的使用方式似乎只是把实验转换成 transfers 后运行，没有当前讨论的中间协调层。以上是她的理解，不是对 VIT 最新版本的独立能力核查。

### 7.2 Telemetry Agent 的来源与消费者

讨论明确：

- 未来部署在真实网络时，Telemetry Agent 从真实网络获取观测。
- 目前在 twin 上测试时，它从 twin 或相关适配层获取指标，再给 Network Agent，后者更新 ledger。
- KK 说，先前曾考虑 scheduler 直接问 telemetry；当前这条路径主要由 Network Agent 消费网络 telemetry。
- Topology 及链路标称容量应从网络/NDT 获得，例如通过文件供 Network Agent 使用，而不是永远手写 mock。
- Telemetry 提供 utilization 等信息，Network Agent 将其叠加到容量/自身资源账本中，估计可供新请求使用的 residual capacity。

会上提到真实环境可以通过 Prometheus、SNMP、sFlow 等获取观测。学生方关心 John 前一天分享的 Prometheus APIs：如果 Telemetry Agent 按这种接口轮询，NDT 是否也能暴露类似接口？

KK 的态度是，先使用 VIT 实际具备的能力；若暂时没有某些 telemetry 接口，就先做能做的部分，随着 VIT 增加能力再利用，必要时也可以增加其他 agents。**没有确认 VIT 已经提供 Prometheus API 或实时 loss/delay 输出。**

### 7.3 截图 2：会上架构草图逐项记录

原图保留了讨论中的临时命名和拼写，如 `Schedular (Admission Control)`、`NDT adaptor agent`、`Mariam agent`；不是正式接口规范。

图中组件和关系如下：

- 左侧 `Requests` 用两条输入箭头指向 `Schedular (Admission Control)`。
- Scheduler 分别连向 `Network agent (keeps ledger)` 和上方 `Mariam agent`。
- Mariam agent 与 Network Agent 之间画了双向联系。
- Network Agent 与 `NDT adaptor agent` 之间画了请求/返回方向的两条箭头。
- NDT adaptor 与 `Network digital twin` 之间也有双向箭头；twin 旁附有 `Topo` 云形标记。
- Network Agent 向下连到 `Commit` 方框。
- NDT adaptor 向下连到 `Telemetry agent`。
- `Prometheus agent` 指向 Telemetry Agent。
- `Real network` 云形框指向 Telemetry Agent。
- Telemetry Agent 指回 Network Agent，箭头旁写着 **`now?`**，保留了当前状态/时机仍在讨论的含义。

图中的独立 `Commit` 框用于讨论流程，不据此断言已实现独立 Commit Agent。图中同时保留 Scheduler 和 Mariam agent，也体现高层合并方式尚未最终落实。

## 八 VIT 相比 Mininet 的必要性，以及 HPE 人力

随着调度、网络决策、telemetry 都拆到独立组件，Mariam 问：剥离这些功能后，是否实际上走向 Mininet 路线？

KK 表示，按他对 Mininet 的理解，目前还没有看清 VIT 在这个模块化架构下有哪些必不可少的额外能力。他希望问清：已有 DOE topology 和带宽等信息，是否可以直接给 Mininet，让它 emulates 所需网络。

大家也短暂谈到自己重做 Python simulation：有人担心要时间、由谁来写；另有人认为，把图结构和带宽数据给仿真器/Mininet 并不复杂。关键还包括**怎样可信地模拟高于宿主物理能力的高带宽 links**。没有决定放弃 VIT 或立刻重写模拟器。

Mariam 表示会向 VIT 相关人员问：当前需要一个外部 adapter 去调用 VM 中的 VIT，具体应该怎样做；若只需要底层网络行为，VIT 相比直接用 Mininet 的增益是什么。转录中的人员名类似 **Nagi、Anis/Anice**，未确认拼写。

KK 希望 HPE 能安排长期开发/维护 Mininet 的人帮忙，提到 **Bob Lantz**（转录为 Bob Lance，按技术语境推定姓名，待核对）。他说曾与其讨论过 Mininet 的扩展性，以及怎样实时反映运行状态供 scheduler/Network Agent 使用；对方曾估计专门花一个周末可以做出一些工作。KK 说不希望占用别人周末，但如果有一周投入，应有希望推进。这不是已签订的人力承诺或工期保证。

相关闲聊和语气也保留：

- KK 半开玩笑说，大家应该“脱鞋敲桌子”，让 HPE 负责人把该专家安排进来；负责人姓名在转录中类似 `Bonit`，不强行恢复。
- 他希望有人真正动手，而不是很多人忙着参加会议，并认为今天深入到实现细节的讨论是有价值的。
- Mariam 也说自己在每周会议中的困难是想法很多、实际进展较少；KK 表示理解，并支持她组织这样能推进具体实现的小会。
- KK 说自己有点像“闯进”原本该由 Mariam 和学生讨论的会议，打趣说应该闭嘴。这与前面让出屏幕解释机会的插话相呼应。

## 九 开发分工、LLM 使用与 runtime 计划

### 9.1 眼前开发如何继续

Mariam 表示会尽量在当天向 VIT 团队问到答案。她希望 UCR 学生继续现有 Network / Telemetry Agent 开发，自己开始填补中间组件，并与 Aroan 研究如何调用 twin。

KK 解释，UCR 没有在 scheduler 上投入时间，并不是拒绝承担，而是当前两位学生分别忙于 network 与 telemetry。若 Mariam 准备开发有调度能力的 agent，建议把她的场景功能与 scheduler 一起考虑。

Mariam 请 Aroan 看 adapter：宿主机 Python 脚本怎样调用 VM 内的代码并返回结果。对方表示可以研究。她还说会把他加入 scheduler/相关 agent 的工作；具体仓库、接口文档和代码归属没有在转录中确定。

### 9.2 Event-triggered 流程是否充分利用 LLM？

Mariam 问，当前这些流程看起来仍是 event-triggered，是否正确使用了 LLM 的能力？KK 表示现在还无法给出确定答案，大家仍在探索 agent 应该怎样用，并请 Linxuan 说自己的理解。

Linxuan 说明下一步 Network Agent 的 runtime 计划：发现网络问题、检测/诊断异常、提出解决方案或修复；需要时把当前场景与信息交给 LLM，让它提出方案。

KK 补充，诊断也可利用当前状态和网络历史，让 LLM 推断可能的原因。Linxuan 又提到更主动的方向：让模型控制计算机/工具去查询需要的信息，而不只是被动接收一次性输入；相关语句的转录不清，似乎强调先查询信息、不修改文件，不能据此恢复完整权限设计。

当下可先把当前状态及历史整理给 LLM，再取回建议。Mariam 回应，更主动的工具操作也许能让 agents 自己发现问题。**没有展示 LLM 闭环已实现，也没有确定自主执行修复或文件写入权限。**

会末还补充整体流程前面有 Workflow Agent，负责提交 workflow requests；图的高层范围还会涉及 networks 与 compute resources。

## 十 SC demo：演示一部分可运行链路即可，但要讲清 gate 进展

KK 转向两个额外问题，第一个是 SC/Supercomputing demo 需要学生提供什么。

Mariam 先说 demo 大约一周后，又有人说还有两周；本次不根据口头相对时间恢复具体场次。她会查看已有代码与进展，拼出一个能运行的故事：某个组件调用另一个，再调用下一个；即使只展示半套流程，也可明确称为 work in progress。

可演示部分包括：

- mock workflow requests 与 mock network 的小闭环。
- 现有 standalone Network Agent demo，像前一天学生逐步讲解的版本。KK 认为这部分容易准备，但不确定单独展示是否足够有说服力。
- NDT/VIT 的接口调用。Mariam 更希望至少把这一块与现有实现连接起来，她和 Aroan 会尝试推进。

她举例可以先列出 demo 项目：第一项 Network Agent，第二项与 NDT 的 interfacing，再按顺序运行，不必让完整架构一次全部工作。

关于 SC 的个人经历，大家有简短交流：有人说从未去过 SC；KK 随后回忆自己约在 **1999 或 2000 年**去过一次，当时刚读完研究生/刚毕业。由于句子衔接和说话人切换不清，不把“从未去过”和“去过一次”强行归为同一人的一致经历。

Mariam 说自己做过几次 SC demo，通常是：

1. 先展示项目整体图景。
2. 列出接下来演示的一两个部分。
3. 展示可运行代码/流程。
4. 听现场反馈。

她用“大约五页 slides，再展示代码”说明规模不必很大。重点是至少让 virtual infrastructure twin 运行，并按已有能力组织叙事。

里程碑方面，她会核对项目 gate/gateway 指标，判断现有展示是否可说明 gate 1 / gate 2 的进展。她说前一天向管理层更新后，管理层希望清楚表明已达到哪些 gates、项目是否 on track，因为仍期待在约一月的新 call 前看到交付。相关管理人员也会去 SC，她会发送展示日程邀请来看；转录没有可靠点名此处的“她”。

**本次没有完成 gate 指标逐条验收，也没有正式宣布 gate 1、gate 2 均已达标。** 记录保留的是准备与沟通要求。

## 十一 HPE 合同、cost share 与真正需要的贡献

KK 的第二个问题是 HPE 的情况。Mariam 解释合同仍在谈，主要涉及 cost sharing：proposal 时曾说如果项目投入降到“150”，HPE 也从自己这边投入“150”，并以人员工时等方式体现。**转录没有明确金额单位，不能写成确定的 150 万或 15 万美元。**

她说 HPE 提交过材料，但需要重新提交 cost-share 相关内容。KK 认为，如果能安排真正懂 Mininet 的人员帮忙，会很有价值。

硬件方面，Mariam 说自己看过 HPE 的文件，列出的多为软件访问、monitoring system 和数据，**没有看到硬件承诺**，这与 Harvey 曾谈到的硬件期待不同。这里是她对当时文件的报告，不代替合同核查。

KK 强调项目需要交付的是 agentic framework，硬件只是额外的“goodies”。现场也有“喜欢硬件”“拿硬件说事/blackmail”之类玩笑，但没有形成索要硬件的行动决定。

Mariam 说，参与的人多，每个人可能都有自己的议程；需要确保仍交付本项目该交付的东西。她希望框架和任务边界清楚后，按 Gantt chart 明确分派工作，让相应人员真正开始构建各自部分。

## 十二 管理层反馈与 Phase 2：资源、组队、IRI 和展示压力

### 12.1 Mariam 展示发给 Rafael 的邮件

Mariam 说前一天向管理层汇报后，把反馈发给了 Rafael。她担心团队在可展示成果、资源使用和合作布局上落后；其他团队已经声称做了很多、达到 first gate metrics。

她也质疑，合同/资源刚落实不久，其他人怎样已经完成这么多；因此这里同时包含外部团队的自报、管理层比较和她自己的担忧，不是独立排名。

**截图 3：邮件正文可读信息**

- 主题：`Resources for AMSC`。
- 发件人：Mariam Kiran；收件人：Rafael Ferreira Da Silva。
- 开头说明她向 Susan 汇报了项目进展，下面列出一些需要提醒的事项。
- 关键条目逐项为：
  1. 有些团队领先，至少他们自己这么说。
  2. 其他团队称已完成 first gate metric；Mariam 将开始检查本项目 metrics。
  3. 别人已使用 AmSC、Lux、Pathfinder 等资源，本项目仍在开发软件，尚未申请 compute；是否也应提交项目申请，先获得可用 hours。
  4. 大家已开始为 Phase 2 组队；她会看 award list 并发给 co-PIs。
  5. Phase 2 是否应策略性加入 NVIDIA、Google 等伙伴，征求看法。
  6. 项目与 IRI 有较多关联，应在组队和展示上更有策略，凸显与其他工作的差异。
  7. 有做机器人等方向的 PIs 已在展示 demos。
  8. 有团队已与 TVA、本地公司合作，将项目亮点汇报到 Dario Gil。
- 邮件最后向 Rafael 征求意见。

这里只记录与会议有关的正文，没有转录截图侧边栏中其他无关邮件、账号和私人文件夹信息。

### 12.2 要开始使用资源，也要把合作对象拉进来

Mariam 说当前还没有申请 compute，应该推动申请并实际使用，向外展示资源与项目工作相连；没有声称本次已提交申请或已经使用到这些资源。

Phase 2 方面，她认为要开始看其他项目的获奖名单、组建互补团队，并征求 co-PIs 意见。她提出 Google 或 NVIDIA 的产业合作可能有策略意义，但没有确认任何公司已加入。

她强调项目触及 IRI，即通过 API 与不同基础设施交互，而这些基础设施相关方尚未充分进入团队。她特别说，**ESnet 应当成为 Phase 2 团队的一部分**，需要推动接洽；本次没有确认 ESnet 已承诺参与。

### 12.3 其他 proposal、已公布的 Phase 2 与时间混淆

KK 提到有人正和 **Arpit Gupta、Scott Shenker** 等人组织更强的 proposal 团队；姓名按转录 `Arpet Gupta / Scotchankur` 的技术语境整理，涉及的主语/团队没有足够信息恢复。

Mariam 说，自己知道他们此前的一次 Phase 1 申请未获批。KK 的理解是他们可能冲的是另一轮 Phase 2，而不是十二月这一轮；原文的“first round”衔接不清。

Mariam 又说已有 Phase 2 项目刚公布，并说约有 **6 个来到 Oak Ridge**，所以她知道这个消息。KK 说自己没有看到 ESnet 相关消息，双方表示还要核对。

这段把已公布的一批 Phase 2、即将到来的十二月/一月 call 混在一起。**会议没有把批次和准确日期讲清，不能据此写成统一、已证实的正式征集日程。**

### 12.4 机器人 demo、对外曝光与团队压力

Mariam 说有些团队已经展示机器人和运行中的 simulation，甚至能演示控制机器人；还有人联系 TVA/本地企业，将亮点上报 Dario Gil。她担忧 SciNet 在这些方面落后，因此给 Rafael 发邮件，希望加强交付和展示。

KK 说这份反馈令人警醒，也表示学生已经尽力加快推进。Mariam 回应，知道大家做了很多，感谢学生的工作；她认为还需要更有创意，做一些其他团队没在做的事。

她建议接下来、可能下周进一步讨论 Scheduling/Mariam agent；目前先继续落实 twin 和 adapter，再逐步明确图中任务分配。

## 十三 收尾与行动项

会末，Mariam 总结今天已经把眼前的启动步骤推进了，接下来弄清调用机制；出现新的 blocker 后通过邮件沟通。她会与 Aroan 继续测试，并把刚加入的同事带到当前进度。

学生方问她是否需要一份小文档，列出在 VM 内运行 VIT、启动 transfer 的初始命令。Mariam 明确说需要，对方答应分享。转录没有包含这些命令的实际内容，也没有展示文档已经发送。

大家互相致谢、道别，结束会议。

| 行动项 | 负责人（按会上发言） | 状态/边界 |
| --- | --- | --- |
| 发 Genesis 资源入口，学生注册并查看目录 | Mariam；各学生 | 拟通过邮件发送，各自账号登录 |
| 讨论需要哪些 tokens、credits、compute hours | 团队/学生提出需求 | 未选定额度，未现场提交申请 |
| 向 Google 联系人询问计费、机构责任、有效期和数据训练/隐私条款 | Mariam | 待确认；不视为已经免费获批 |
| 获取 NRP 正式资源/集成资料 | John 提供；Mariam 跟进 | 会上仍在等待 |
| 向 VIT 团队询问 VM 调用接口、telemetry、相对 Mininet 的增益及高带宽仿真能力 | Mariam | 希望当天问到；具体回答不在本转录中 |
| 研究宿主 Python 调用 VM 内代码并返回结果的 adapter | Aroan/Aaron；Mariam 协同 | 表示会研究，通信技术尚未定 |
| 继续 Network / Telemetry Agent 开发 | Linxuan / SB | 不因本次架构讨论暂停现有开发 |
| 把 Mariam 的场景比较/协调功能与 Scheduling Agent 一起设计 | Mariam、团队；Aroan 拟加入 | 近期/可能下周继续对齐，职责仍可调整 |
| 分享 VM 内运行 VIT、启动 transfer 的简短命令文档 | 已有文档的学生，发言归属未能可靠区分 | Mariam 确认需要，转录未含文档正文 |
| 准备 SC 的局部可运行 demo 和 slides 叙事 | Mariam 统筹，学生提供现有能力，Mariam/Aroan 推进 twin | 不要求整套系统完成；优先 twin 接口与现有 Network Agent |
| 核对 gate metrics，向管理层/SC 说明进度，发送展示日程 | Mariam | 待核对，不等于 gate 1/2 已验收 |
| 继续处理 HPE cost-share，争取有效 Mininet 开发支持 | Mariam、HPE；KK 提出人员需求 | 合同仍在谈，未确认人员已到位 |
| 查看 award list，与 co-PIs 讨论 ESnet、产业伙伴等 Phase 2 组队 | Mariam、KK/其他 co-PIs | 合作与批次时间均需后续核对 |

### 尚未解决、需要后续确认的问题

- VIT 实际支持哪些控制动作，是否能映射当前 SENSE 风格 adapter；宿主机和 VM 怎样通信？
- VIT 是否暴露 Prometheus 或其他指标接口，能返回哪些状态、容量、loss/delay 数据？
- VIT 的历史数据、实时数据、Mininet 底层及高带宽仿真各自起什么作用？
- 场景枚举/仿真核验何时必要，由 Mariam/scheduler、Network Agent 还是单独组件发起？
- SC 最终展示哪几段链路，哪些 gate 指标能被现有演示证据支持？
- Google 等资源的费用、使用期限与隐私承诺；Phase 2 的实际合作名单和征集批次。

## 附录 A 资料、名称与转录校正

### A.1 用户提供与截图可读的链接

- [RPyC 官方文档](https://rpyc.readthedocs.io/en/latest/)：用户随材料提供。官方文档将其介绍为跨进程/机器调用 Python 对象的 RPC 库；此说明仅帮助定位链接用途，不能作为会议已经选型的证据。
- [Genesis Mission Consortium 资源目录（google 搜索）](https://partnerships.genesismissionconsortium.org/resource-inventory?q=google)：截图中的 URL；上文资源项目描述以截图和口述为依据，未独立核验其当前可申请状态。

三张截图依次对应：资源目录（第三节）、架构草图（第七节）、管理层反馈邮件（第十二节）；可读内容已在对应章节详细转录。原始图片文件未在附件目录中提供，尚未存入仓库。

### A.2 转录不确定项

| 转录形式 | 本文处理 |
| --- | --- |
| virgin machine / virgin box | virtual machine；口头也多次泛称 VirtualBox，实际现场使用 UTM，不能混为同一软件 |
| over / OVA；MDK / dvMDK | OVA 镜像包与 VMDK 磁盘文件；准确镜像名待核对 |
| BIT / IT / VIT | 根据上下文记为 VIT / virtual infrastructure twin |
| NDT / NDT agent 的混用 | 保留讨论演进，区分 twin 本体、adapter 与场景/调度 agent |
| mark / max network | mock network / mock SENSE |
| propaggate / comed / canal | propagate / commit / cancel；modify 可辨认 |
| ledger → lecture | 按容量账本 ledger 整理 |
| NRP / NRB；cloud lab | NRP、CloudLab，按既有项目语境整理 |
| Corvi / car we；WNB | 由截图确认 CoreWeave、W&B Weave |
| whether next / alpha Earth | 由截图确认 WeatherNext、AlphaEarth Foundations；其他模型名同截图 |
| Bob Lance；Bonit；Anice | Bob Lantz 为语境推定；HPE 负责人及 VIT 人员的准确拼写仍待核对 |
| Arpet Gupta / Scotchankur | 疑为 Arpit Gupta / Scott Shenker；未确认涉及的具体 proposal 主体 |
| Rafael / Raphael | 由邮件截图采用 Rafael Ferreira Da Silva |
| TBA / Dario Gill；AMSEC / Lu | 由截图整理 TVA / Dario Gil、AmSC / Lux；没有据此核验新闻事实 |
| gate / gateway | 指项目 gate metrics；编号、验收状态及正式要求未在本次逐项核实 |
| 6.93、150/150、一周/两周、年底/一月等 | 保留口述范围和不确定性，不自行补单位、日期或正式结论 |

## 附录 B 完整原始转录

以下逐字保留用户提供的自动转录（包括误识别、重复、口头停顿和末尾工具提示），便于回查上述整理；未添加虚构 speaker labels。

<details>
<summary>展开完整英文自动转录</summary>

```text
OK so I was able to download UTM to create new virgin machine open existing virtual machine so we should open existing virt two machine, right?


Oh you can also create new um We did create new and we chose emulate and in emulate we chose other other OK, and then that gives us a just down before that uh do you have the uh dotvmDK file yeah I think they do I have the so the S stay here BIT I sent you guys I think there was one file which was STKVITV one002.ova and uh we extracted that file and um we got the dvMDK file inside it and this is the one we have to use in the UTM just one second I'm looking for this file.


Okay.


OK, let me share it OK Aaron's here I Aaron so we share the Google Drive OK so in this you're saying to extract the yeah the there is yeah I think that was just one second.


I have another there is another folder also yeah yeah I think there was there were two things so I'm just looking at which one we use used um no, this is a Python can you go inside that SK hyphen VI the first one's this one is This is the Google Foldter.


I sent you guys. Which one we used to take care of me to dinner on do you have the VIT source yeah VIT source folder can you go inside that and STKVIT I I yeah I think it's it's it's the STKVIT one OVA the yeah I think either of these will work so yeah big and they will contain the and once we download and once we extract we it have the file Okay.


Yeah, both are same size 6.93.


Aaron, did you get the folder Yes, but it is access restricted so it made me log into account and then request access. See if I can get the OK, so you should have access now So while this guy this thing is downloading, I wanted to show you guys this . Can you see this Genesis mission partnership exchange?


So these are a number of resources that are available to us that we can request.


So for example, I put in google , uh and three results came up.


So for example, we can request tokens from cognition AI.


This is what they're offering autonous model agnostic plow compute.


So I think this we can use to run our models. Um Google is offering tokens also for um using their infrastructure and also access to their models, alpha fold, whether next alpha Earth. In case here.


Okay.


And so car we is basically offering uh WNB. So this is basically just um software you can, if our project uses LLM, we can go and see the quality of the LLM, the single agent, we can track it's how how many how many calls it's doing, et cetera.


So Corvi was offering their t teleometry stuff, uh use of their software, so we can request resource, uh, which will basically be time uh at collaborators whose so everybody and uh submit request kind of thing.


So we so this is um hi K K. So I'm just showing like the different resources uh resources that are available to the genesis thing. Um so we also have so agent compute we looked at this.


We can have on frontier, we can request some resources here to run our AI agents.


Is it limited time Kan or a number of like like it's a request you're making to an HBCC system so how many hours and stuff of GPU compute um valenter also is available here so I think NRB should come through this when they get uh their stuff they are still not here because I've I'm still waiting for John to send me like physical um documentation but uh if we want we should submit so we we should submit some resource requests here.


So I'm sharing this with the students to see like what their thoughts are, what should we put in requests for?


Uh so we can have those tokens or something available for the project to use.


Can do you guys have access to this?


Genesis consum partnership exchange?


I try but it' it's it's it's not opening actually.


Is it that we shouldina for the?


Yeah, I signed up.


They gave me a genesis ID.


I'm not sure if I can share that ID but I think I should because everybody on the project should have the same ID but it's optional to put in so you have to sign up and then you'll see all of this resource inventory available.


So the thing is at the moment much of what we are doing is only requiring some compute without actually looking for any LLM access and so that's why we've been just working with cloud lab.


Yeah, I think uh we whether it is NRP or anything else from genesis, we will soon need that for LLM API access.


Brightane Sean and Surba Yeah.


So So is this restricted site these guys have to get to sign up for access to this site?


So this is a login site.


Yeah, you'll create your own account. And login So yeah, I think it's yeah you could just basically request a login create an account and login I'll send this in an email. Uh so have a look at like the resources.


Otherwise I was thinking, you can submit like some tokens even if we don't use it, we can submit for cloud Redits for scientific discovery other compute hours.


So about this, they give us credit allocation on GCP for the project Irish sensored governor, awardies will sign an engagement agreement to access Bubbal services based on the program pickoff one year from credit allocation.


So we request this so you can request how many computer hours, projects start and date, project details.


We can put all the collaborators usually rip us off here.


I can check with them and it't guarantee approval of location yeah, because this Google guy has been emailing me so I can ask him like if we if we put in certain requests, will you be charging us yeah.


Yeah, I' charging us meaning, you know, whether it is your product, our project or us our institution, what with we like not to be get ripped off because what happened when we signed up for GCP in UCR we had like 1 million dollar allocation or something and UCR paid them 1 million bucks that got used up in a month we were all lot of our faculty got screwed because we were stuck with having started depending on it and then now, you know it's like can't get out of it.


So if if this is a unlimited use or something and it is for one year, yeah, we can work with it for phase one right and get to the point where afterwards for phase two, we can see what to do.


Okay.


I will check with them on this . NRPAI stuff that uh John mentioned even that might be a good beginning for us is free so yeah get started with that while if Google provides us or you know there's another arrangement that you see is our University of California system is looking to have with open AI so we could use that as well . But one of the things that we have withemini from our UCR accounts is that what we do doesn't get used for training Gemini so there's a little bit more privacy assurance I don't know if that would be the case with this compute that Google offers check all of these questions. Them down. And yeah.


So, okay.


So I wanted to show that, but yeah, okay.


So that's good.


And then going back to what we're doing so okay so I've downloaded the over file that has to be extracted and that will have the.MDK file so it's already an over like you want me to unzip it but it's oh yeah yeah um you can unzip that like using the tar command -us XVF yeah yeah OK and STK OK it gave me a VMDK file yeah yeah yeah that is the one will have to use in the UTM so um if you go to the UTM uh window and then there um I I think you already chose the create new emulad in other So then um I think the architecture we can leave it at X 8664 and then the CP would be two c and RAM can be like maybe six G then um um uh can you uh share the OK let me share like what I'm doing It screen is a chair.


No it's sharing the wrong screen stop sharing share this one yeah so so I came here oh yeah uh that can be intel and this this ram you can increase it to six GPs yeah yeah that should be fine.


Then core would be two and then you can say continue Why do you need such a guard awful amount of memory It was just like for initial testing I just saiditted that amount.


I actually haven't measured the usage and um you can unselect UEFI boot here yeah and then you can browse actually actually actually uh just select drive image there before before browsing here.


So that drive image browse and here you select the VMDK file that you just extracted.


There is. Being done, but I can because I think it automatically deleted itself so if under now let me say it OK it's now it's VMDK but I think it stood this up last time and then it okay same thing I' sorry so here okay so we need care yeah this can be just continue.


Should be fine. Here you can give any name if you want for this VM.


Otherwise you can just see oh okay VIT test one and this will it take some time how do we write an agent that calls the IT I'm I sorry we didn't.


She was bad he would just use a similated pyson file to simulate the did he or says so you use the mark network uh emulator, right yes you had some EPIs that you used to call this mark network yeah later we use us we use the same ap shy as the provided so that sense API if VIT can understand it then we should be able to just take those calls and stick it to calling VIT correct but it probably doesn't confound to that sense API so there might be a need to adapt these things for whatever digital twins that we decide to use Mariam.


Okay wait um so the VIT is like you have to run the virtual box to actually run the VIT, right?


So you're saying that the mock thing will write out a python file, which the VIT will breed, right?


I shut up.


Let me actually mute myself so that way don't have to my mouth it's Sure yeah, while my virt machine is booting up so it's a bundo and stuff . Okay.


While with you okay do we do here where should I start?


Here we have a mark network.


It very simple.


It has a tarpology and a sound simple interface.


So let's look at that interface and say okay how did we call that you know one of those calls if yeah, they say our max and this is out is the class so it contains a network and have some API that are the same as the real sense provided like propaggate.


That means that want to reserve this this kind of link and a comed and a can and modify we only have this four or five important interface because because we can see in the oh sorry.


This is the sense since A shire file and uh Since I provided a such things to manage the to manage the link like we can use the food. Instance, its ID and action.


Theashing can be such as canal apparitions, like Kamed really.


So you're showing, right?


Yes, yes so your code maps to these AIs is what you' , it's you also provide this kind of interface.


So like so little work agent the kind can you use your ended agent similarly.


Yeah.


So, uh the NDT agent, there are some examples in the folder like Python scripts , so should we map the NDT agent to those?


So when you when you call the NDT agent, the NDT agent will first start the virtual box, pull those values, run that simulation, collect the results, close the virtual box, and send the results back to the other agent calling for that information. So for the network agent, it will the routed notot talk to the Vot the agent Oh, yeah, so right now our the NDT agent is inside a virgin box, right?


So our NDT agent needs to call this virgin box, run it get the results and then communicate back. Another way would be if um to win or need to spawn the uh VIT every single time I I think instead of the VIT is like always running and then um let's say we have the NDT agent which is running at a higher layer and then that is uh interacting with our network agent.


Now, when the network agent makes the um sense API calls, the NDT agent should then uh make those reservations on the actual um, the VIT network, which is running in the virtual machine and then it has to uh acknowledge the network agent that the reservation was completed.


So we may not need to spawn the VM each time.


Yeah, so the VM is constantly running in the background, but it's taking some information.


Okay.


So we need some way of I I've never done this whether an ABI call goes into a virtual box scenario uh so we can check how the the thing happening inside the virtual machine is reading information from the local machine and doing changes Yeah.


I think there must be like we can have a folder where all the scripts are and the the agent in the virtual machine is constantly reading that folder.


That would be either hosted somewhere or hosted locally.


Yeah.


I' not I wish it could be even driven.


It'd be a lot more efficient, but I don't know if we care about efficiency at the moment.


Just want to make sure that we get the response in a timely basis, right?


So at the moment, like for our guardrails, right, we only have to demonstrate this in a virtual machine.


Like we only have to demonstrate this on the on the virtual uh sorry, the NDT because network digital twin we don't actually have to do a sense call because we said we't do real stuff. Utilize, but uh no sense it's fine to have, but we eventually need to demonstrate in the ndt. , what ised agent is her before.


It's like just start up the he and then if you do nothing, it was should do It's supposed to run scenarios like uh you you set a configuration up, then you call the NDT agent.


It checks all the different scenarios and it returns back and optimization result and then you say commit after that so as far as we are concerned, we could think about our sense calls as going to the entity agent the entity agent translates that into what it needs to do with VIT can we think like that why agent that lately taught you the just to use the adapter?


So we were so this is to account for those kind of situations that you have multiple calls, submitted to your admission controller and the admission controller now needs to allocate resources to all these multiple calls, so the admission controller will call the NDT NDT will run various scenarios like how do I how do I organize all of these calls and then once it has an optimized portfolio, it returns back to um the the agent who's going to do the actual committing.


So it could be the sense API or something so it goes back to the sense and then sense basically offloads, okay, these are my commit.


So it's basically uh yeah.


So at some level, the work that you are talking about the NDT agent doing is partially what I think we were considering to do in the network agent, which is to deal with multiple requests understanding their resource needs in terms of the network in on which helps how much capacity determine which we have incorporated priority, but we were envisaging that also would be part of the network agent so it's sort of these two guys are doing some similar functionality, I think Am I rising one or not so the I think the difference is you're creating your own typology, right?


And you're assigning all the values apology creation was marked apology because of the lack of real network or an emulator behind us if I'm saying anything wrong, please correct me link. The emulator should be this NT right?


Because the NDT should be uh should have an apology of the DUE network and will have all the values of the network like loss through put and everything.


So that will be the emulator . But emulator should it should simulate that should traffic, but when at which time interval what traffic has to run, that is something we are doing with the network agent.


The network agent is uh uh sorry, the scheduling agent will actually decide uh which transfers have to run.


The network agent will give the offers as to it, which schedule in which time inter that transfer can happen, and the emulator would just um simululator like just performed send some traffic between those two end points which the emator has I I don't think the NDT should uh do the so there are two things that Miriam is talking about one is the network digital twin itself a front end to that which is this NDT agent that is doing some of the mediation across multiple requests to the network, which is represented by the NDT So this NDT agent and network agent are sort of we we need to see how to bring them together into one component yeah so basically think of this as a timet tabling system you have a virtualized timet tabling system.


Your NDT agent gets all the requests that need to be configured it will then push it to it will check like all different scenarios.


Like if I organize AB or BA or BC So it will run all those simulations in the NDT get results on each of those scenarios, return an optimized schedule to maybe the network agent and the network agent then configures.


So now you've got an NT agent that is subsuming some of the functionality that is there in us our uh conceptually envisaged schedul agent and some of the functionality that is there in our currently implemented network agent so now there are the NDT agent is doing pieces of these two is this NDity agent something you wrote haven't written yet I want to start writing so that's why I'm uh trying to figure out how to do the virtual box thing with you guys so the NDT agent primary goal is to simulate all different scenarios in the virtual box inside. And return the results to the network agent the network agent can then make intelligent decisions that okay I'm not going to take scenario we can return back three different scenarios, giving an a score of one, two, three and then the network agent can make a decision that I'm going to take score of three, for example.


Why there for the different scenario?


Because network agent already decide which he piled to choose and the out for yeah, so that's where the NT agent becomes an intermediate, the network agent will talk to the ndt . The NDP emulates the DUE network. If you say your NDT agent is not directly talking to the NDT.


It's only talking to the network agent.


Am I right?'s supposed to be talking directly to the NDT but we can make we can see where you're going with this we have let's think about.


We have three components. Let me try and a diagram well. There are three components.


One is a sched that takes all these different requests with their constraints in terms of what they want to do for their experiment with a computer resources experiment resources and network resources.


Let's only focus on the network resources so there are multiple experiment requests that come to the scheduler.


The scheduler says I've got this experiment request that requires this bandwidth from .8 to B and for this time another experiment requires point C to D using some common links that A to be also might have used.


We don't know and it over a certain time.


So that comes to the scheduler.


The schedular then says okay now for this uh transfer from A to B requiring this bandwidth at this time interval, we talked to the network agent and the network agent looks at all the resources in the topology by having collected from the network or the network digital twin what the topology is and what the capacity are and from the telemetry agent knows how much available bandwidth is in the hops and then says OK here are the options for experiment one here's the options for experiment two and so on and in the sched prioritzes and decides, okay, this is what I want for experiment one and then comes back and tells the network agent commit these resources, the network agent then goes off and tells the network or the network digital twin this is what I want you to commit on these links now I was thinking if you have an agent that is in front of the network digital twin that would take these commands from the network agent and translate it and not provide any other additional intelligence for decision making, but translate it and hand it to the network. Now if you're thinking, you have an agent that is doing more then possibly what we could think about is the functionality that you're thinking about in your agent.


I'm going to call it Miriam's agent rather than that Nity agent and I'm thinking that Miriam's agent can serve the functionality of the scheduler so that Miriam's agent can essentially become the scheduling agent and then the network agent is doing all the things that your envisaging of understanding the topology and then figuring out how much bandwidth is going to be used on which links for this experiment and talk to Miriam's agent and say these are the options that are available you choose which one you want.


OK so the depology is so who makes the running of all the scenarios?


So the depology is held in the network digitalital twin, right?


So the topology that is known in the network or the network digital twin is made available in some kind of a file that the network agent can use to make all its understanding of .8 to be uses this sequence of links and then the network agent talks to the telemetry agent and says hey tell me for this this these links how much available capacity is there right now tell me what the utilizations are so I can figure out how much available capacity there is yeah so this should be inside the network digitalin.


So the whole point of you using the network digital twin is emulating the network.


It is not emulating teletry.


If it is, then you know what we need it is it is doing all the teletory work as well.


It is so the reason why we decided to go with this particular virtual infrastructure twin was because it's emulating real DE infrastructure data so it actually transferring or emulating the transfer of packets I don't know if it calls and like latest data, but it's been built on historical data sets of real DV network..


So it has a apology, okay?


It has a topology of the network and then it knows how it behaves like it knows that the Chicago to Oak Rid Link is like 50 gig versus some other link is 10 gig. Yeah good so it knows the capacity of those links it knows behavior is it run?


What package we send on it.


So if we run a bunch of experiments which use a link and send 80 gigabits on a 100 gigit link then OK there you know it can say this is my utilization of .8.


I see little or no loss.


Maybe there is a small percentage loss that I see.


This is the kind of delay I see and that the network digital twin, just like the network would make available to some entity like Prometheus to help give to the telemetary agent that this is the current utilization, the current loss characteristic, this the current delay on each of these links I see what you want to do in Miriam's agent is more like some scheduling activity . The way you are saying it though is you're saying the Nity agent does everything We've split it out as schedular a network agent and a telemetry agent and if we build these components as modular, that helps us evolve each one of them to add functionality to deal with failures, to deal with uh unknown or unanticipated events, keep track of information on an ongoing basis with whatever teletry we do, we can have the telemetry agent track in terms of averaging information in the way that is desired by the network agent and we can go through this reserve and then commit process. And go back and tell the scheduler okay you asked me to reserve and you asked me to commit now I've committed and I'll keep letting you know if what you expected for this transfer is being met or violated at any point in time after deployment agent can do all the scheduling work very nicely.


I think that's what your you seem to be focusing on the scheduling of competing requests yeah OK yeah I wanted to test each of those competing requests and the simulation at the simulation then returns like how to organize those competing requests we were saying would basically do the static estimation rather than similate the all the all those data transfers but if there's a need to simulate the data transfers before we come back and say okay these are water feasible then we can have an entity between our network agent and the network or the network digital twin that then says for each of the data transfers that the network agent is asking for let me go and check the feasibility of it yeah right but my my expectation was that the network agent is keeping all this ledger of resource use and we will thinking about this especially in the context of something like ESnet which is all based on virtual circuits rather than a pure packet environment that this is still virtual circuit virtual circuits.


So given that those are virtual circuits with a reservation we thought that there is no need to go through wholesale simulation effort to figure out if these three different flows that generate this kind of bursty traffic on a link whether they will cause delays to build because of queuing or packet loss that will result in our violating the SLA.


We thought that we could do this based on pure capacity estimation and to in delay estimates to make sure that we meet the SLAs but not actually simate the traffic but uh so this works if you have a ledger system kind of works if you are committing what what happens now you request for services and you get that.


But for some flows that are just in time, they are just entering the network.


So you need to fit them somewhere So you want them to trans B used use the apology to determine how to route these on demand flows. . So there's no reservations for them.


Yeah, they have there is no reservation in advance in the ledger.


You can now add them to the ledger, but they want to run now. Network agent is tracking in the ledger what the current utilization of the different links are.


So if we have an on demand flow as long as Miriam's agent tells us hey look for this on demand flow I'm going from point X to Y and I need a minimum capacity of and with so then the network agent can check on the in the ledger a feasible path to go from point X to Y with that bandwidth requirement of at least end bits a second right once we have that then we can update the ledger and keep that to say this on demand flow is also being provided this end bits per second bandwidth and therefore subsequent request from Miriam's agent will have to factor in the remaining bandwidth only four reservations. And then we can talk about priority after that yeah.


So I am seeing that if if the VIT as a network digital twin has some ideyncrasies, what we need is some interface from the network agent to talk with this VIT and its serious syncrasies less dumb it's just only doing API translation from what the network agent wants to what the VIT wants API translation only that I think these guys call it a simple adapter it's not doing any intelligence no decision making just funneling a request from the network agent that uses a particular API maybe sense to the API that VIT understands yeah so okay I'm hoping that that'll be a simple adapter but Miriam's agent can be a more elaborate scheduler agent yeah I have a question here The network digital that we have isn't supposed to represent just the network dropology or uh in real time, whatever the traffic is actually happening as of now on the ES net, is it supposed to represent that traffic also ? What traffic on ESnet meaning what is going on in ESnet today?


No, so it doesn't actually.


So the network digital twin I think doesn't get real time data, but it just draws like uh they've done a uh I might need to read go over the but basically, so these files they had represent uh uh experiments of those experiments they see the thing that they did before that VIT was they just took the experiment and figure out what the transfers are and just shoved it on VIT and long as those transfers.


They didn't have anything to sort of do the mediation.


What we are saying is that we've got two components scheduling agent and the network network agent link has built to talk to VIT and un underneath linksuance network agent I at one point we were thinking the schedule we talked to the teletary agent but we don't now we're just primarily having the network agent talk to the telemitary agent the telemetary agent talks to VIT and collects essentially what Promitas would have collected from a real network. There are two things here.


The telementary agent can do uh SNMP calls as flow calls and get what is happening now so we could put that uh like, say this return to topology to the network agent, the network agent then talks to the elementary agent elementary agent says, okay, this is what the scenario looks like now.


And then the network agent can then superimpose that data and then make decisions. Capac and then he is superimposes what comes from the agent to get the residual available capacity to accommodate additional requests that's good.


So given this discussion, I'm also double thinking that the way we're using the network digital twin, if we strip down everything, we're going down the miniut route, right?


So we could guard based on my dumb knowledge of mini net, but um I have not perceived any significant additional things that are there in VIT that will help us if we have Miriam schedule agent and network agent and elementary agent so that would be one question I will ask uh a niece and Nagi, like if we strip down everything we could basically just have a mini net uh here emulating the DUE topology.


We take that extra information you batted in BIT and we could yeah and that's why I was hoping. . Yeah.


And I'm still hoping although I do not know what's going on, but HPE who has the person whose created min net has supported minette for God knows how long 15 years sharp he's notita has not put it put him on the team I want us all to take off our shoes and pound the shoe on the table to make Bonit assign him at least to help us.


So the one thing that I have talked with Bob Lance about how to scale mini neck, how to make sure that what it does is all represented in our real time for us to keep track of everything that goes on in ourheduler and network aging. And he said, hey, if I can dedicate a weekend, I should be able to get it done so I don't want him to spend his weekend but if he spends a week, that should be enough and we don't need a lot of people just busily attending meetings instead have somebody to some real work today's meeting is good.


We're going into the nitegrities of these things so I think so one thing is I will take this question to Nagi and Anice saying that we figured out that we need an adopter agent between our agents and your VIT.


So how do we do that Since VIT runs in a virtual machine, we can strip everything and go down to the mini net level because we can also redo this as as a python simulation, right?


To make our make our work easy, we can just replace this whole thing with the python simulation.


It'll take time though.


Who'll do it?


That's very easy.


You use graphic you create aology. You superimpose the bandwidth values So I need to they they' fed all that, what you say in terms of the graph of the topology and the network bandwidth, and you give it meaning it that would be so easy it will do everything.


It's just that we need to make sure that it is able to emulate higher bandwth links than what it currently does. So that's the okay so I know which question I should ask them for this part.


So okay so we do have a dumb adaptor agent in the middle.


That's correct goes along with the sched admission control component figure out what is happening between all of that and then this calls this yeah calls the network Miriam station calls the network agent.


And then who calls the NDT adapter agent?


The network.


And then are you guys in agreement?


This may change as we develop, but this is the current because I don't want I shouldn't.


I'm actually get crashing this meeting you this was supposed to be your meeting with these two guys.


I should've shut up just one one more thing just to get more clarity the teletry agent is um is interacting either with um the real network when we deploy it in later on.


But as of now the only thing it does is it fetches the metrics from the digital twin and then it gives it to the network agent and network agent will update its lecture.


OK OK then it makes sense yeah we should have that line to go between the telemetry and the network agent and the current Prometheus APS which um uh John shared yesterday we need some way to uh emulate them also from the network digital Twin or because then uh if the limit agent, if we have that polling those Prometheus APIs, we need the network digit can also be expose those AI so that it can use it and provide those metrics to the network agent but you know is VIT, whatever it is, if they don't have it, we do what we can and then as they add more of that capability, we can utilize it. We can add more agents also.


Yeah.


So yeah, this is uh, yeah, the the challenge we have like what I'm struggling with in our weekly meetings is there is a lot of ideas being discussed, but um less on actual work happening.


So I I sympathize with you on that and and I'm glad you're taking this sort of thing to say let's actually do some real work um it's a good idea because otherwise we'll run out of time and then afterwards we stand in front of the whatever person and say blah blah I don't have and so okay so this is good.


So, okay so based on this, I have some questions to take to the VIT folks which I'll try to get answers today.


And then I will go over so I think from your guys point of view, you continue developing as you guys are developing. And I'll start filling in like different agents in the middle to see how things are going if we have not spent energy on the schedul part it's not that we refuse to do it, but we' not sp spend the time because we've got these two guys working on network and teletary.


Yeah.


I'll with scenarios if you are planning on building an agent, see if you can roll Miriam's and schedule together.


So the adapter agent, could you help with seeing how an adopter agent would work like how a vitin script is going to call code inside a v machine and return results?


I could look into that.


So the adapter part so we can check that and then I'll add you to the scheduler and our agent so we can start working on that yeah.


Okay.


So in all of this, this is still not doing um so this is all still event triggered um, which is is it the correct way of using LLM Are we like using the power of LLM's correctly with this scenario ? I can't answer that yet ifan is able to answer it yes, but I think we are in the discovery process of how we ought to be using aanche, but answer that if you can in what your understanding is link shown in . Yeah, for Carly and planning to implement the round high stage of Little work Agypt.


That means Little Rock agent we all found the problems and detect the the problem in the network and uh gave the solutions and the f fixed.


So here I thinkodang model is if needed, like network agent will uh gives the caral scenario, current information to nar model and the largeang model provides to provide the solutions.


And I think even diagnosis, right?


So firstance that you provide the current state and maybe even the history from the network agent to an LLM that then comes up with an inference of this is likely to be the issue but I think better way is let AI let the larger model control the the computer and the and the input while the information the wound, but not modify the file. We'll see. We will see. By just to impose a the information and the current information current state and the history information to to AI and the AI returns the solutions.


Currently we can with like this.


Yeah.


So maybe so the agents would discover something on their own kind of thing if we let them control it.


Okay. Schedule networks and compute resources.


Okay.


Sounds good.


Okay.


So with this, we also have a workflow agent in the beginning.


Sorry, I think we've gone over a which is submitting the requests to go Yeah.


Okay.


Yeah.


Okay.


So I have two questions that are nothing to do with all this.


Number one is in terms of demo at supercomputing, what will you need from these guys?


So I still need to yeah the demo is like one week away now.


So we have two weeks yeah so we have to show something running so I'll look at all the what we have so far and start to stitch a story together. Um so maybe it'll just be part of this uh like maybe we just showed this part talking to this part then talks to this part um kind of thing so we just show half of it um and it's like work and progress.


We show like and I will double check with the gateways that's saying that oh see we were already achieved gateway one or two based on what we're showing today and you know, uh show a little demo with a mark network and a mock uh work floor request So that part we can do.


Maybe if if there is I don't know how much of Miriam's agent can be done in between, but if if we want to just show stand alone sort of stand alone, the network agent, the way that anon was walking through his little demo yesterday that I don't know how satisfactory that demo would be to show at supercomputing, but we could set that up somewhat easily for you to show.


I think we should show some adaptaptation with the network digital twin. Um so me and Aaron will try to see how we can get that working that piece and then we stitch things together.


So we can we can show the we can do the demo in the sense that, you know, we have a list of a page that one we will show a network agent demo, second we will show network digital twin interfacing third um and then we basically just run through that that's that thing.


So I will have you done a C demos before?


I've never been to a C.


Well, I have been once in 1999 or 2000. Okay. Just graduating school at a time.


So, um okay, so as see demos, I've done them a few. Uh basically you just show an overall picture of the project and then from the project, uh sub like a one, we will show this, second we will show this.


And then you basically show one and two, and that's it.


And then you get feedback from the people.


So it's like five slides, then you show the code and then that's it. . So we should get at least the virtual infrastructure twin working because if they really wanted us to show that we'll um try to get that piece working and then we stitch things together, switch a story based on what we have.


So we don't have to show this whole thing working just half one and two is fine.


Um, but basically we have to say that we have achieved gate one gate to those kind of things.


S care about what we's what they are like I did a update for the project yesterday to my management.


They said that you should say that you've achieved gate one gate two and you're on track because they are still expecting you to deliver by the call that comes out in January. That all the yeah she'll be there at S so I'll send her our schedule that this is the time will be presenting so she'll come and see it yeah okay okay.


So okay, so that's for a C and you had a second question?


So what with HPE What is the like they haven't I think they're contract is still being negotiated because they are supposed to bring shared costs if you remember that at the time we submitted the proposal, they said that they will be bringing like if they went down to 150, they will put 150 from their own.


So that part they are putting in as uh ours.


People are working.


So that is being negotiated.


They submitted something and they have to resubmit that cost check So I think they if they have somebody help us with mini net, that's a big value for us. Yeah, and I don't think they added hardware, like what Harvey was saying because I went over their documentuments.


They've added a lot of software that will provide access to the software, this monitoring system and data, but no hardware is actually listed in any of the documents . But we have so much hardware coming out of I don't.


We just need a agentic framework delivered for this project.


I mean, hardware is only sort of to collect goodies.


I mean, No, we just need to deliver the I think what is happening is uh adding so many people, everybody has their own personal agendas um but we have to make sure that we're delivering the project that we need to deliver.


I like lots of hardware that I cannot blackmail these guys to give me hardware to the agentic frame harness and maybe they could start working on those pieces.


So uh I'm hoping that once we set this up for them, we can then say, okay, you guys need to, um, so I'll go to the gun chart and say, okay, we've assigned this task to you.


Go ahead and start building.


Okay, okay.


All right. . But, yeah, I just so one thing I I will bring this up, okay, okay, because yesterday we had our feedback to the management and I sent the feedback we had from a management to Raphael uh so this is the current status.


We're actually very behind.


Um so some teams are hegged uh or everybody's saying, oh, we've already done a lot of work.


So I was like, okay, I don't understand how you've done a lot of work when everything just came through. Um so everybody's saying they've already achieved first gate metrics, uh people are already using resources on AMSEC, Lu, pathfinder.


So these are all the machines, which I was showing you guys. Uh We haven't requested any computer resources, so that's one thing.


So we should say that we are using these resources because it's supposed to be like, oh c . Um, there is two people have already started talking to people to make teams.


We haven't started this yet, so we need to start looking into this.


So I'll look at the award list and connect with you guys. Um I also suggested strategic to add Google or Nvidium for phase two because, um it might help us getting phase two because there's going to be a lot of thoughts uh over there.


So our project uh tackles IRI so like API is talking to different infrastructures um we currently are not having any of those folks in here so we need to form a team with them um so for example, ESNnet needs to be on our team for phase two.


So we need to see how we can get that done.


Some of the projects award for themselves No one to go and have a write a face proposal along with Arpet Gupta and Scotchankur and so on . Oh, so I know they submitted a face one with Arpet Gupta and a that was rejected.


I see.


So, so he's trying to put together a very strong team then with Scotthenker and stuff.


That was my impression, but he's that that was he was going to do the first round of face two rather than the December round of face two.


So phase two projects just got announced.


Oh, and he didn't get?


I didn't see any uh any news from ESnet.


So, okay.


So I'll double check that.


So six six space two came to Oreage.


That's why I know.


Oh, okay.


I I this feedback that you got is sobering and so and I have to there is so some teams are already presenting robots because they have that as part of their demos, so they are showing simulations running showing robots being controlled. Um so that that worried me.


And then there are some teams uh, who are also in contact with Dario Gill.


So they are uh talking to local companies like TBA and creating highlights and sending them up to Dario Gill.


So we are very behind it with with all of those.


So I don't know.


I'm gonna uh, I sent this to Rafael that we really need to punch up like how we are delivering this. Um I guys are running as fast as we can.


Nay, I I know you guys are doing so much so thank you so much for all the work.


I think we just need to be creative with ideas like do something that none of the other teams are doing so um okay okay let's go a little bit further then maybe we should talk about uh next week or something building the sched agent ary M's agent.


Yeah, so I'll work on the network digital twin our team will work on the adopter agent and see how that will work and we'll start combing through this picture and seeing how things will be assigned.


And it's okay if you guys put something here that we multiple agents could be doing multiple things.


So even if Mariam's agent and network agent are similar, it's fine.


We'll just separate them out later.


Okay.


So purposes of today's meeting, we got this to work.


I think we yeah, so we got this to work and we'll figure out how this works so um we'll communicate over email once we know what our next holdups are.


Okay, thanks guys.


Yeah.


Go ahead.


Uh, no, uh, just for Mariam.


Do you want the initial commands to start the transfer like I have such a like a small documentation on how you can run this VI inside this VM.


Yes, yes.


Okay.


I can share that.


Yeah.


Okay.


So and uh so I don't just join so I'll bring him up to speed so I think yeah we we' start testing ourselves . Took it down.


Okay, guys.


All right.


Okay.


Thank you.


Bye, bye, bye.


I's you for today.


Bye.


Bye. 




Was this transcription useful or not useful?
```

</details>
