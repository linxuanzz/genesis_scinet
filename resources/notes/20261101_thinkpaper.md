> KK 的话:
>
> "Architecture that we are making up might be worth exploring in a paper. But I don't yet see the novelty. Let us go further, and we may find nuggets that are worth a paper.
> If we have something that says: agents can do X, Y and Z that heretofore rule based systems for network resource management and scheduling could not do, then there might be something…
> Mariam Kiran wants us to think about writing a paper on the Architecture. Not sure, but you can see that there is some enthusiasm for our work."
>
> KK 在思考目前的工作如何找出创新点发出一篇论文。请你先根据当前项目内容收集和阅读相关论文,然后创新性地思考 idea,使得可以发论文。

## 结论先说

1. **KK 的判断成立:现有架构单独拿出来不够新。** 逐项看都有前人:两阶段预留(reserve → commit)是 OGF NSI / OSCARS / SENSE 的老做法;按 (bytes, deadline) 给用户报价、让用户挑,Pretium(SIGCOMM '16)做过;"LLM 提方案、确定性组件校验"是 Confucius、Aether、6G 协商论文的共同模式;LLM 做网络诊断有 Confucius、NIKA、OFCnetLLM(Mariam 是作者之一);LLM 离线写策略有 Glia、Nada、PolicySmith。用 LangGraph 编排本身更谈不上贡献。
2. **我认为能撑起论文的一句话是:规则系统(以及任何优化器)只能在给定的问题里求最优,agent 的增量来自改写问题本身。** 这句话在 [20260926_agent.md](20260926_agent.md) 里已经有雏形("Rules decide inside a well-defined problem; the agent keeps the problem well-defined when the world around it isn't"),但当时没有变成可测的东西。
3. **把它变成可测的办法:closed-world oracle。** 在同一份请求 schema 上,算出离线最优解(穷举或 MILP,知道全部未来请求)。任何规则系统、启发式、RL,只要不改问题,都不可能超过这个 oracle。agent 如果超过了,超出的那部分就是"规则系统做不到"的定量证据,而且不依赖于我们挑了多弱的 baseline。这正是 KK 要的 "X, Y, Z that rule based systems could not do"。
4. **候选的 X、Y、Z,加一条保底的 W:**


|                | agent 能做而规则系统做不到的事                                                                                   | 为什么规则做不到                                                                            | 现有代码里的种子                                           |
| -------------- | ---------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------- | -------------------------------------------------- |
| **X** 改写请求     | 请求不可行时,不是拒绝,而是用 workflow 语义改写请求本身:先传 10% 预览供 steering、改用另一站点的副本、在边缘先做数据缩减、换计算站点                      | 规则系统只能在网络自己的维度(路径、速率、开始时间、价格)上调整;请求的弹性在 workflow 语义里,不在 schema 里,而且每类 workflow 各不相同 | offer 的 `blocked_by`:告诉对方"卡在哪、被谁占、何时释放"            |
| **Y** 修正目标     | 把"8 PM 前要"还原成 utility curve(平台期、递减段、作废点),按科学价值而不是字面 deadline 做取舍                                     | 规则系统把 deadline 当作给定输入;目标函数本身缺失时规则无从下手                                               | 9/28 会上的 utility curve 讨论                          |
| **Z** 运行期跨域重协商 | 承诺 `at_risk` 时,network agent 给出修复选项(降速、延后、部分交付、换路),scheduling agent 结合 workflow 的 slack 和计算站点状态选择或调序 | 单域规则只能按 priority 抢占或丢弃;要联合决策又需要各站点交出完整状态,而站点不会交                                     | 图 B(runtime)设计、`at_risk` 消息                        |
| **W** 不牺牲保证    | 以上全部由 LLM 只提方案,ledger 做唯一的提交者;无论 LLM 输出什么,overcommit 恒为 0                                            | —(这是让 X/Y/Z 可以上生产的前提)                                                               | "The LLM never writes the ledger";reserve 的原子预扣与回滚 |


1. **最值得做主线的是 X**,其次是 W(便宜、能直接做实验)。Y 有边界争议(见 §4),Z 需要图 B 先做出来。

下文依次是:文献地图、规则系统的隐含前提、oracle gap 方法、X/Y/Z/W 展开、评测草案、次要点子、与 Mariam 说的 architecture paper 的关系、建议的下一步。

---



## 1. 文献地图:哪些已经有人做了


| 方向                       | 代表工作                                                                                                                                                       | 做了什么                                                                          | 我们不能再声称的                         |
| ------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------- | -------------------------------- |
| 广域网截止期传输与带宽预留            | TEMPUS(SIGCOMM '14)、Amoeba(EuroSys '15 / ToN '17)、Pretium(SIGCOMM '16);OSCARS、NSI、SENSE;Zuo 等关于预留与容错的系列论文                                                  | 按大小和 deadline 在路径与时间上"打包"传输;Pretium 用动态价格给每个请求报价,达到离线 oracle 社会福利的约 80%       | 时间-容量账本、多 offer 报价、两阶段预留         |
| ML / RL 做流量工程(Mariam 的线) | DeepRoute(2019)、Hecate(INDIS '22,ESnet)                                                                                                                    | 深度强化学习学 TE 控制,多目标优化                                                           | "用 AI 做网络资源决策"这一笼统说法             |
| LLM 网络运维                 | Confucius(SIGCOMM '25,Meta)、MeshAgent(SIGMETRICS '26)、OFCnetLLM(Yoon、**Kiran** 等,2025)、NIKA 基准、AIDA(SIGCOMM '26)、SIGCOMM '25 的 LLM 故障定位                    | 意图翻译、工具调用、validator + dry run、根因分析                                            | LLM 诊断、LLM 意图翻译、"LLM 只推理、事实来自工具" |
| LLM + digital twin 做验证   | Aether(Cisco/Swisscom,2026 arXiv)、IETF NMRG agent-NDT 架构草案                                                                                                 | 多个 agent 在共享 twin 上验证配置变更                                                     | "twin 当 LLM 的 guardrail"         |
| LLM 资源协商                 | 6G 切片协商(arXiv 2511.19175)、LLM 辅助 contract net(arXiv 2608.12371)、Symbiotic Agents(arXiv 2507.17695)、Counterparty Modeling is Not Strategy(arXiv 2605.16575) | 两个切片 agent 就带宽和 CPU 讨价还价,确定性控制器保证可行;发现 LLM 只看均值、忽视尾部风险;多轮协商提高准确率但 token 与时延大增 | "agent 之间用 LLM 协商资源"             |
| LLM 离线写策略                | Glia(MIT,2025)、Nada(HotNets '24)、PolicySmith、Agentic-V2X(2026)                                                                                             | LLM 生成可解释的调度/路由算法,在模拟器中评估后部署,运行时不调 LLM                                        | "LLM 生成规则、twin 里评估"              |
| 科学 agent 基础设施            | Academy(Globus,Pauloski 等)、ORNL 跨设施自主实验架构、ALS 加速器 agent(arXiv 2509.17255)、LBNL 2026 年 1 月 user facility agent workshop                                     | 跨 HPC / 设施部署有状态 agent;"co-pilot":agent 提议、人批准关键步骤                             | "科学 workflow 的 agent 化"          |


**我看到的空隙**(检索有限,不等于不存在):

- 没找到把 LLM agent 用在**广域网带宽预留 / 截止期传输**上的工作。
- 已有的 LLM 资源协商都在 6G 切片和边缘计算里,**协商的维度仍是网络自己的维度**(带宽、CPU、时延)。没有一篇让 agent 在"请求方的语义维度"上做文章。
- 科学 agent 基础设施(Academy、ORNL 跨设施)**把网络当透明管道**;网络一侧的工作(Confucius、OFCnetLLM)**不了解上层 workflow**。SciNet 夹在中间,"science-aware" 正好是这个缝。(2026-11-02 修正:后一句说重了。Confucius 知道服务名和流量等级,但不知道 workflow 的截止时间、依赖与弹性。例子与修正见文末第 6 个问答。)



## 2. 规则系统的隐含前提,以及科学 workflow 怎样打破它们

TEMPUS、Pretium、OSCARS 这一类系统能工作,依赖下面这些前提(这是我的归纳,不是这些论文自己写的):


| 前提           | 规则/优化系统里的样子                                           | 科学 workflow 里的现实                                                  |
| ------------ | ----------------------------------------------------- | ----------------------------------------------------------------- |
| ① 请求是完整且刚性的  | (src, dst, bytes, deadline) 就是合同;系统只能接受、拒绝,或调路径/速率/时间 | bytes 不神圣(可以先传子集、压缩、在边缘缩减);dst 不唯一(有副本、可换计算站点);传输之间有 DAG 耦合       |
| ② 目标函数是给定的   | 最大化满足 deadline 的数量、利用率、或按价格算的社会福利                     | 价值由实验定义(steering 回路、beamtime 窗口),deadline 只是对 utility curve 的粗糙压缩 |
| ③ 只有网络一种资源   | 计算、仪器在系统之外                                            | 传输晚了,可以用计算调序吸收(slack),也可以换站点                                      |
| ④ 单一管理域、全局视图 | TEMPUS、Pretium 是集中式                                   | 跨 DOE 站点、ESnet、大学网络,各方只公开部分状态                                     |
| ⑤ 异常可以预先枚举   | 保护路径、按 priority 抢占                                    | 叠加故障、主机与网络难区分                                                     |


前提 ① 和 ② 被打破,是 X 和 Y 的来源;③ 和 ④ 被打破,是 Z 的来源;⑤ 是诊断方向,已经很拥挤(§6)。

## 3. 核心方法:closed-world oracle gap

**做法:**

1. 固定一份请求 schema,即我们现有的 `TransferRequest`(src, dst, bytes, window, priority)。
2. 对给定场景(拓扑、背景流量、全部请求按到达顺序),在这个 schema 内求离线最优:知道全部未来请求、只能调路径/速率/时间、接受或拒绝。demo 规模可以穷举,规模大一点用 MILP。
3. 任何不改问题的系统(earliest-start 规则、TEMPUS 式打包、Pretium 式报价 + 规则请求方、RL)都 ≤ 这个 oracle。
4. agent 允许改写问题(X、Y、Z),再交回同一个确定性求解器和 ledger。
5. 报告 **agent 相对 oracle 的差值**,按来源分解:X 带来多少、Y 带来多少、Z 带来多少。

**为什么这比"打败若干 baseline"更有说服力:**

- 不依赖于 baseline 强弱。审稿人最常见的质疑是"你的规则 baseline 太弱",oracle 直接堵住这条路。
- 正好对应 KK 的问法:不是"agent 比规则好一点",而是"**规则系统在原则上做不到**"。
- 同时可以展示反面:在不需要改问题的场景里,agent 不应比 oracle 差太多(因为数字仍由求解器算),也不应更好。如果更好,说明实验有漏洞。

**这个框架的软肋(必须正面回应):** 审稿人会说"那就把 schema 扩展一下,加个 elasticity 字段,规则也能做"。回应只能是:

- 弹性藏在异构、非结构化的材料里(设施 user guide、workflow 代码、过去的运行记录),每类 workflow 都不一样,扩展 schema 需要逐类做知识工程;agent 的贡献是在运行时完成这件事。
- 这要求评测里有**设计系统时没见过的 workflow**(held-out),否则"agent 找到了我们自己写进描述里的弹性"就是自证。



## 4. X、Y、Z、W 展开



### X:改写请求(semantic relaxation)—— 建议的主线

**一个例子**(数字只为说明):beamline 下午采了 40 TB,要传到 ORNL 做重建,6 PM 前要结果以决定下一批样品。主路径的一段被背景流量占到 12:00 之后,quote 的结果是"任何 offer 都在 7:30 PM 之后完成"。

- 规则系统:拒绝,或给一个晚到的 offer。
- agent:看到 offer 里的 `blocked_by = background_traffic, link L2, until 12:00`,结合 workflow 语义("steering 只需要每个扫描的前 5% 帧"),改写成两个请求:2 TB 预览立即以低速走主路径,其余 38 TB 在 12:00 之后高速传。预览满足 6 PM 的 steering 需求,全量数据当晚完成。

> **更正(2026-11-01)**:这个例子是我编的,"前 5% 帧"、40 TB、拆成 2 TB + 38 TB 都没有出处,"前 5% 帧"的说法本身也不准确。有真实论文支撑的版本见文末第 2 个问答。

**这里有一个可以单独成立的协议点子:offer 带上"为什么"。**

- Pretium 给请求方的信号是**价格**;请求方只能接受或拒绝,规则化的请求方也只能"按价格挑"。
- 我们的 offer 已经带 `blocked_by`。把它扩成结构化的**不可行原因与反事实**:卡在哪条链路、被谁的流量占、何时释放;"如果晚 2 小时开始 → 可用 100 Gbps";"如果 bytes ≤ 10 TB → 能赶上 deadline"。
- 优化里这就是瓶颈约束的对偶变量(shadow price),只是贴上了语义标签(链路、时段、背景流量)。规则化的请求方只能对这些信息写死几条反应;LLM 请求方能把它们映射到 workflow 层面的改写。
- 一句话版本:**Pretium gives a price; we give a reason.** 这是我目前觉得最像 "nugget" 的一点,需要再查文献确认没人这样做过。

**可测的假设:** 在争用场景下,带原因的 offer + LLM 请求方 > oracle(在原 schema 内);去掉原因、只给 offer 时,增益显著下降;原因相同但请求方是规则时,增益也下降。两个消融分别证明"原因"和"LLM"各自必要。

### Y:修正目标(utility curve)

- 价值:同样的容量,按曲线分配比按字面 deadline 分配能交付更多科学价值。例 1(beamtime)和例 2(托卡马克放电间隙)的曲线形状见 [20261004_utility_curve.md](20261004_utility_curve.md)。
- **边界冲突**:9/22 合作方明确说"本项目提供机制,不替实验定 policy 或 success metric"(已记在 [20260926_agent.md](20260926_agent.md) §4)。所以 Y 只能写成"从实验已声明的偏好中提取曲线,交人确认",不能写成"LLM 决定价值"。
- 作为论文的一部分可以,单独做主线会被问"曲线对不对谁来判"。



### Z:运行期跨域重协商

- 诚实的一点:**如果所有信息集中在一处,一个确定性的联合优化器(网络 + workflow slack + 计算)也能做 Z**,不需要 LLM。所以 Z 的价值只在两种情况下成立:站点不愿交出完整状态;修复选项是开放的(换站点、改数据量,与 X 重叠)。
- 评测要同时报两个参照:单域规则(下界)和全知联合优化器(上界,现实中不可得)。agent 应落在两者之间,且越接近上界越好。
- 需要先实现图 B,短期做不了。



### W:不牺牲保证

- 不变量:任何 agent 行为下,ledger 不出现 overcommit;整组 reserve 原子;commit 失败可重试。
- **最便宜的实验**:把 LLM 换成随机或对抗性的提议者(乱改速率、重复 reserve、提交过期 offer),跑大量回合,统计不变量违反次数应为 0,同时记录被拒提议的比例。这把"LLM 可能乱来"从担忧变成数字。
- 这也部分回应 KK 在 10/22 提的独立验证问题:验证的对象不只是 LLM 写的代码,还有 LLM 在运行时的决策,两者用同一组不变量检查。
- 单独不够成论文(propose-verify 已有很多),但适合作为论文里的安全性小节。



## 5. 评测草案(待与 KK 对齐,不是计划)


| 项   | 草案                                                                                                                                   |
| --- | ------------------------------------------------------------------------------------------------------------------------------------ |
| 环境  | 现有 mock network(slide 3 拓扑 + 背景流量),之后换 digital twin;短期不依赖真实 twin                                                                     |
| 负载  | 2–3 类 workflow:beamline steering(有 utility curve)、1000genome 批处理、夜间 replication;每类配一份自然语言说明,弹性信息取自真实资料(设施手册、已发表的 workflow 描述),不是我们编的 |
| 对照  | ① earliest-start 规则;② TEMPUS 式打包;③ Pretium 式报价 + 规则请求方;④ closed-world oracle;⑤ agent 去掉"原因"(只看 offer);⑥ 原因 + 规则请求方;⑦ 完整 agent        |
| 指标  | 交付的 utility(按曲线算)、deadline 命中率、相对 oracle 的差值及其分解、overcommit 次数(必须为 0)、**不安全改写次数**(违反科学约束的改写,例如对必须全量的数据只传预览)、LLM 调用次数与时延              |
| 防自证 | held-out workflow;描述里放干扰信息(不能缩减的数据也写上"可以压缩"之类的误导),测 agent 的精确率而不只是召回率                                                                |


**主要风险:**

1. 弹性来源太人为,被看成玩具。缓解:弹性取自真实资料,加 held-out 与干扰项。
2. "扩展 schema 就行"的质疑。缓解见 §3。
3. LLM 时延:改写发生在 quote 循环之外(秒级到分钟级),不碰 200 ms 的协调指标;这点要在论文里写清。
4. 6G 协商论文发现 LLM 忽视尾部风险。我们的 offer 若带 p50/p95,要检验 LLM 是否真的用 p95,而不是只看 p50。这本身可以是一个小发现。



## 6. 次要点子(不建议做主线)


| 点子                                               | 为什么不做主线                                                                                     |
| ------------------------------------------------ | ------------------------------------------------------------------------------------------- |
| 语义 overbooking(KK 的 ATM 想法:按 workflow 相关性决定超额多少) | 有意思,但需要真实流量与 workflow 共现数据,Phase 1 没有;经典 overcommit 文献(云、航空)很多                              |
| LLM 诊断 + 选下一次 probe                              | 非常拥挤(Confucius、NIKA、SADE、AIDA),Mariam 组自己有 OFCnetLLM,我们没有数据优势                               |
| LLM 写策略、twin 里评估                                 | Glia、PolicySmith、Agentic-V2X 已占位;我们的 twin 还没就绪                                              |
| 独立验证 LLM 生成的代码                                   | 偏软件工程,离 SciNet 远                                                                            |
| "agent 之间的承诺协议"本身                                | reserve/commit 是 NSI 的老东西;A2A / MCP 这类 agent 协议确实没有带 TTL、原子组预留的"资源承诺"语义,但单靠这点不够,只能当论文里的设计部分 |




## 7. 和 Mariam 说的 "architecture paper" 怎么对上

- 可以写成架构论文,但**架构是载体,论点是 oracle gap**。纯架构描述(几个 agent、几张图、几种消息)在 INDIS 这类 workshop 也许能中,但正如 KK 所说,看不出新意。
- 一种组织方式:§架构(三张图、ledger 作为唯一提交者、带原因的 offer)→ §为什么规则做不到(前提表 + oracle 论证)→ §X/W 的实验 → §Y/Z 作为设计与初步结果。
- 题目方向(只为说明口径):"Rules Solve the Problem, Agents Change It: Negotiated Data Movement for Autonomous Science" 或 "Beyond the Closed-World Oracle: …"。
- 会议:INDIS(SC workshop,Mariam 熟悉)、HotNets(偏想法,适合 oracle gap 这种论点)、SIGCOMM / NSDI 需要更完整的系统与真实数据。**各会的 2027 年截稿日期我没有查,需要核对。**



## 8. 建议的下一步(只给一个)

**先把 §结论的 X/Y/Z/W 表和 §3 的 oracle gap 方法整理成一页,带去和 KK 讨论,确认他是否认可这个论点方向。** 这是方向决策,应由 KK 和你来定。如果认可,第一个探路实验就是 X 的最小版本:在现有 quote 分支上,一个争用场景、两类 workflow、穷举 oracle 对比"带原因的 offer + LLM 请求方",先看差值是否存在。

## 未核实与需要回查的地方

- NSI 的 reserve / reserveCommit 两阶段语义来自我的已有知识,本次没有重新查原始规范。
- Pretium、TEMPUS 的细节只看了摘要和二手描述;"约 80% oracle 福利"出自 Pretium 摘要。
- 6G 协商、contract net、Aether、OFCnetLLM 只读了 arXiv 摘要页,没有读全文。
- "没有人把 LLM agent 用于广域网带宽预留"、"没有人在 offer 里给请求方结构化的不可行原因"是检索不到的结论,不是证明;写论文前要做更系统的检索(尤其是 multi-domain 预留与 SLA 协商的老文献)。



## 参考来源

- [Pretium: Dynamic Pricing and Traffic Engineering for Timely Inter-Datacenter Transfers (SIGCOMM '16)](https://www.microsoft.com/en-us/research/wp-content/uploads/2016/08/pretium_sigcomm16.pdf)
- [Calendaring for Wide Area Networks / TEMPUS (SIGCOMM '14)](https://www.microsoft.com/en-us/research/?p=166762)
- [Amoeba (ToN '17)](https://cse.hkust.edu.hk/~kaichen/papers/amoeba-ton17.pdf)
- [Fault-tolerant bandwidth reservation strategies (Zuo et al.)](https://escholarship.org/uc/item/0205h79j)
- [Hecate: AI-Driven WAN Traffic Engineering for Science (INDIS '22 talk)](https://scinet.supercomputing.org/community/documents/148/INDIS_Final_SC22Talk.pdf)
- [DeepRoute on Chameleon (MERIT workshop)](https://webarchive.ucr.edu/icnp19.cs.ucr.edu/proceedings/Workshops/MERIT/paper_4.pdf)
- [OFCnetLLM: LLM for Network Monitoring and Alertness (Yoon, Kiran, Ebling, Breen, 2025)](https://arxiv.org/abs/2507.22711)
- [Confucius: Intent-Driven Network Management with Multi-Agent LLMs (SIGCOMM '25)](https://minlanyu.seas.harvard.edu/writeup/sigcomm25.pdf)
- [An LLM-based Agentic Framework for Accessible Network Control](https://arxiv.org/abs/2509.20600)
- [Aether: Network Validation Using Agentic AI and Digital Twin](https://arxiv.org/abs/2604.18233)
- [IETF 124 NMRG: NDT-based architecture for AI-driven network operations](https://datatracker.ietf.org/meeting/124/materials/slides-124-nmrg-network-digital-twin-based-architecture-for-ai-driven-network-operations-00)
- [LLM-Based Agentic Negotiation for 6G](https://arxiv.org/abs/2511.19175)
- [Multi-Agent Scheduling with LLM-Assisted Contract Net Negotiation](https://arxiv.org/pdf/2608.12371)
- [Symbiotic Agents](https://arxiv.org/pdf/2507.17695)
- [Counterparty Modeling is Not Strategy](https://papers.cool/arxiv/2605.16575)
- [Glia: A Human-Inspired AI for Automated Systems Design and Optimization](https://arxiv.org/abs/2510.27176)
- [Agentic-V2X](https://arxiv.org/pdf/2607.04290)
- [Empowering Scientific Workflows with Federated Agents (Academy)](https://arxiv.org/abs/2505.05428)
- [AI agents for enabling autonomous experiments at ORNL's HPC and manufacturing facilities](https://impact.ornl.gov/en/publications/ai-agents-for-enabling-autonomous-experiments-at-ornls-hpc-and-ma/)
- [Agentic AI for Multistage Physics Experiments at a Particle Accelerator](https://arxiv.org/pdf/2509.17255)
- [Berkeley Lab Agentic AI for User Facilities Workshop](https://als.lbl.gov/berkeley-lab-hosts-agentic-ai-for-user-facilities-workshop/)
- [FaulT-Bench](https://arxiv.org/pdf/2608.27021)
- 项目内:[20260926_agent.md](20260926_agent.md)、[20261004_llmrole.md](20261004_llmrole.md)、[20261004_utility_curve.md](20261004_utility_curve.md)、[20261014_networkagent.md](20261014_networkagent.md)、[10/27 会议](../meetings/20261027_scinet_network_telemetry.md)

---

> 1. "steering 只需要每个扫描的前 5% 帧"这句话莫名其妙的,结合例子,什么意思?
> 2. 你给的 X 的 beamline 的例子中,"预览满足 6 PM 的 steering 需求,全量数据当晚完成。",是否有真实依据,还是你编的?如果这是编的,请你找出真实的例子,并且有官方论文/说明背书。



### 1. 那句话想说什么,以及它为什么说不通

**想表达的意思**:决定实验下一步怎么做(steering),往往只需要数据的一小部分;完整数据要留着做最终分析,但不必赶在决策时刻之前到。

- **steering**:实验进行中,根据刚采到的数据的分析结果,调整接下来的实验,例如换样品、改参数、把视野移到感兴趣的区域。
- **帧(frame)**:探测器拍的一张图。在 CT(断层扫描)里,样品转一圈,每个角度拍一张投影图(projection),一次扫描是几百到几千张。

**这句话的问题**:

- "前 5%"是我随手写的数字,没有出处。
- "每个扫描的前 5% 帧"在 CT 里说不通:前 5% 的帧只覆盖了前 5% 的旋转角度,用它重建不出可看的图像。真正能用来做快速预览的子集是另一种取法(见下文的真实例子):每个角度都要,但每张图做降采样(binning),或者只重建少数几个切片。



### 2. 例子是编的;真实的对应例子

**承认**:§4 X 里 beamline 的整个例子(40 TB、6 PM、"前 5% 帧"、拆成 2 TB 预览 + 38 TB 全量)都是我编来说明机制的,没有出处。当时只写了"数字只为说明",没有说明机制本身也是推想,这是我的问题。已在原处加了更正。

#### 最接近的真实例子:APS 2-BM 的实时流式重建(有论文)

Nikitin, Tekawade, Duchkov, Shevchenko, De Carlo,*Real-time streaming tomographic reconstruction with on-demand data capturing and 3D zooming to regions of interest*,Journal of Synchrotron Radiation 29 (2022) 816–828,doi:10.1107/S1600577522003095。工作在 Argonne APS 的 2-BM 线站完成。我们 demo 拓扑里的 `aps-beamline-8id` 也在 APS,但 2-BM 是另一条线站。

论文原文能支撑的几点:


| 论点                | 原文(英文原句)                                                                                                                                                              | 出处          |
| ----------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------- |
| steering 不需要完整 3D | "In many cases there is no need to reconstruct a full 3D data volume in real-time."                                                                                   | §2.3        |
| 只重建三个切片,且很快       | "real-time reconstruction of three arbitrary slices through the sample";"the total reconstruction time is always less than 1 s."                                      | §2.3、§3 表 1 |
| 对比:完整 3D 重建慢得多    | "the reconstruction time of a full 3D volume using tomoPy ... is about 15 min"(CPU)                                                                                   | §1          |
| 完整原始数据按需另存        | "The second pipeline is associated with on-demand data capturing to an HDF5 file";"no data binning or cropping is applied in this case."                              | §2.1        |
| 预览确实用来 steering   | "one can select a relevant sample region directly looking at the streaming reconstruction";冰与气体水合物实验中,据此选出区域并"automatically zoomed into it with higher magnification" | 结论、§4       |


也就是说,真实做法是**两条流水线**:一条流式数据做低延迟预览,用来决定下一步;另一条按需捕获完整数据,用于事后分析。这和我想说的"预览供决策、全量随后"是同一个结构。

**但它不能直接证明我们的 X,差在三处:**

1. **它在线站本地完成**(commodity computers,紧挨探测器),不经过广域网,也没有网络资源分配。
2. **省下的主要是计算,不一定是数据量。** 重建任意方向的三个切片,仍需要每个角度的投影,所以"只重建三个切片"本身不减少要传的数据。能减少数据量的是降采样或裁剪(binning / cropping)。论文写明按需捕获那条"不做 binning 或 cropping",由此推断流式那条可以做;这是我的推断,需读原文 §2.1 确认流式流水线的默认设置。
3. **决定拆分的是人和线站软件,不是 agent。** 把它搬到广域网上,变成"network agent 发现全量赶不上,建议拆成降采样预览流 + 全量后传",是我们要提出的东西,不是已有事实。



#### 广域网上确有时间敏感的 steering 传输(有官方说明)

这两例能支撑"跨站点、为实验决策服务、有软截止时间的传输在 DOE 真实存在",但**不涉及预览/全量拆分**:

- **LCLS → NERSC(ExaFEL)**:Blaschke 等,*Real-Time XFEL Data Analysis at SLAC and NERSC: a Trial Run of Nascent Exascale Experimental Data Analysis*(arXiv 2106.11469;后发表于 Concurrency and Computation: Practice and Experience,2024)。摘要写从采集到完整分子重建的周转"in as little as 10 min -- sufficient time for the experiment's operators to make informed decisions"。
- **DIII-D → NERSC(经 ESnet)**:NERSC / ESnet 2024 年的官方新闻。放电间隔约 20 分钟,自动化 workflow CAKE 把放电间隙分析从约 60 分钟缩到约 11 分钟,结果用于指导下一次放电。



#### 用真实材料重写 X 的例子(仍需标注哪些是推想)

> 事实(Nikitin 2022):在 APS 的流式 CT 中,steering 只需要三个切片的实时重建(< 1 s),完整原始数据另行按需捕获;完整 3D 重建在 CPU 上约 15 分钟。
>
> 事实(ExaFEL、DIII-D):DOE 已有把实验数据经广域网送到 NERSC、在分钟级内返回结果以指导实验的生产 workflow。
>
> **推想(本项目要论证的)**:当分析放在远端 HPC、而广域网容量不足以按时送达全量流时,network agent 根据 offer 里的瓶颈原因,向 scheduling agent 提出"降采样的预览流按时送达、全量捕获数据随后传"的改写;规则系统只能接受、拒绝或推迟全量请求。

**后续要补的证据**:找一个"预览/降采样数据经广域网送远端分析、全量随后传"的真实部署或论文。候选方向是 LCLS-II 的数据缩减流水线和 NCEM 4D Camera 到 NERSC 的流式传输(Welborn 等,arXiv 2407.03215),但这次没有核实它们是否做了这种拆分,不能引用。

来源:

- [Nikitin et al., J. Synchrotron Rad. 2022 (PMC 全文)](https://pmc.ncbi.nlm.nih.gov/articles/PMC9070713/)
- [Blaschke et al., Real-Time XFEL Data Analysis at SLAC and NERSC (arXiv 2106.11469)](https://arxiv.org/abs/2106.11469)
- [ESnet: DIII-D, NERSC, and ESnet Collaboration (2024)](https://www.es.net/news-and-publications/esnet-news/2024/diii-d-nersc-and-esnet-collaboration/)
- [NERSC: DIII-D National Fusion Facility, NERSC, and ESnet Collaboration Speeds Nuclear Fusion Research](https://www.nersc.gov/news-and-events/news/diii-d-national-fusion-facility-nersc-and-esnet-collaboration-speeds-nuclear-fusion-research)
- [Welborn et al., Streaming Large-Scale Electron Microscopy Data to a Supercomputing Facility (arXiv 2407.03215)](https://arxiv.org/abs/2407.03215)(未核实是否涉及预览拆分)

---

> 1. 继续找证据
> 2. 你的 X 的意思其实就是想强调一种规则外、基于 workflow 语义的变通性,类似于普通算法只能修改参数,LLM 可以跳脱出去修改规则/超参数。所以你不必拘泥于这一个例子(预览 + 全量随后传)。找找更多其他、真实、有背书、语义感知后可调规则的例子。

**理解一致。** X 要说的是:TEMPUS、Pretium 这类系统只在请求给定的框架里调路径、速率、开始时间;而科学 workflow 的请求本身可以改写:要传的东西、传到哪、分几段、什么时候必须到、哪些不许动。能不能改、怎么改,取决于 workflow 语义。

下面的例子都是**真实部署或已发表的工作**,按"请求里哪一项被改写"分类。需要说明:**这些改写全部是人在设计阶段为某个设施专门做的工程,不是 agent 在运行时做的。** 它们证明的是"规则之外的改写空间真实存在、而且因 workflow 而异",不证明 agent 能自动做到;后者是我们要论证的。

### 1. 改写"传什么":传派生量或缩减后的数据,原始数据另行处理


| 案例                                   | 改写了什么                                                                      | 依据什么语义                                                             | 来源与可信度                                                                                                         |
| ------------------------------------ | -------------------------------------------------------------------------- | ------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------- |
| **LIGO 引力波**:低延迟只传 h(t)(应变数据),原始帧走批量 | 同一台探测器的数据拆成两种请求:h(t) 低延迟(秒级,经 Kafka),raw 批量(早期规划为最多 1 天延迟,经 LDR / GridFTP) | 发预警只需要 h(t);O2 期间 H1 的 h(t) 约 2.4 TB,raw 约 600 TB,h(t) 不到 raw 的 1% | IGWN 官方计算文档(低延迟数据);LIGO/Virgo 规划幻灯与 O2 数据表(会议材料,非论文)。**这是我第一版编的"预览 + 全量随后"的真实版本**                              |
| **LCLS-II 数据缩减流水线(DRP)**             | 写盘前丢掉 X 射线没打中样品的帧(veto,幻灯写 > 10 倍缩减),再做 SZ 有损压缩、特征提取                       | "没打中的帧对科学无用";压缩误差要不影响重建结果                                          | Thayer 等 CHEP 2023 论文 *Massive Scale Data Analytics at LCLS-II*;SLAC 2021 新闻;Thayer 2024 IFDEPS 幻灯。veto 倍数出自幻灯 |
| **Ocelot(Globus + 有误差上界的有损压缩)**      | 广域网传输前用 SZ 压缩,用户给误差上界                                                      | 下游分析能容忍多大误差,由科学用途决定;系统用模型预测压缩质量,让用户可以信任                            | Liu、Di、Chard、Foster、Cappello,arXiv 2307.05416。综述称传输时间减少 90% 以上,该数字为二手引用,未核对原文                                  |
| **自主实验(gpCAM,NSLS-II / ALS)**        | 不做网格全扫描,由高斯过程挑下一个测量点,数据量从源头就变少                                             | 科学目标(找到相变边界、峰值区域)决定哪些点值得测                                          | 方法:Noack 等,Sci. Rep. 9, 11809 (2019);Nat. Rev. Phys. 综述 (2021)。"只需 15% / 12% 的数据"出自 Noack 的幻灯,未见于论文            |




### 2. 改写"传多少、按什么精度":渐进式取数


| 案例             | 改写了什么                             | 依据什么语义                                      | 来源                                                                             |
| -------------- | --------------------------------- | ------------------------------------------- | ------------------------------------------------------------------------------ |
| **MGARD 渐进检索** | 数据先重构成多层;按用户要求的误差逐步取,先取粗的、需要时再补细的 | 分析对误差的要求可以逐步收紧;同样的误差要求下,取回的数据量比单一误差的方法少 64% | Liang 等,SC '21,doi:10.1145/3458817.3476179;后续 Wu 等 arXiv 2411.05333 按派生物理量控制误差 |


这一项和"预览 + 全量"同构,但有同行评审背书,而且误差可控。

### 3. 改写"什么时候必须到":同一份数据,用途不同,截止时间不同


| 案例                       | 改写了什么                                                                        | 依据什么语义                             | 来源                                                                                                                     |
| ------------------------ | ---------------------------------------------------------------------------- | ---------------------------------- | ---------------------------------------------------------------------------------------------------------------------- |
| **Vera C. Rubin 天文台**    | 同一张原始图像:为发预警,7 秒内从智利山顶送到 SLAC(4 GB 压缩数据,含压缩开销);禁传期(80 小时)过后,全量再复制到法国、部分复制到英国 | 预警要在读出后 60 秒内发出;禁传期是政策约束,时间到了才允许外传 | Hernandez 等,*Data Movement Model for the Vera C. Rubin Observatory*,arXiv 2507.12955。另:通用的 Rucio 赶不上 7 秒,所以快速传输是专门写的代码 |
| **DIII-D 托卡马克 → NERSC**  | 放电间隙分析的目标是在约 20 分钟的两次放电之间给控制室结果                                              | 结果只在下一次放电前有用                       | Bechtel Amara 等,Frontiers in Physics (2024),doi:10.3389/fphy.2024.1524041                                              |
| **KSTAR → NERSC(DELTA)** | 跨 9000 公里流式分析,约 5 分钟完成流式传输、分析与可视化;放电间隔约 10 分钟                                | 同上                                 | Kube、Churchill 等,Plasma Phys. Control. Fusion (2022),arXiv 2108.08896;时间数字出自 ITER 2021 技术会议幻灯                          |
| **LCLS → NERSC(ExaFEL)** | 采集到重建约 10 分钟,足够操作人员在实验中做决定                                                   | 同上                                 | Blaschke 等,arXiv 2106.11469                                                                                            |


Rubin 的禁传期也说明,语义不只带来"可以放宽",也带来"不许提前"。规则系统同样不会知道这类约束。

### 4. 改写"传到哪":换计算站点,或把计算挪到数据旁边


| 案例                           | 改写了什么                                                                                                                                  | 依据什么语义                                                                                    | 来源                                          |
| ---------------------------- | -------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------- | ------------------------------------------- |
| **DIII-D 双站点**               | 同一个 workflow 可以在 NERSC 或 ALCF 跑:"the calculation could just as easily run at NERSC if the ALCF systems were shut down for maintenance" | 只依赖单一 HPC 设施的局限("its own maintenance and downtime schedule");workflow 与站点无关,只要配置脚本描述了可用系统 | Bechtel Amara 等,Frontiers in Physics (2024) |
| **APS / LCLS 边缘推理(BraggNN)** | 推理放在线站的边缘设备上,不把原始衍射数据实时送远端;只为周期性重训练把数据送到 ALCF                                                                                          | 实验需要的是"峰位置"这个可行动信息,不是原始图像                                                                 | Liu 等,IEEE XLOOP 2021,arXiv 2105.13967      |




### 5. 改写"一次传完还是分批流":改变请求的粒度


| 案例                         | 改写了什么                                                        | 依据什么语义                | 来源                                                                                                     |
| -------------------------- | ------------------------------------------------------------ | --------------------- | ------------------------------------------------------------------------------------------------------ |
| **ATLAS Data Carousel**    | 不把整批输入从磁带全部搬到磁盘再处理,而是滚动窗口:取一部分、处理一部分、释放一部分;同一时刻磁盘上的 AOD 不到一半 | 处理任务可以按文件逐个消费,不需要整批到齐 | Borodin 等,EPJ Web Conf. 245, 04035(CHEP 2019)与 295, 01054(CHEP 2024);ATLAS Run 3 计算论文 arXiv 2404.06335 |
| **NCEM 4D Camera → NERSC** | 跳过中间文件,从探测器缓存直接流到 NERSC 计算节点内存(约 480 Gbit/s,15 秒产生 700 GB)   | 分析可以边到边算              | Welborn 等,arXiv 2407.03215                                                                             |
| **APS 2-BM 流式 CT**         | 一条流做三个切片的实时预览,完整数据按需另存                                       | 见第 2 个问答              | Nikitin 等,J. Synchrotron Rad. (2022)                                                                   |




### 6. 这些例子合起来说明什么

**观察(有上表支撑):**

1. **改写空间覆盖请求的每一个字段**:传什么(LIGO、LCLS、Ocelot、gpCAM)、精度(MGARD)、截止时间与禁传(Rubin、DIII-D)、目的地(DIII-D、BraggNN)、粒度(ATLAS、4D Camera)。TEMPUS / Pretium 能调的只有路径、速率、开始时间,以及是否接受。
2. **每一种改写都由各设施团队专门实现**:Rubin 因为 Rucio 不够快而另写传输代码;LCLS 的缩减算法按实验设参数;DIII-D 要为每个站点写配置脚本。没有一种是通用网络系统提供的。
3. **每一种改写都带着科学上的有效性条件**:LCLS 保留一部分未缩减的数据做验证(幻灯写 100 Hz);Ocelot 先预测压缩质量再让用户信任;MGARD 控制误差上界;Rubin 有禁传期。这正对应评测里的"不安全改写"指标(§5),而且说明 W 里的校验不只是检查容量账本,还要检查科学约束。

**推想(要论证,不是事实):**

- 旗舰设施(LIGO、Rubin、LCLS、ATLAS)有专门团队,在设计阶段就把改写做成了固定流程。长尾实验和临时组合的跨设施 workflow 没有这种团队,也不会预先写好这些流程。agent 的价值在于:**在运行时、在资源争用出现时**,从 workflow 的描述和设施文档里找出可行的改写,交给确定性求解器和校验器。
- 审稿人会反问:既然设计时人工做就行,为什么要 agent?回应只能靠实验:在 held-out workflow 上,agent 运行时找到的改写,能达到人工设计改写收益的多少,以及"不安全改写"有多少。

**对 X 的表述可以改成**:

> Science data movement requests are not fixed contracts. Real facilities already rewrite them along every dimension: what is sent (LIGO h(t), LCLS veto), at what fidelity (MGARD), by when (Rubin, DIII-D), to where (DIII-D NERSC/ALCF, edge inference), and in what granularity (ATLAS Data Carousel). Each rewrite is hand-built per facility and bounded by science-specific validity conditions. Rule-based network resource managers can only adjust path, rate and start time inside the request. An agent can propose such rewrites at runtime, and a verifier checks both capacity and science validity.



### 仍未核实

- LIGO 的低延迟 / 批量划分出自官方文档和会议幻灯;O4、O5 时期 raw 怎样批量传输,没有找到当前的说明。
- LCLS veto 的"> 10 倍"、gpCAM 的"15% / 12%"、Ocelot 的"90% 以上"都不是从原论文正文里读到的。
- Ocelot 是否已正式发表(会议或期刊),没有查。
- ATLAS Data Carousel 只读了摘要,滚动窗口的细节没有读正文。



### 来源

- [IGWN low-latency data(官方文档)](https://computing.docs.ligo.org/guide/data/lowlatency/)
- [IGWN Computing for O4, O5, and beyond(幻灯)](https://indico.ego-gw.it/event/306/contributions/3064/attachments/1740/3048/IGWN%20Computing%20for%20O4%2C%20O5%2C%20and%20beyond.pdf)
- [LIGO O2 数据集与传输说明(幻灯)](https://dcc-backup.ligo.org/public/0181/G2200571/001/slides.pdf)
- [Thayer et al., Massive Scale Data Analytics at LCLS-II (CHEP 2023)](https://indico.jlab.org/event/459/papers/12502/files/971-Thayer_CHEP2023_v3.pdf)
- [SLAC 2021:LCLS 新数据系统](https://www6.slac.stanford.edu/news/2021-02-17-bigger-faster-more-powerful-slacs-new-x-ray-laser-data-system-will-process-million)
- [Thayer 2024 IFDEPS 幻灯](https://www.bnl.gov/ifdeps/files/talks/janathayer.pdf)
- [Liu et al., Optimizing Scientific Data Transfer on Globus with Error-bounded Lossy Compression (Ocelot)](https://arxiv.org/abs/2307.05416)
- [Liang et al., Error-controlled, progressive, and adaptable retrieval of scientific data with multilevel decomposition (SC '21)](https://www.osti.gov/biblio/1855631)
- [Wu et al., Error-controlled Progressive Retrieval under Derivable Quantities of Interest](https://arxiv.org/abs/2411.05333)
- [Hernandez et al., Data Movement Model for the Vera C. Rubin Observatory](https://arxiv.org/abs/2507.12955)
- [Bechtel Amara et al., Accelerating discoveries at DIII-D with the Integrated Research Infrastructure (Frontiers in Physics 2024)](https://www.frontiersin.org/journals/physics/articles/10.3389/fphy.2024.1524041/full)
- [Kube et al., Near real-time streaming analysis of big fusion data](https://arxiv.org/abs/2108.08896)
- [ITER 2021 技术会议幻灯(KSTAR 时间数字)](https://conferences.iaea.org/event/251/contributions/20635/attachments/11190/16488/ITER_TM_2021_12.pdf)
- [Liu et al., Bridging Data Center AI Systems with Edge Computing for Actionable Information Retrieval (XLOOP 2021)](https://arxiv.org/abs/2105.13967)
- [Borodin et al., ATLAS Data Carousel (CHEP 2019)](https://www.epj-conferences.org/10.1051/epjconf/202024504035)
- [Borodin et al., Updates to the ATLAS Data Carousel Project (CHEP 2024)](https://www.epj-conferences.org/articles/epjconf/abs/2024/05/epjconf_chep2024_01054/epjconf_chep2024_01054.html)
- [Software and computing for Run 3 of the ATLAS experiment](https://arxiv.org/abs/2404.06335)
- [Welborn et al., Streaming Large-Scale Electron Microscopy Data to a Supercomputing Facility](https://arxiv.org/abs/2407.03215)
- [BNL:Automatically Steering Experiments Toward Scientific Discovery(gpCAM)](https://www.bnl.gov/newsroom/news.php?a=218852)
- [Noack 幻灯(gpCAM 数据量数字)](https://www.bnl.gov/nysds21/files/talks/day4/1-marcus-noack.pdf)

---

> 我还想到一个点是,基于 agent/LLM 的系统不一样的点在于,它具有自主性,能够中间不需要人参与地做决策,人只需要。能够独立进化。这个点你觉得呢

(原话"人只需要"后面没写完,下面按"人只需要设定目标和边界"理解。)

**方向对,但这两个词照原样写进论文会被认为不新,需要换一种可测的说法。**

### 1. "自主、不需要人参与"本身不是区别

- **规则系统本来就是自主运行的。** TEMPUS 的调度、BGP 选路、云的自动扩缩容,中间都没有人。"不需要人参与"是自动化的本义,不是 agent 独有的。
- **"自主网络"这个口号早就有了**,而且正是 Mariam 那条线:Feamster 与 Rexford 的 *Why (and How) Networks Should Run Themselves*(2017,凭记忆,未重新核对),Mariam 在 ESnet 的 self-driving network 和 Hecate(DRL 做流量工程,见第一个问答的文献表)。说"我们的系统是自主的",审稿人会问这和 self-driving network 有什么不同。

**真正的区别在于:能自主处理的范围有多大。** 规则系统在预想到的范围内自主;一旦超出(请求不可行、未见过的故障、要和别的域商量),就停下来交给人。前面找到的那些改写(LIGO 拆 h(t)、DIII-D 换站点、LCLS 丢帧)全都是**人**做的。所以可以这样说:

> agent 的自主性不是"没有人",而是**把原本只能升级给人的那部分决策接过来**。

这正好对上 KK 在 9/28 说的升级阶梯:规则处理不了的升级给 LLM,LLM 也处理不了的再升级给人。可测指标是:同一组场景里,**升级给人的比例**和**问题解决耗时**降低多少,同时容量与科学约束的违反次数仍为 0。

另外要注意,合作方社区对"完全不要人"是有戒心的。Confucius 要求敏感操作必须人工批准;LBNL 2026 年 1 月的 user facility agent workshop 推荐"co-pilot"模式,即 agent 提议、人批准关键步骤。所以论文里更稳妥的说法是"缩小需要人的范围",而不是"去掉人"。

### 2. "独立进化"要说清楚进化的是什么

- **如果进化的是参数**(超额分配比例、速率校准系数、RL 的策略权重),这不新。Hecate 的 DRL 和我们图 C 的 calibrate 都是。
- **如果进化的是规则本身**,就和 X 一脉相承,可能是一个真正的点子:**LLM 在运行中处理掉一个规则处理不了的情况后,把这次成功的处理编译成一条新的确定性规则;新规则先在 digital twin 里验证,通过后才放进快速路径。** 下次遇到同类情况,直接由规则处理,不再调 LLM。

这样,升级阶梯会随时间**往下移**:原来要找人的,变成 LLM 处理;原来要 LLM 处理的,变成规则处理。系统越用越"规则化",LLM 调用越来越少。一句话:**agents that write themselves out of the loop。**

**为什么值得考虑:**


| 好处                    | 说明                                                                                                                                                          |
| --------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 回应 LLM 慢、贵、不可复现的质疑    | 慢路径只处理新情况;重复情况走确定性规则,满足 200 ms 的协调指标                                                                                                                        |
| 给 digital twin 一个具体角色 | twin 用来审核新规则能否上线,而不只是演示环境;这是合作方关心的                                                                                                                          |
| 可测                    | 在一串场景上画曲线:LLM 调用率、升级给人的比例、决策时延随时间下降,而交付的 utility 不降、违反次数为 0                                                                                                 |
| 和已有工作有区别              | Glia、Nada、PolicySmith 是**离线**让 LLM 设计策略;Voyager 的技能库、Agent Workflow Memory 积累的是 LLM 自己的经验,不变成确定性规则(这两篇凭记忆,未核对)。"运行时遇到问题、事后编译成规则、经 twin 审核再上线"这个闭环,我没检索过,需要查 |


**风险:**

1. **规则积累会退化。** 规则越来越多、互相冲突,或者对条件过拟合。需要规则的版本管理、冲突检测和淘汰机制。
2. **"进化"难在 6 个月内展示。** 需要足够长、足够多样的场景序列,而且后面的场景要和前面的同类但不完全相同,否则看不出泛化。场景生成本身就是工作量。
3. **审核标准谁来定。** twin 里验证通过,不等于真实网络上也对;Phase 1 的 twin 还不确定。



### 3. 怎样和前面的 X 合成一条主线

> **X(改写问题)回答"agent 能做什么规则做不到的事";自主与进化回答"做过之后怎样变成规则能做的事"。**

合起来,论文的故事是一个三层升级阶梯(规则 → LLM → 人),外加两种移动:

- 遇到规则处理不了的情况,**向上升级**:LLM 改写问题、提出方案,确定性校验后执行;LLM 也处理不了,才找人。
- 处理成功后,**向下沉淀**:把这次改写编译成规则,经 twin 审核后放进快速路径。

衡量方式仍然是第一个问答里的 oracle gap,外加两条随时间变化的曲线:升级给人的比例、LLM 调用率。

我的判断:**"自主"作为口号不新,"缩小升级给人的范围"可测、值得写;"进化"如果落到"LLM 处理过的情况沉淀为经 twin 审核的规则",是我目前觉得除了"offer 带原因"之外第二个像 nugget 的点。** 建议把它补进给 KK 的那一页里,作为 X 的后半段,而不是单独开一个方向。

---

> 你的这个点我觉得很有意思。请你查一下是否被其他论文做了。查的时候不要太乐观也不要太悲观,有些论文虽然想法差不多,但是场景可能会有区别,不要武断下结论。

被查的点子,先写成可比对的形式:

> 运行中遇到规则处理不了的情况 → LLM 处理 → 把这次成功的处理**编译成确定性规则** → 规则**先在 digital twin 里审核**再放进快速路径 → 下次同类情况不再调 LLM;整体表现为升级阶梯(人 → LLM → 规则)随时间往下移。

拆成五个要素,逐一对照:**(a)** 触发来自运行中的新情况;**(b)** 沉淀的产物是不经 LLM 也能执行的确定性规则;**(c)** 上线前有独立审核(twin / 仿真);**(d)** 场景是有硬约束的资源管理控制回路;**(e)** 人也在阶梯上,用升级给人的比例来衡量。

### 1. 结论

- **抽象思想不新,这一点要坦然承认。** 认知架构 Soar 的 chunking(Laird、Rosenbloom、Newell,1986)就是"遇到僵局 → 慢速推理解决 → 把结果编译成新的产生式规则 → 下次不再陷入僵局",和我们的设想几乎同构(凭记忆,未重新核对)。LLM 时代,"从经验中归纳技能、验证后收入技能库"已经是一个有综述的方向:TMLR 2026 的一篇综述审阅了 124 篇论文。
- **在我查到的范围内,没有工作同时具备 (a)–(e)。** 最接近的几篇各缺一两个要素,而且场景不同(审计合规、网页 agent、Minecraft、交换机 CLI 运维、离线算法设计)。
- **所以能不能成为论文,不取决于"这个闭环有没有人提过"(有),而取决于把它放进网络资源管理时,有没有别处没有的技术难题。** 我认为有三个候选(§4),但这是我的判断,需要和 KK 讨论。



### 2. 逐篇对照

✓ = 具备;△ = 部分具备或场景不同;✗ = 不具备;? = 摘要未说明。


| 工作                                                                                                                                                        | 做了什么                                                                                                                           | (a) 运行中触发        | (b) 确定性规则               | (c) 独立审核        | (d) 资源控制回路                 | (e) 人在阶梯上 | 和我们的主要区别                                                                                                                            |
| --------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------ | ---------------- | ----------------------- | --------------- | -------------------------- | --------- | ----------------------------------------------------------------------------------------------------------------------------------- |
| **Trace2Policy**(arXiv 2606.10457,2026 年 6 月,预印本)                                                                                                         | 从专家决策记录里蒸馏出规则文档,按错误类型(缺失 / 错误 / 冲突)迭代修补,每个修补过回归门槛才保留;最后编译成 Python,推理时零次 LLM 调用。物流公司 22 天部署,编译后的 Python 比同内容的 prompt 高 9.8 个百分点 | ✗ 规则来自专家记录,离线迭代  | ✓                       | △ 验证集回归门槛       | ✗ 审计、合规、合同审查               | ✗         | **最接近**。"编译成确定性代码比留在 prompt 里更好"这一点它已经给出证据,我们不能再声称是自己的发现。区别在规则来源(专家记录 vs. 运行中 LLM 的处理)和场景                                           |
| **Agentic Plan Caching**(NeurIPS 2025,Stanford)                                                                                                           | 从完成的 agent 运行中抽取计划模板,新请求按关键词匹配,由小模型改写后复用;成本降约 50%,时延降约 27%                                                                     | ✓ 运行中积累          | ✗ 复用时仍要小模型改写            | ✗               | ✗ 通用 agent 任务              | ✗         | 思路同为"运行中积累、减少大模型调用",但产物不是确定性规则,也没有上线前审核。作者的博客自己也提出"缓存的计划多接近才能安全复用"这个开放问题                                                            |
| **Agent Workflow Memory**(ICML 2025)                                                                                                                      | 从 agent 的历史轨迹归纳出可复用的 workflow,可在线归纳                                                                                            | ✓                | ✗ 产物是给 LLM 用的自然语言流程     | ✗               | ✗ 网页 agent                 | ✗         | 沉淀的东西仍由 LLM 执行                                                                                                                      |
| **Voyager**(2023,凭记忆)                                                                                                                                     | 把成功的行为写成代码技能放进技能库,由环境反馈自我验证                                                                                                    | ✓                | △ 代码,但由 LLM 选择调用        | △ 环境内自检         | ✗ Minecraft                | ✗         | 技能是 LLM 的工具,不是绕过 LLM 的快速路径                                                                                                          |
| **Dynamic Agent Skills 综述**(TMLR 2026,arXiv 2607.10113)                                                                                                   | 审阅 124 篇:从交互收集证据 → 提出技能更新 → 验证并收录 → 生命周期管理                                                                                     | —                | —                       | —               | —                          | —         | 说明"验证后收录的演化技能库"已是成型方向。我们不能把"会进化"本身当贡献                                                                                               |
| **Self-Evolving Defense**(arXiv 2609.36603)                                                                                                               | 从有害的 agent 轨迹中提炼可复用的安全策略,以后检索使用,不改模型权重                                                                                         | ✓                | △ 策略被检索后仍交给 LLM         | ?               | ✗ agent 安全                 | ✗         | 模式相同("从失败中合成可复用规则"),场景不同                                                                                                            |
| **Agentic Router**(arXiv 2608.09184,SONiC 交换机 CLI 运维)                                                                                                     | 把运维经验抽象成可检索的指导;用真实 SSH 执行结果,以 LoRA 更新一个后果预测器                                                                                   | ✓                | ✗ 指导 + 模型权重,决策仍由 LLM 提出 | △ 执行前预测后果、按风险重排 | △ 网络运维,但不是容量与承诺管理          | ✗         | **网络领域里最接近的**;沉淀的是给 LLM 的经验,不是绕过 LLM 的规则                                                                                            |
| **PolicySmith**(HotNets '25)、**Vulcan**(arXiv 2512.25065)、**ADRS / Barbarians at the Gate**(arXiv 2510.06189)、**Glia**、**网络运维的自动启发式设计**(arXiv 2605.28197) | LLM 离线生成并演化策略代码,用模拟器或真实负载评估;PolicySmith 生成的拥塞控制可直接放进 Linux 内核                                                                  | ✗ 由研究者针对固定目标离线启动 | ✓                       | ✓ 模拟器 / 负载      | △ 缓存、拥塞控制、GPU 负载均衡、LDPC 解码 | ✗         | 产物和审核方式与我们一致;**区别在触发方式**:它们是"给定问题、离线搜最优策略",我们是"运行中遇到规则覆盖不到的情况,针对它补一条规则"。ADRS 的作者自己说瓶颈在于"robust evaluation and validation framework" |
| **Aether**(Cisco / Swisscom,arXiv 2604.18233)、**数字孪生增强的 agent 事件响应**(arXiv 2608.02422)                                                                    | 用 digital twin 验证 LLM 提出的网络变更或响应动作                                                                                             | △                | ✗ 验证的是单次动作,不沉淀规则        | ✓ twin          | △ 网络运维                     | △         | twin 当审核者已有先例;我们多出的是"把通过审核的处理变成长期规则"                                                                                                |
| **NetBrain Runbook Companion**(厂商材料)                                                                                                                      | 工程师根据事件经验更新 runbook;动作需人工审核或预先批准                                                                                               | ✓                | △                       | 人工              | △                          | ✓         | 产品里已有"经验沉淀进 runbook",但由人主导                                                                                                          |




### 3. 哪些地方确实没找到

在**网络资源预留与调度**(带宽预留、跨域承诺、截止期传输)里,没找到"运行中遇到覆盖不到的情况 → LLM 处理 → 编译成确定性规则 → twin 审核后上线"的工作。网络领域的近邻要么只沉淀给 LLM 用的经验(Agentic Router),要么只做离线策略搜索(PolicySmith、Vulcan、ADRS),要么只审核单次动作(Aether)。

**这只是检索不到,不是证明不存在。** 局限:

- 只查了约十组关键词,而且大多只读了摘要;
- 很多相关工作是 2026 年的 arXiv 预印本,演进很快,半年后格局可能不同;
- AIOps 方向(自动修复、事件 runbook 学习)和 Soar 之后的经典 AI 文献(explanation-based learning、case-based reasoning)没有系统查。



### 4. 如果要做,技术核心可能在哪里(我的判断,待讨论)

既然闭环本身不新,论文需要回答**这个闭环放进网络资源管理时,哪些问题是别处没有的**。三个候选:

1. **规则的适用范围怎么定。** 一次成功的处理变成规则时,规则的触发条件写宽了不安全,写窄了用不上。Trace2Policy 用缺失 / 错误 / 冲突三类错误迭代修补;Agentic Plan Caching 留下了"多接近才能复用"的开放问题。在我们的场景里,适用范围还受网络状态影响(同样的请求改写,链路空闲时成立,争用时不成立),比文本类任务更难。
2. **规则之间、规则与其他租户之间的相互作用。** 资源管理里,一条规则单独看没问题,和别的规则或别人的流量叠加可能造成超额承诺,或者把别人挤出去。审计、网页 agent、Minecraft 里没有"一条规则的副作用落在第三方身上"的问题。这意味着 twin 审核要在混合负载下做,而不是只回放触发这条规则的那一个场景。
3. **规则会过时。** 网络在变(链路升级、背景流量变化、站点政策改变),去年对的规则今年可能错。这和 10/14 讨论图 C 时发现的问题是同一个:校准不能把故障期的数据当成常态(见 [20261014_networkagent.md](20261014_networkagent.md) §4)。规则需要带上成立条件,条件不再满足时降级回 LLM 或者淘汰。

其中第 2 点我认为最有网络特色,也最能和 W(ledger 作为唯一提交者)接上。

**对外的说法要相应调整:** 不说"我们提出了能自我进化的 agent",而说"我们把 LLM 处理过的情况编译成规则的思想(Soar chunking、Trace2Policy、技能库)用到有硬约束、多租户的网络资源管理上,并解决它在这里特有的 X、Y 问题"。前一种说法会被审稿人用上表直接驳回。

### 来源

- [Trace2Policy: From Expert Behavior Traces to Self-Evolving Decision Agents](https://arxiv.org/abs/2606.10457)
- [Agentic Plan Caching (NeurIPS 2025)](https://neurips.cc/virtual/2025/poster/116166)
- [AgenticCache (MLSys 2026)](https://mlsys.org/virtual/2026/oral/3806)
- [Agent Workflow Memory](https://arxiv.org/abs/2409.07429)
- [Dynamic Agent Skills: A Lifecycle Survey and Taxonomy of Evolving Skill Libraries](https://arxiv.org/abs/2607.10113)
- [Self-Evolving Defense: Continual Security Policy Learning for LLM Agents](https://arxiv.org/abs/2609.36603)
- [Agentic Router: An Execution-Grounded Continual Learning Approach With Memory](https://arxiv.org/abs/2608.09184)
- [PolicySmith: Man-Made Heuristics Are Dead. Long Live Code Generators! (HotNets '25)](https://conferences.sigcomm.org/hotnets/2025/papers/hotnets25-final279.pdf)
- [Vulcan: Instance-Optimal Systems Heuristics Through LLM-Driven Search](https://arxiv.org/abs/2512.25065)
- [Barbarians at the Gate: How AI is Upending Systems Research (ADRS)](https://arxiv.org/abs/2510.06189)
- [Automated Heuristic Design for Network Operations](https://arxiv.org/abs/2605.28197)
- [Aether: Network Validation Using Agentic AI and Digital Twin](https://arxiv.org/abs/2604.18233)
- [Agentic Incident Response through Digital Twin-Enhanced Multiscale Planning](https://arxiv.org/abs/2608.02422)
- [NetBrain AI / Runbook Companion(厂商材料)](https://www.netbrain.com/features/ai/)
- 凭记忆、未重新核对:Laird, Rosenbloom, Newell, *Chunking in Soar: The Anatomy of a General Learning Mechanism*, Machine Learning 1(1), 1986;Wang et al., *Voyager*, 2023

---

> 1. "科学 agent 基础设施(Academy、ORNL 跨设施)把网络当透明管道"我不太理解,请用例子说明,比如就用 Academy
> 2. "网络一侧的工作(Confucius、OFCnetLLM)不了解上层 workflow",我也不理解,请针对这两个系统举例
> 3. "资源管理里,一条规则单独看没问题,和别的规则或别人的流量叠加可能造成超额承诺,或者把别人挤出去",同样举例说明

先说一个修正:回去读了原文,**第 2 点我原来说重了**。Confucius 知道服务名和流量等级(例如 "gold traffic … for Ads storage service"),不是完全不了解上层。准确的说法是:**它知道"这是谁的流量、什么等级",不知道"这份数据为什么要传、什么时候必须到、能不能改"。** 第 1 节原句处已加注。

下面每个例子都分开标注:**论文原文说了什么**,和**我为说明而构造的情景**。

### 1. Academy:网络是"透明管道"是什么意思

**"透明管道"的意思**:上层系统把数据交出去,就假设它会到;不问网络能给多少带宽、什么时候能到,网络也没有渠道告诉上层"这条路现在很挤"或者"你的传输赶不上了"。网络对上层不可见(透明),上层对网络也不提要求。

**论文原文(Pauloski 等,arXiv 2505.05428v3)**:

- agent 之间的消息经过一个 exchange(Redis 队列,或部署在 AWS 上的云端 exchange)投递到各自的 mailbox(§III-D)。
- 大数据不放在消息里,而是传引用:"we pass large values by reference and perform out-of-band data transfers by using ProxyStore"(§III-D4)。ProxyStore 底下可以接 RDMA、UCX、Globus Transfer 或 P2P UDP;实验里用的是 ZeroMQ 和 P2P(§IV-B)。
- MOFA 案例:Assembler、Database、Estimator 跑在 Chameleon Cloud,Generator 和 Validator 跑在 Aurora,Optimizer 跑在 Polaris;agent 之间通过 exchange 传消息协作(图 7)。
- 全文**没有**提到带宽预留、传输截止时间,也没有提到 SENSE、OSCARS 或 ESnet。与网络有关的只有:多路径设计"suitable for dealing with heterogeneous networks"(§III-D2),以及测得的往返时延。

也就是说,Academy 关心的是**数据怎样到达**(选哪种传输协议、直连失败怎么转发),不关心**能不能按时到达**。这对它的目标是合理的,不算缺陷。

**构造的情景**(不是论文内容):

假设 MOFA 的 Generator 在 Aurora 上一批生成了大量候选结构,要交给 Chameleon 上的 Assembler,下一轮生成要等 Assembler 和 Estimator 的反馈。同一时间,另一个 workflow(比如 1000genome)正在 ANL 到 Chameleon 的同一段链路上做大批量传输。


|          | Academy 现在的做法                        | 有 SciNet network agent 时                                                  |
| -------- | ------------------------------------ | ------------------------------------------------------------------------- |
| 传之前      | 不问。ProxyStore 在 Assembler 解引用时才开始拉数据 | 先 quote:这段链路被背景流量占到几点,现在能给多少速率,什么时候能传完                                    |
| 传得慢时     | Assembler 只看到"还没到",只能等               | offer 里写明 `blocked_by`,scheduling agent 可以决定先让 Assembler 处理已到的一部分,或者推迟这一轮 |
| 传输有截止时间时 | 无从表达                                 | 用 reserve / commit 拿到有时间保证的承诺                                             |
| 链路出故障时   | 传输失败或卡住,上层分不清是网络还是主机的问题              | network agent 发 `at_risk`,说明是哪一跳、预计晚多久                                    |


所以"透明管道"不是说 Academy 做错了,而是说**它和网络之间没有对话的接口**,SciNet 的 network agent 恰好可以补上这个接口。ORNL 的跨设施架构我只读了摘要(LLM 接口 + 多 agent 决策层 + 设施 API + 溯源),没看到网络控制,但没有读全文,不能下同样肯定的结论。

### 2. Confucius 与 OFCnetLLM:网络一侧知道什么、不知道什么



#### Confucius(SIGCOMM '25,Meta)

**论文原文**:

- 使用者是 Meta 的**网络工程师**。表 1 的请求例子包括:"Update max capacity for all fibers in NA to X"、"Generate soft drain command for switch X"、"Can you show me gold traffic from region A to B on May 20 for Ads storage service?"
- 容量 what-if 分析里,需求用的是统计聚合:"use 'hose' demand type with p90 percentile run 'cap_planner'"。
- 故障诊断例子:Instagram 的推理请求在某段时间失败,Confucius 依次查主机所在区域和前缀、TCP 重传、NetNORAD 丢包数据、相关 LSP 路径上的网络变更记录(§2.3)。
- 对 drain 这类操作,论文关心的是"prevent introducing packet loss"和避免路由黑洞(§2.4)。

**它知道什么**:哪个服务的流量(Ads storage、Instagram 推理)、流量等级(gold)、拓扑、计数器、变更记录。

**它不知道什么**:某一次传输服务于什么任务、截止时间是几点、晚了价值掉多少、数据能不能缩减或换目的地。这些信息在 Meta 的场景里也不需要:Meta 的流量是持续的服务流量,按等级和 p90 需求做规划就够了。

**构造的情景**:工程师让 Confucius 生成"drain switch X"的命令。Confucius 会检查 drain 之后会不会丢包、会不会出现黑洞。假设 switch X 下午正承载一条 beamline 的分析数据,6 PM 前必须送到;同时承载一份夜间复制,明早前完成即可。

- Confucius 能判断的:drain 之后剩余容量够不够、gold 流量有没有受影响。
- Confucius 判断不了的:**现在 drain 会让 beamtime 的 steering 失效,晚两小时 drain 就没有任何科学损失。** 因为"6 PM""steering"这些语义不在它的数据里。



#### OFCnetLLM(Yoon、Kiran 等,2025)

**论文原文(arXiv 2507.22711)**:

- 部署在 OFC 2025 展会的展区网络(show floor network)。
- 数据:包速率、输入输出错误率、接口规格、flow 数据,约 1340 万条接口数据点和 62.3 万条光层数据点(§4)。
- 工程师通过聊天框查询;功能是汇总接口状态、诊断单个接口、按小时预测流量(§4,图 4、图 5)。
- 论文**没有**说明流量对应哪个应用或用户;§5 提到"each demonstrator was able to have their own agents",说明有按展台划分 agent 的设想,但没有说明流量归属。
- 论文**没有**描述改路由、预留带宽这类动作,只有监测、分析和预测。

**构造的情景**:OFCnetLLM 发现某个接口下午 2 点错误率上升、流量预测会到高峰。

- 它能说的:哪个接口、错误率多少、预计几点到峰值。
- 它说不了的:这个接口后面是哪个展台,3 点是不是有一场必须成功的现场演示,还是只是某人在下载大文件。因此它没法判断这个告警该不该立刻处理、该先保谁。

**小结**:Academy 一侧知道 workflow 但不问网络;Confucius、OFCnetLLM 一侧了解网络,对上层只知道服务名和流量等级。**两边都缺"这次传输的语义"这一层**,这就是 science-aware 网络要填的位置。

### 3. 规则叠加导致超额承诺或挤出别人

下面三个例子**都是我构造的**,用来说明为什么"新规则只拿触发它的那一个场景在 twin 里验证"是不够的。背景:规则是从 LLM 的成功处理中沉淀下来的,单独在 twin 里验证都通过了。

#### 例 A:两条规则被同一个事件同时触发,超额分配的假设失效(超额承诺)

- **规则 1**(从一次 beamline 事件中沉淀):"链路 L2 拥塞、steering 传输 at_risk 时,改为预览立即传、全量推到 18:00–22:00 传。"
- **规则 2**(从一次夜间复制事件中沉淀):"L2 拥塞、复制任务 at_risk 时,推到 18:00–22:00 传。"
- 各自验证时,18:00–22:00 的 L2 都是空的,两条都通过。
- 某天 L2 下午拥塞,**两条规则同时被触发**,两份大传输都挤进 18:00–22:00。

后果分两种情况:

- **账本严格分配时**:不会超额承诺(W 保证),但第二份传输会被拒绝或进入 `at_risk`。规则 2 承诺的"推迟就能完成"落空,于是又要升级处理。
- **按 KK 的设想做超额分配时**(例如允许 1.2 倍):超额分配的前提是各传输的峰值不会同时出现。两条规则由**同一个事件**触发,恰好让需求同时出现。账本允许两份都进来,实际速率不够,两份都超时。

要点:**超额分配假设需求相互独立,而由同一事件触发的规则天然相关。**

#### 例 B:每次多留一点余量,合起来占满链路(挤出别人)

- **规则**(从几次"预留 40 Gbps、实际只跑到 30 Gbps"的经验中沉淀):"给 steering 类传输多预留 20% 余量。"
- 单独看合理:这类传输从此很少超时。
- 但规则会作用于**所有**同类传输。几十个 workflow 都多占 20%,链路上能给其他请求的容量明显变少,其他租户的 quote 越来越多地被拒绝,或者只能拿到更晚的开始时间。
- 每一次决定都"局部合理",合起来是**囤积**。账本里没有超额,问题在别人身上。



#### 例 C:改道到"看起来空闲"的路径,挤占不在账本里的流量(挤出别人)

- **规则**(从一次成功的修复中沉淀):"主路径 MAIN 出问题时,steering 传输改走 ALT(经 esnet-nash)。"
- 验证时 ALT 很空,通过。
- 后来 ALT 上多了另一个机构的大量 best-effort 流量。这些流量不是我们的预留,账本只通过 telemetry 把它们记为背景流量,而且观测有延迟。
- 规则触发,我们的预留流量占到 ALT 上,对方的吞吐大幅下降。我们的账本没有超额,自己的承诺也兑现了,**代价落在第三方身上**。

这个情景在流量工程里并不新:故障后改路,把拥塞转移到别处,是 TE 研究的老问题。我们的新情况是,**改路的规则是自动沉淀出来的,没人专门检查过它对别人的影响**。

#### 这三个例子对审核提出的要求


| 要求                                     | 对应的例子 |
| -------------------------------------- | ----- |
| 在混合负载、多条规则同时生效的情况下验证,不只回放触发规则的那一个场景    | A     |
| 检查由同一事件触发的规则之间的相关性                     | A     |
| 指标除了"我们自己的承诺是否兑现",还要包括其他租户的接纳率、等待时间与吞吐 | B、C   |
| 对每条规则的累积效应设上限,例如全局余量预算                 | B     |


这也是上一个问答里说"第 2 点最有网络特色"的原因:审计、网页 agent 这些场景里,一条规则错了只影响这一次决定;资源管理里,规则的副作用会落在别人身上,而且多条规则会相互放大。

### 来源

- [Pauloski et al., Empowering Scientific Workflows with Federated Agents (Academy), arXiv 2505.05428v3](https://arxiv.org/html/2505.05428v3)
- [Confucius: Intent-Driven Network Management with Multi-Agent LLMs (SIGCOMM '25)](https://minlanyu.seas.harvard.edu/writeup/sigcomm25.pdf)
- [Yoon, Kiran, Ebling, Breen, OFCnetLLM, arXiv 2507.22711](https://arxiv.org/html/2507.22711v1)

---

> LLM 这边暂时这样。你觉得架构方面是否有创新点?不要只看当前实现,请考虑上未来设计(PLAN 里没做的)以及潜在实现。



### 1. 结论

- **单个部件看,几乎都有前人,而且大多在 2003–2014 年的 grid / NSI 时代。** 如果论文写成"我们设计了一个 agent 架构,有 quote / reserve / commit、运行期修复、学习校准",审稿人会认为这是 grid 时代的方案加上 LLM。
- **但有一个架构层面的论点我认为能立住:网络与 workflow 之间的接口(契约)应该长什么样。** 现有接口只有三种:没有接口(Globus、Academy,尽力而为),二元接口(NSI / OSCARS:给一条保证带宽的电路,或者拒绝),价格接口(Pretium)。我们的设计(含 PLAN 里还没做的部分)在接口上有四个特征。每一个单看都有前身,合起来针对的是 grid 时代没有的条件:**承诺是软的、对方是会改写请求的 agent。**
- 另有两个次要候选(commitment-aware telemetry、决策日志 + twin 回放),以及一批不建议当卖点的部件。



### 2. 先列不能声称的部分


| 我们的设计                                   | 前人                                                                                                                                                                  | 说明                                                   |
| --------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------- |
| 网络 + 计算(+ 仪器)的整组原子预留,任一失败整组回滚           | **GridARS**(JSSPP 2007,doi:10.1007/978-3-540-78699-3_9):用两阶段提交协同预留计算与网络,做过日美跨太平洋实验;**HARC**(MacLaren,GADA '07):基于 Paxos Commit 协同预留超算时间与 lightpath(EnLIGHTened 测试床) | 约 20 年前就做过。我们 5a 的 `pending_group` 只是同一思路            |
| reserve → commit 两阶段、出错通知、多域层级聚合        | **OGF NSI CS 2.0**(GFD.212):reserve、reserveCommit、provision,`errorEvent`、`dataPlaneStateChange` 通知,aggregator 负责多域协调;SENSE 建立在这一套之上                                 | 我们的生命周期是它的子集加上 quote                                 |
| 开始时间与速率可变的预留;按"数据量 + deadline"分段定速率     | **Burchard、Heiss、De Rose 2003**(malleable reservation,可变开始时间与速率);**Chen 与 Primet**(arXiv cs/0606076,把一个请求分成多段、各段不同速率)                                               | 我们的三种放置策略(earliest_start / max_rate / min_rate)在这条线上 |
| 多个 offer 给请求方挑                          | **Pretium**(SIGCOMM '16):按数据量和 deadline 报价                                                                                                                          | 见第一个问答                                               |
| offer、counter-offer、运行中重新协商             | **WS-Agreement Negotiation**(OGF 草案,2010):offer 不具约束力,counter-offer 必须落在对方给的约束范围内,支持对已有协议重新协商                                                                       | grid 时代的 SLA 协商已有完整状态机                               |
| LLM 提议、确定性组件校验                          | Confucius、Aether、6G 协商论文                                                                                                                                            | 见第一个问答                                               |
| 在测量预算内,把主动探测放在最可能发现 SLA 违约的地方           | **RFC 8316 及 IRTF NMRG 自治 SLA 违约检测草案**                                                                                                                              | 与下面 §4 的候选 5 最接近                                     |
| 三张图按触发方式拆分、LangGraph、共享存储注入、agent 注册与发现 | 工程选择;agent 发现有 A2A 等协议                                                                                                                                              | 不是研究贡献                                               |




### 3. 主论点:网络与 workflow 之间的契约层

四个特征,以及每个特征对应 PLAN 里的哪一步:


| 特征                           | 内容                                                               | 对应 PLAN                                                 | 最近的前人                                           | 差别                                                                         |
| ---------------------------- | ---------------------------------------------------------------- | ------------------------------------------------------- | ----------------------------------------------- | -------------------------------------------------------------------------- |
| **① offer 带风险**              | 每个 offer 给出 p50 / p95 完成时间,而不是"保证"或"不保证"                         | 第 4 步(字段已有,目前是理想模型);第 9 步校准后才有真实分布                      | NSI / OSCARS:专用电路,硬保证;SWAN、BwE、TEMPUS:运营方控制全部流量 | 我们处在中间:**只控制自己的预留,别人的流量只能观测而且有延迟**(账本分 observed / own 两层就是为此)。承诺只能是带风险的软承诺 |
| **② offer 带原因和反事实**          | 不可行或受限时说明:卡在哪条链路、被谁的流量占(`blocked_by`)、何时释放;"晚 2 小时开始可得 100 Gbps" | 第 4 步(`blocked_by` 已有);反事实未做                            | WS-Agreement 的协商约束:规定 counter-offer 允许的取值范围     | 它告诉对方"可以出什么价",我们告诉对方"为什么不行、改什么能行"。这是 X(请求改写)的输入                            |
| **③ 承诺带可在本地变动的范围(envelope)** | 只要 p95 完成时间不越过承诺,network agent 可以自行换路、换电路、调速率、多路径增容,不惊动上层;越过才上报  | 第 7 步(图 B 本地修复)、第 8 步(多路径)、5a `place_on_circuit` 的 hook | malleable reservation:开始时间和速率可变,但**在预留时**就定下来   | 我们把"本地修复"和"向上重新协商"的分界写进契约本身,运行中由这个范围决定谁来处理                                 |
| **④ 预测性的 at_risk**           | 违约还没发生,但重算的 p95 已越过 deadline 时就上报,附原因与剩余余量                       | 第 7 步(图 B 的 triage)                                     | NSI 的 `errorEvent` / `dataPlaneStateChange`     | NSI 是出事后通知;我们在出事前通知,给 scheduling agent 留出调整的时间。这是 Z(跨层重新协商)的触发点            |


**为什么四个要放在一起讲**:①让请求方知道风险,②让请求方知道怎么改,③让网络自己能处理的事不打扰上层,④让网络处理不了的事尽早交给上层。缺一个,X、Z、W 中就有一个无法落地。论文的架构贡献可以写成:

> 在软承诺、多自治 agent 的条件下,网络与科学 workflow 之间需要一个新的契约层;我们给出它的设计、它保证的性质(W:任何上层行为下账本不超额),以及缺少其中任一特征时会损失什么(消融实验)。

**这个论点成立的前提需要先核实**:①的动机依赖"承诺是软的"。KK 在 9/28 说过这里的 circuit 不是严格电路、更像 ATM、允许超额分配(见 [20260928_llm_responsibility.md](../meetings/20260928_llm_responsibility.md))。但如果 SENSE 在真实 ESnet 上提供的是硬 QoS 保证,背景流量就不会侵占我们的预留,风险主要来自端主机和多域拼接,①的分量会变小。PLAN 待决里 `inclusion_list` 的语义问题也属于这一类。

### 4. 次要候选

**5. commitment-aware telemetry(承诺驱动的观测)**

- 内容:network agent 根据账本告诉 telemetry agent 该看哪里。即将开始、余量小、价值高的承诺经过的链路和时段多采样、多探测;远期、余量大的少采。探测结果直接回写账本,改变后续 offer 的 p95。
- 对应:3a 的观测过期与 `refresh_if_stale`(目前只按过期时间刷新);第 11 步与 SB 的 telemetry agent 对接;10/22 KK 要求的异步事件入口。
- 前人:RFC 8316 和 IRTF 草案是在预算内最大化 SLA 违约的检出概率。差别在于我们按每个承诺的 deadline 余量和价值加权,而且测量结果闭环进入准入决策。新意中等。
- 好处:给 SB 的 telemetry agent 一个有研究味道的需求,两个 agent 的接口有了明确理由。

**6. 决策槽位 + 决策日志 + twin 回放**

- 内容:每个可替换的决策点(triage、本地修复、超额比例、刷新策略、请求改写)都记下输入、输出和出处("every number carries its source",slide 12);事后在 twin 里换成规则、LLM 或 RL 回放同一批输入,做反事实比较;同一套回放也用作新规则上线的审核门(第 4 个问答)。
- 对应:PLAN 第 10 步"与规则版对比";10/22 KK 提的独立验证。
- 前人:Aether(twin 验证单次动作)、ADRS(模拟器评估策略)。差别是把记录与回放做成运行架构的一部分,而不是离线实验。偏方法学,新意中等,但能直接回答"LLM 到底带来了什么"。

**7. 承诺与电路解耦**

- 内容:上层只看到稳定的承诺 ID;底下用哪条电路、是否复用 warm circuit、是否先建后拆(make-before-break)、是否拆到多路径,由 network agent 在 envelope 内自行映射和重映射。
- 是③的实现机制,偏工程,不单独当贡献。



### 5. 建议的论文结构(供和 Mariam、KK 讨论)


| 部分      | 内容                                                                                |
| ------- | --------------------------------------------------------------------------------- |
| 问题      | agentic 科学 workflow 与研究网络之间缺少契约:现有接口要么没有、要么二元、要么只有价格                              |
| 为什么现在需要 | 承诺是软的(共享链路、只能观测别人的流量);请求方是能改写请求的 agent(LIGO、Rubin、DIII-D 等真实改写,见第 3 个问答)          |
| 设计      | 契约层四个特征;ledger 作为唯一提交者;决策槽位                                                       |
| 性质      | 任何上层行为下账本不超额;envelope 内修复对上层透明                                                    |
| 评估      | 消融:去掉①②③④中任一个,看 utility、deadline 命中率、升级次数、对第三方的影响(第 6 个问答的例 A–C)                  |
| 与前人的关系  | 明确继承 GridARS、HARC、NSI、malleable reservation、WS-Agreement、Pretium,说明差别只在契约内容和软承诺条件 |




### 6. 仍需核实

- SENSE 在真实 ESnet 上的预留是硬保证还是软保证(决定①的分量)。
- "带风险的带宽承诺"有没有直接前人:这次没搜到,但只用了一组关键词。下次可查 chance-constrained bandwidth reservation、deadline miss probability admission control。
- GridARS、HARC、Burchard 都只读了摘要和介绍页。
- WS-Agreement Negotiation 是否支持"不可行原因"类的信息,只读了规范摘要和二手说明。



### 来源

- [GridARS(JSSPP 2007,LNCS)](https://dx.doi.org/10.1007/978-3-540-78699-3_9)
- [HARC 介绍(LSU CCT)](https://cct.lsu.edu/research/cyber-advancement/harc)
- [Co-allocation of compute and network resources using HARC(PoS ESLEA 2007)](https://pos.sissa.it/041/016)
- [OGF NSI CS 通知机制幻灯](https://github.com/OpenGridForum/redmine_dmsf_files/blob/main/NS/NSI_CS_Notifications-v28450.pdf?raw=true)
- [NSI 2.0 幻灯(GLIF 2013)](https://www.glif.is/meetings/2013/summer/kudoh-nsi2.pdf)
- [Burchard et al., Performance issues of bandwidth reservations for grid computing (2003)](https://sol.sbc.org.br/index.php/sbac-pad/article/view/34127)
- [Chen & Primet, A Flexible Bandwidth Reservation Framework for Bulk Data Transfers in Grid Networks](https://arxiv.org/abs/cs/0606076)
- [WS-Agreement Negotiation(wsag4j 文档)](https://wsag4j.sourceforge.net/site/wsag/wsag_negotiation.html)
- [OGF WS-Agreement Negotiation 草案](https://xml.coverpages.org/OGF-WS-AgreementNegotiation.pdf)
- [RFC 8316](https://www.rfc-editor.org/info/rfc8316)
- [IRTF NMRG 自治 SLA 违约检测草案](https://datatracker.ietf.org/doc/draft-irtf-nmrg-autonomic-sla-violation-detection/10/bibtex)
- 项目内:[PLAN.md](../other/network_agent/PLAN.md)、[20261014_networkagent.md](20261014_networkagent.md)、[20261022 会议](../meetings/20261022_withkksb_networkagentv1.md)、[20261027 会议](../meetings/20261027_scinet_network_telemetry.md)

---

发paper：

- 科学 agent 基础设施(Academy、ORNL 跨设施)**把网络当透明管道**;网络一侧的工作(Confucius、OFCnetLLM)**不了解上层 workflow**。SciNet 夹在中间,"science-aware" 正好是这个缝。
  - 之前的工作比如Academy是不关心网络，所以只有当产生完数据后才开始传输数据。而有了scinet之后，先quote，能够知道这段链路被背景流量占到几点,现在能给多少速率,什么时候能传完。此外，传的慢、网络出问题，Academy都没法处理。
  - 网络侧的工作比如confucius是: **不知道**某一次传输服务于什么任务、截止时间是几点、晚了价值掉多少、数据能不能缩减或换目的地。
  - AI根据语义来改传什么，传多少，精度，截止日期，传到哪
- **进化规则本身：LLM 在运行中处理掉一个规则处理不了的情况后,把这次成功的处理编译成一条新的确定性规则;新规则先在 digital twin 里验证,通过后才放进快速路径。** 下次遇到同类情况,直接由规则处理,不再调 LLM。系统越用越"规则化",LLM 调用越来越少。
  - 三层升级阶梯(规则 → LLM → 人),外加两种移动:
    - 遇到规则处理不了的情况,**向上升级**:LLM 改写问题、提出方案,确定性校验后执行;LLM 也处理不了,才找人。
    - 处理成功后,**向下沉淀**:把这次改写编译成规则,经 twin 审核后放进快速路径。
  - 需要考虑的点
    - **规则的适用范围怎么定。** 一次成功的处理变成规则时,规则的触发条件写宽了不安全,写窄了用不上
    - **规则之间、规则与其他租户之间的相互作用**
      - 资源管理里,一条规则单独看没问题,和别的规则或别人的流量叠加可能造成超额承诺,或者把别人挤出去
    - **规则会过时。**
      - 网络在变(链路升级、背景流量变化、站点政策改变)
      - 校准不能把故障期的数据当成常态
      - 规则需要带上成立条件,条件不再满足时降级回 LLM 或者淘汰。
- 小的点
- 架构上，接口层是贡献，整个组织架构也作为小的贡献

