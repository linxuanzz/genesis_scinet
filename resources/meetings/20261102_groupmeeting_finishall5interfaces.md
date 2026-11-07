# 2026-11-02 大组会：SciNet 研究贡献与 Network Agent 五类接口进展

> **日期与范围**：2026-11-02。仅记录本次大组会中与 SciNet 有关的讨论，其他项目、论文和实习等话题不收录。
>
> **材料与可靠性**：用户提供的英文自动转录，无时间戳及 speaker labels，存在术语、人名和句子误识别。按上下文将主要发言整理为 KK、Linxuan 和负责 Telemetry Agent 的 SB；这不是完整参会名单，发言归属未经回听确认。实现进度记为会上报告，不等同于本次已审计代码或复跑验证。
>
> **相关背景**：[10 月 27 日 SciNet 会议](20261027_scinet_network_telemetry.md)、[10 月 23 日 Telemetry Agent 职责讨论](20261023_withkksb_telemetryagent.md)。附录 B 只摘录本次转录中 SciNet 讨论对应的连续片段，不附整场大组会原文。

## 核心摘要

Linxuan 报告，Network Agent 在此前 quote 的基础上补充了 **reserve、commit、modify、release**，当前五类消息/操作已具备实现。会上展示了简单拓扑中的候选响应与 reserve 后账本状态变化；KK 没有要求继续逐一演示其余操作，因此不据本场转录判断所有分支都已现场展示或验证。

研究贡献讨论集中于：**多 workflow 竞争共享网络资源时，agent-mediated negotiation 如何优于既有资源管理和规则系统，以及 LLM 在哪里能提供具体帮助。** KK 认为目前尚未走到展示这类 novelty 的阶段，并不要求现在就证明；近期先把模块做扎实，再用具体多工作流、诊断或人机协作案例收敛贡献。

Network / Telemetry 的分工再次明确：**Network Agent 做资源预留与账本核算，Telemetry Agent 测量并保存实际观测，不扣减容量。** 按链路、按时间段的容量信息与端到端诊断测量需要区别处理，两位开发者应直接对齐当前假设、API 与实现顺序。

近期安排是准备次日 SciNet 讨论，补足可共享的整体 slides；接下来两三周希望形成有意义的 workflow 或 twin 对接。若 twin 侧无法及时提供可用接口，KK 提出也可以考虑与 NRP 的实际环境对接，但本次没有正式改换研究方向。

## 一 研究问题：不能只把“新场景”当作论文贡献

### 多 workflow 共享网络资源

Linxuan 以科学 workflow / research-agent 系统作对照：一些系统将网络视为已经可用的传输条件，而 SciNet 要显式处理容量、请求协商和预留。讨论提到 Academy 等工作；对其实际覆盖范围和网络假设，本次没有做文献核对，因此这里只记录比较思路，不作为已确立的 related-work 结论。

KK 认可这是一个 gap，但指出，**仅说明存在这一场景，还不足以说服 networking / systems 读者**。需要具体说明：

- 多个 workflow agents 如何竞争共享网络资源。
- Network Agent 作为中间层承担什么资源管理功能。
- 这与传统 network management、operational support systems 或 SDN control 的处理方式有什么区别。
- Agent-based 方式为什么能把这件事做得更好。

讨论也提及动态创建 networking agents，以及它们如何管理网络、相互通信，作为值得进一步研究的方向；本次未选定具体机制或评测场景。

### 规则基础与 LLM 的增量作用

当前底层首先是规则系统，例如集中接收网络请求，并确保总需求不超过容量。Linxuan 提出 LLM agent 可能进一步改变或生成规则。

KK 表示，现阶段尚未展示这项能力，但这并不令人失望：需要先把多个 workflows、实际 workload 和协商过程放到一起，才能具体看 LLM 如何帮助调整规则，进而找到 novelty。**“LLM 可改规则”目前是研究设想，不是已经完成的实验结论。**

## 二 LLM 候选作用与贡献仍需落到具体例子

Linxuan 希望从几个角度组织未来论文，讨论涉及以下内容；各角度之间仍有重叠，本次没有定稿论文提纲。

### 2.1 诊断：选择工具、定位原因

有参会者提出，当 workflow 表现不符合预期时，agent 可以选择诊断工具、调查应检查什么。KK 认为这是可能有价值的方向，同时提醒网络管理行业已经在做相关诊断，仍需寻找有意思的具体案例，而不是仅靠“使用 LLM 诊断”来声称新颖性。

会上建议参考一篇有关 cellular failure management 的会议论文。会议名转写接近 MobiCom，题名转写为 `default` 等，作者和准确题名均不清楚；**应核对原始出处后再引用，本文不指认为已确认的某篇论文。** 该论文只作为 SciNet 诊断思路的参考，不在本记录展开蜂窝网络研究。

### 2.2 人机协作：怎样减少人的排查与决策负担

Linxuan 设想，agent 不能自行解决问题时请人介入，并将处理结果转化为以后可复用的规则。KK 追问：**agent 具体怎样帮助人，而不仅是把问题转交给人？**

讨论的一个可用方向是缩小候选原因或方案集合，让人只需在少量合理选项中判断。KK 以过去 AI planning 的工作作类比：先搜索、剪枝，再把少量候选交给规则或用户决定；同时指出那个既有工作本身并未完成闭环。

有参会者提出，可在同一具体情景中比较人独立处理、agent 处理以及人机协作需要的步骤。本次没有制定实验或评价指标，只提出应以可观察的帮助来描述贡献。

### 2.3 输入规范化与缺失上下文推断

Linxuan 展示或提及此前整理的 LLM 作用位置，包括从邮件、对话等输入生成规范格式，以及补全或推断缺失上下文。

KK 将输入规范化进一步具体化：科学家可能只会用其领域语言表达正在做的实验，系统需要通过多轮交互，把这些表达转成可用的标准输入。Linxuan 希望用这些难以仅靠固定规则处理的环节解释为何需要 agents。

KK 请 Linxuan 再发一次该整理材料的链接，供之后阅读；本次转录未包含链接，也未讨论完整功能清单。

### 2.4 接口形式化

讨论认为，workflow、scheduling、network，以及 Network Agent 与 SENSE / twin 之间的接口需要进一步形式化。Linxuan 提到 WfFormat 等已有方向；KK 强调 Scheduling Agent 与 Network Agent，以及 Network Agent 与 SENSE API 的明确接口也有价值。

这些可以共同构成系统工作的一部分，但本次没有将某个接口本身宣布为充分的独立论文贡献。

### 2.5 新规则的验证、适用范围与冲突

Linxuan 提出，LLM 生成的新规则可先经 digital twin 验证，再转为后续可执行规则；还需考虑规则适用范围、过期条件，以及多条规则之间的交互和不一致。

KK 追问如何处理相互冲突的规则，并建议选一个具体例子，演示 agents 怎样交互、形成理解或规则，再看怎样验证。**本次没有确定规则冲突算法，也没有证明 twin 已能完成相应验证。**

KK 的近期要求是先把正在做的模块完成、做好；更具体的 novelty 通过后续案例逐步找出。

## 三 本周 Network Agent：五类操作的实现进展

### 3.1 报告的完成范围

| 操作 | 会上报告的进度 | 本场可确认的展示范围 |
| --- | --- | --- |
| Quote | 前一周已有 | 再次展示请求与多个候选响应 |
| Reserve | 本周补充 | 展示 reserve 请求、带过期时间的响应及账本变化 |
| Commit | 本周补充 | 被列入已实现操作，未继续逐项演示 |
| Modify | 本周补充 | 被列入已实现操作，未继续逐项演示 |
| Release | 本周补充 | 被列入已实现操作，未继续逐项演示 |

这里的五类接口是 **Scheduling Agent ↔ Network Agent 的五类消息/操作**，不能理解为五套彼此独立的 REST 服务或整个系统全部外部接口已完成。

Linxuan 也提到 Network Agent 与 SENSE、telemetry 的接口，但当前讨论仍以简化实现及可继续完善为前提。本次没有审计真实外部系统的接入状态。

### 3.2 Demo 中的内容

Demo 使用带有 background traffic 的简化拓扑，以两次 transfer 请求展示多个候选安排，再发出 reserve 请求，显示过期时间与容量账本的变化。

转录中的节点名称、单位和部分时刻不稳定，本文不把演示数字登记为定量结论。KK 在理解新增接口的进度后表示不必继续展开，转而讨论次日汇报。

## 四 术语反馈：Quote、request、response 还需统一

KK 对 `quote` 作为请求动作的用法提出疑问：在常见商业语言里，quote 往往是提供方给出的报价，容易与请求/响应方向混淆。如果不是沿用已存在的协议术语，可以考虑用更直接的 request / response。

随后又发现，简单把第一类操作改名为 `request` 也不够，因为 reserve、modify 等同样都是 scheduler 发给 network 的 requests。需要区分**通用消息方向**与**具体 request type / operation**。

另一位参会者提到一个有 request / offer 等交互的配置协议，可作术语参考；从“dynamic configuration”上下文看疑似 DHCP，但协议名转写不清，不据此恢复完整状态机。

**本次没有敲定重命名，也没有要求立即修改 schema 或代码。** 记录的是表达上的歧义及统一术语的需要。

## 五 Telemetry 与 Network 的职责及实现顺序

### 5.1 实际观测与资源核算分开

SB 说明，Telemetry Agent 保存链路上的实际测量信息，与 Network Agent 的 ledger 不同：telemetry 自身不因收到预留请求而扣减容量。

KK 认可这一分工：

- **Telemetry Agent**：测量链路容量、利用率等实际状态，并保存观测。
- **Network Agent**：维护预留与承诺的账本，用观测和已有资源占用判断新请求能获得什么。

Telemetry 内部保存数据，不意味着它要重复维护 Network Agent 的资源会计。

### 5.2 链路容量推导与端到端诊断测量需分别对齐

SB 问，应先只实现链路容量查询、完成整合，还是现在就加入端到端统计，以便 Network Agent 在 transfer 进度不足时进行诊断。

讨论提到，Telemetry Agent 可提供 API，并执行相应命令获取端到端 RTT 等统计；但哪些具体指标现在需要、调用由谁触发，必须与 Network Agent 的运行期需求协调。

对于当前展示的**按链路、按 time slot 查询可用带宽，再判断路径可支持多少带宽**的流程，KK 让 Linxuan 说明现有处理方式，并将这部分资源判断留在 Network Agent。

这不应被扩大解释为所有端到端指标都可以由链路数据直接相加。容量上的路径推导，与 RTT、完成时间或实际传输表现等端到端测量，是不同需求。

### 5.3 当前行动是开发者直接对齐

KK 要求两人直接讨论：Network Agent 当前假设 telemetry 提供什么，Telemetry Agent 实际能做什么，哪些处理放在哪一边更合理。

**本次没有决定“只做链路容量即可”，也没有要求立即实现所有端到端统计。** 两人需要形成适合当前阶段的分工，并为次日讨论准备可汇报的内容。

## 六 次日汇报、slides 与后续集成

### 6.1 次日 SciNet 讨论与共享 slides

按会议日期，“明天”为 **2026-11-03（周二）**。Linxuan 问是否展示本周代码和示例，KK 表示可以；相关句子不足以恢复具体发言时长或完整出场顺序。

KK 还提到，Harvey 之前希望把上周展示的内容整理成 slides，放到共享 Google Slides 上。需要形成一份整体连贯的介绍，而不仅是临场代码 walkthrough。KK 表示这项整理不算立即紧急，但应在近期完成。

### 6.2 两三周内形成有意义的外部对接

KK 希望在接下来两三周内，workflow 侧或 twin 侧能提供有意义的对接对象，让本组 agents 真正完成有用的事情，例如 workflow 使用 Scheduling Agent，或 twin 与 Network Agent 联动。

KK 对部分合作方的实现进度表达了担忧，希望进一步了解对方已有代码和后续计划。这是会上个人判断，**不等于本次已经审计对方代码，也不将其对其他人投入程度的评价当作客观结论**。

若 twin 侧无法及时接起来，KK 提出也可以考虑直接与 NRP 的真实环境合作；这是备选方向，本次未作正式切换决定。

KK 强调继续做好本组可控的工作、形成能支持 Phase 2 的可信进展，同时与合作方沟通时避免营造指责其他人没有工作的气氛。会上关于项目数量或竞争情况的口头说法未核对，本文不列为项目事实。

## 七 行动项与待决问题

| 事项 | 负责人 / 状态 | 边界 |
| --- | --- | --- |
| 再发送 LLM 作用位置 / 贡献思考的材料链接 | Linxuan；KK 请求之后阅读 | 转录未提供具体链接 |
| 为次日 SciNet 讨论准备本周新增接口和示例 | Linxuan | 2026-11-03；本次未确定具体展示时长 |
| 对齐容量查询、端到端测量和诊断 API 的职责与实施顺序 | Linxuan、SB | 先说清双方假设，不预设全部处理都放在某一边 |
| 将前次展示整理成可共享、整体连贯的 slides | 相关展示者；KK 转述 Harvey 的请求 | 近期完成，会上未给硬截止日 |
| 推进 workflow / twin 与本组 agents 的实际对接 | 本组与合作方共同协调 | 希望两三周内有意义的对接，不视为外部团队已承诺交付 |
| 用具体场景收敛 LLM、规则协商、诊断或人机协作的贡献 | 后续共同研究 | 先完成现有模块；本次不启动新实验、不确定最终论文主张 |

待决事项包括：五类操作的统一命名；运行期实际需要哪些 telemetry 观测；多 workflow 协商的最小验证案例；新规则的适用性与冲突验证方式；workflow / twin 的具体对接接口和责任人。

## 附录 A 转写存疑点

| 原转写 / 讨论项 | 整理口径 |
| --- | --- |
| `legend based systems`、`large angry model` 等 | 按研究讨论语境分别理解为 agent-based systems、large language model |
| `Academy` 等研究系统比较 | 记录为会上理解，未做原论文覆盖范围审计 |
| `Moby farm`、`default` 等论文线索 | 疑似会议名和题名；准确出处未确认，不补全作者或链接 |
| `code`、`court` 等 | 请求报价语境整理为 quote；真正代码语境仍按 code 理解 |
| `Russian sal`、`later` 等 | 按上下文整理为 reservation、ledger，不恢复精确响应字段 |
| 配置协议名 `DHT/DC` 等 | 疑似 DHCP；只保留类比建议，不强行恢复协议过程 |
| `VIT/VID/VRT` 等 | 疑似 virtual infrastructure twin 的相关称呼，本文统一以 twin / digital twin 指代，不确认正式组件名 |
| 人名、邮件收件人、精确 demo 数字 | 不清楚处不补全；实现状态和沟通情况均仅记录会上报告 |

## 附录 B SciNet 讨论对应的原始转录片段

<details>
<summary>展开 SciNet 原始转录片段（不包含其他项目和话题）</summary>

从讨论 agent-based networking systems 的研究价值开始，到转入另一篇 load-balancing 论文之前结束。片段内原文不修改，含该讨论中的语音识别残缺与临时问答；不附整场录音转录。

<!-- BEGIN SCINET TRANSCRIPT -->
I I think this whole legend based systems and networking agents dynamically created , uh and how they manage networks, how they communicate among stages, um that are dynamically created that that can be an interesting area and you in case of that. Was thinking about this is novel these things.


I' these days, I'm thinking about the lab things, the contribution novelty and I think we can write a paper from four perspectives the first is is workflow is work flow.


Yeah, I think it's it's sal is a point because for the smoke, yeah, but networking or a systems guy he you're not going to make him feel ha.


That's a really good thing.


Because for the research agents, Satanize like a kad, they didn't you guys?


You so okay, I mean get used to how you speak I'm trying very hard but I mean, the research aiding assistance site, like the academy, of the paper, and they didn't care about the network.


They jail consider network as a a a currency, yet yes.


So what they do it those guys, right?


Theemy from Chicago, right?


So there all hypper performance computing people.


This is network is there.


They don't pay attention to that so much.


Yeah.


So they that's right.


So they just so they just, when the data generate , they will use the net network to transfer it, while for scienceate, we use quote we use a quote something negoti.


Yes. For the domining whether the resources.


Yes, two capes the high performance, capes the reservation. Is that there are many competing work that have to share that resource. Is just assumed, I' just one exclusive user of uh whatever resource I need, and I'll just figure out how tow my experiment.


Yeah.


So for our new scenario, it's the gap, right?


It's not aop. Is a gap, but we have to convince networking people how this problem space that we have that are now looking to see how to have multiple workflow agents.


This network agent is an intermediary, is now serving a useful function of doing dissource management.


That is different than what we would do with network management, operational support systems , even as the end control, don't provide thatly system, right?


So, how this engine based system helps us to do that resource management better ? So this thing.


I sign opinion is that uh the bottom is a rule-based system.


It's rural, and theian mother and the people and a yet what role that large language model can play and help going beyond just roomate systems.


So the rules here is like we are saying we've got a central engine, which is the natural networkase.


Every request for network network resources comes through that networkas.


The rule is, the total demand does not ex the . I think the diff the biggest difference between the larger and model based system and the rural based system is agent, larger angry model based agent can change the rule can create the rule.


So for that I feel like at the level at the point where we are we' not been able to demonstrate it.


But it is not expected at this point, right?


We have to actually take multiple work floors and understand the workload and then look at the negotiation that happens and then see how the large language module will help in changing the food.


We've got to come to that point.


I am not at all feeling bad about not being at that point yet, because we have walking towards this point.


Once we get there, then we can say here, this is where the nugget of novelies.


Yes.


Right?


We're not there yet.. Place where I think can actually use is in the diagnosis.


So in case a particular workflow is not the thing, then what tool to use and what to actually.


Here I think don't need to have about those.


I network management diagnosis people do and it is industry does quite a bit of it.


How much papers write about it?


I don't know.


It's very much like you are diagnosing attacks to these otherments to say, hey, this is what. Might be the root cause of this secrets.


And then it will check and something they do, but uh airport management as well.


We may not see many papers, but we can be some of the ugly people, too, provide that contribution as a paper.


Both in terms of loan negotiation for resource management and for diagnostics.


U there was a paper in Moby farm that J had about understanding failure, uh issues in segregating the land.


Have you uh looked at the paper swing Maybe he can't hear it or maybe he cannot speak.


Uh, I think there's some issue on my side.


Can you use your on my phone?


Um, that just reading fairly or you know, we can hear you now.


Oh, have you looked at the dy paper, Jar paper from audio?


Some default.


It's called default.


My voice is soeaky car is.


If you're not looked at your newsp, just take a look, but that that might be one which looks at failure management in cellular land. ? Oh, I'mding. Just words.


Oh, don't repeat words so that somebody else says, because then that sounds like dish one.


I don't know if you heard you about this., it's he'dding.


Oh, somebody's shedding.


Yeah.


So, but but I agree that if we can actually find some interesting cases, for for detection, that would be good.


Oh, you that this year's paper.


Yeah, you went to this conference rate, but I don't know, you might have access to the proceedings, right?


But anyway, it's open access. Was to see it..


But go on, that was second thing you.


You you have two more things, right?


Yeah, the single thing is is the most important. Finally, it will become like the rope is 15 will because the problem and we will ask.


We will ask the agent an agent will handle the problem if if it you father the problem.


If he can't, he will ask a human to do it, and it will form a new have the agent had the human to solve the problem?


I think that's another critical piece.


How will the agent assist the human to solve the problem by natrowing down the guidance of what solutions reasonable or makes sense.


So if we can provide that kind of help to the aged consulting the LLM, that can be a directions.


If we just say, hey, the agent will help how?


Right?


And for that, we have to think about specific scenarios.


So it's it's like the same if only human had to solve this and how many steps they had to take.


And if on the agent was taken, then how many.


But now if human and agent is is in how many students mean that.


So I was working I had patients with this old friend of mine who was doing AI planning, you know, about indigo project, right?


So we had the AI planner and so writing newspaper on how planning systems can be used for anything resources, uh in the network for multiple operators.


But, you know, the reason I was very attracted to that effort was that the planner would pro all the possibilities to them arrive at as a small set and maybe use the set of rules to then decide which of the options in that small set would be the best.


But he never closed the loop and I have been still struggling to get him to finish that.


But it's the same sort of thing here. You are doing these agents and if we can say how you can prune the possibilities that can then be provided to the user as a very small manageable set for them to decide.


That can be the useful.. That that they in the can form a new can form new rules, right?


And when we use the certain, we have more when we use the system, the al termatic systems, they will generate a more rules, and it can handle more different situations, and will, of course, handle a new problem. Conceptually so this is this is the thing when we can of explore as our contribution novelty.


And the third thing is, we mention it before, where not model can be used in the system, so I have document. Before.


I'm not seen it, have I?


Let me let me show like . There there are several things that age in the can do, like, we talked input normalization, like the culture of the inference.


Right?


I think this is this minimal most more points coming also as our functions as as a contributions.


No. Can do Maybe one also ago, two.


I also go.


So long ago.


Yeah.


This thing is uh we are agents use a large model in a summary.


We talked first, it's like first say it'sization, normalize input email or from child or something and generates the normalized the formats . So, this thing is we want to be able to translate Yes. Scientists.


Yes, this thing that are doing this genome something. Do we, how is a computing person, but the people who are doing energy physics experiments, physics people, they will say this is what I am doing.


And we have to be able to take what they're doing and to some multi turn interaction with them arrive at the normalized input. . It's just a one function, there are also others more function like contriverance. Inferen are amazing formation. Like this thing.


I these things I want tohize it because these things are not can be handled by raw based raw based systems.


So, from the perspective, writing in paper, I think it can be our new can be a kind of contribution.


It can be all kind of or other bantage.


Why we use ag agent here?


So if we Okay, and and the first thing is, uh Can you send me this pointer again, I read it now?


Not now, I mean in the next.


And this is the sort of thing.


The fourth thing is the contribution is the interface.


Our W format or w The interface between whatow the scheduling and Yes.


We also need to formalize the interface between the scheduling and the network. Not interface with it to formalize.


Yeah, currently, yes. Once we have this VD, then we will need a form interface between, or at least let's forget about. Even if we formalize the interface between the network and the sense API for. That could be also very good. All of that together will get us a good data.


Yeah, and yes, we have had here. So for the sickness power, we use AI to generate a new rules and little new rose can be verified through the IT through little twins, and after that it can be affixed rose, and we also need to consider the rule adapted a range range and the big lie, maybe the world will expired for different situations and the rules may be have interact interactions between different rules.


So there can be a kind of challenges, I think.


How do we resolve the interactions between those rules are inconsistencies??


If you've got multiple rules that have inconsistencies between yes.


So we can verify to using the dains.


So let's see if we can work to some example to show how this agent talks to another to attrive at interpretation or interpretation of what is then what in the genome. Are and it's not nomization what rules it might have.


I agree with what you had let's take one for example and walk to that.


But for now, let's just make the pieces that we are working on. We find, you know, again.


So this week so for this week I implemented as a other I'm sorry.


Did we send a note to that we have?


Yes.


The.


You sent it to That's no email.


Yeah.


That's an email to Harvey current and and the yes, yeah..


And so this is right?


Oh, sorry.


Let me share it okay.


For this week I implemented the the r for interface. Between thecation and the scheduling agent.


Because not week we only have a code.


No, no, no, the not is the rest for race over the pis, the sched and network agent.


And another occasion with a sensape shy and the little occas with tary impment.


Yeah, but uh for the HPI between yes, yes.


Maybeano was simple, we can't improve it.


So we so we there are there is a exam pull here.


This, this is this is the topology.


Oh what what ? Okay.


So there's the box neck the cl like between the the red, right?


Yes.


The data will transfer from two and a or two to to between Atlanta and Chicago is the bottom here to here. Will transfer.


So, this there is a demo.


uh , let's say the basic information they includes a top topology and background traffic, the ill two has the background traffic from night to 12. So the capacity becomes a 40 yes. Then agent will also send the code to Little work agent.


They see the quote the.


So I think you should not ask for.


This is like the request. . I think when somebody says here, I can give you this, that's usually a quote in business language.


Okay, I see.


I don't need you to just use the terms that we computer scientists use, which is requested and response. Enough.


Unless this is already used by some other people at this court and offer.


Are they?


Or is it your?


Is it your terminology an offer?


No it's IIS terminology. . Just use it with response.


Okay, I see, okay, I see.


So, you request?


So there are two transfer.


T Tu.


Chang is from from two to one and with the data of 50 TB and this one is the one TB, and the time thing from nine to threeier. Request.


I can't room out this.


Those are two transfer requests, correct?


Yes.


Okay.


And so agent will send an agent with the offers. For a transfer will provide us three offers.


The signal offer and the three offers. ? Yes, because it's a request.


Last week we already already have the request.


Yes, yes.


Yes, yes.


I will.


Yes, yes. Finish it as fast as possible Yes, yes, yeah.


So this is the current major. Because the way it did in, there is there anything, so our own resuration zero.


And the reservation is no.


And the sense in intensity is known.


And then, the agent, we also send network agent with a reserve reserve request.


This is the reserve request a format.ust study, quot ID request ID, uh offer Yes, we can we sorry.


We can change the first part of name as request, because in the can state are the five five message as as request.


The modify is a request. Request going from the scheduler to the.


So the first can the first one cannot be called request.


Everything is.


Yeah.


Oh, you want to say request type in something.


R request. Anyway, that wasn't.


So the networkation, I will say, okay, the Russian sal and it will expire at we expire that uh 91 and uh so offer the agent choose was you here.


So, we can say the danger changed. Have you seen the VC protocol?


Sorry.


DHT.


DC the dyn .figuration for a call.


No.


It has a similar request in offer and then commentary.


So, you can use that doology if you want.


Okay.


So the later that now literation, we have the we have two reervation. What's here?


You here, just we have the processor reserve, but last week only have the request have their code, now we have reserve have commit have the modifier has the release, we have three have four more interface.


This is the current progress.


So we continue?


No, my good.


Oh, so okay, yeah.


You know that's that's all.


We can talk to these guys tomorrow about the should we present the code and the example?


Would be fine..


I want you to talk about your first.


And then you talk about your Okay.


I guess so.


The the thing that they want is to have all the stuff that you've presented in the form of slides, right I'm not responded to that request.


How do we wanted it to be in sides that we can post on the on the Google slides from what you presented last week.


Last week. Your short line and you the architecture.


So we can very good that afterwards, but we probably need to have sort of a cogent presentation of everything . So sometime in the near future, not urgent, but sometimes in the near future.


Okay.


Okay.


And I'm working on that.


The thing is with um I think for now, uh teletry region interacting with the network agent, the one is to a capacity uh the burling capacity requests that the network agent requests it is one thing. Utilization.


Right?


Yeah, and then from there, if somebody makes a request, then you can say what's the reasonable?


Yes.


Yeah. So the network agent is maint its own leg, but the telemitter agent will have its own slow, which is not like it's it's not deducting any capacity.


It's only rear time it measures on the length, it stores it in the in thement.


It also stores it in the element is not supposed to any account.


That's uh with the with the network agent, um should should should we also give it those aggregates that enter and aggregates for this um athe?


Because uh, the into aggregates might be needed when the network agent is trying to monitor the current transfer that is happening, uh, in case in case a particular transfer is is not uh sufficiently progressed, then it may want to investigate ? What is the let's say the current progress of this particular transfer?


Now, should we uh influment that right away now and also make that change in the network agent so that the tele total?


Yeah, I mean the teletry agent will give the AP so that the network agent can run the diagnosis and telemetration will run in the command to get the intern RTT or look location types.


I was not sure if I should just implement the link capacity for now with the full integration with the inter do the puzz things. And then we can then afterwards about how how to arrive at end to any yeah this is something no behavior we have to coordinate with what the network agen looking to do.


Is it trying to tell the telemetry give me this end to end capacity or does it direct right?


Oh, do you say if in this whole multiop that you show, right?


They say from source the destination . I agent will say how much capac is available for the same Coron, for one single, and it each time times lot. You know how much available.


Yes, for each year you . And then you figure out from that what is the band available for a flow going through multiple, from social to destination at the fours that you had.


You are the one who's going to check out how much is the entry in the bank of the bill.


Yes, that's for you.


You just need to give that's you guys both need to talk to each other about what he's assuming and what you can do and what you should be doing and if he's doing something that makes more sense under that.


So, have something for tomorrow?


Yeah, and let's see.


I'm we have to be very careful not to um get other people to think that they're not doing anything.


They're they know that ev that they're not, but we just need to keep doing what we can as much as we can because ultimately there's only one phase one networking project among all the so many, I don't know how many projects, hundreds, seven, hundred, you. Whatever the number. Same track.


But there is to networking effort we do a good job or some other people will come and swoop in and continue to do do aase to a new kicked up.


I hope that doesn't happen.


Even if these other guys don't do very much, whatever we have, if we can show that we are on the way to do some things sensible for place too, it'll be a good.


And the only person who I think we can depend on to work with us is cannot.


Everybody else.


I don't even know. Have you looked at her code?


Her code.


It there are not music for music.


It's not a complete.


I was going to ask to sometime. That say what is there and what she' planning to do. Main thing is the end of the next two three weeks we should have something meaningful to interface to, right?


Either on the VIT side or on the workflow side.


So that the three agents that we build will do something useful .? So, I wonder get to a point where we can say, hey, we are done.


Come on, let's figure out how the workflow uses our scheduling agent. About how your VIT will work with our network is.


So what get to that point where they can then say well, we have what we don't have something.


E that them, otherwise we would work with NRP without doing any VRT. Real set met.


Okay.



<!-- END SCINET TRANSCRIPT -->

</details>
