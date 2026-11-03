# Network Agent 实现计划

逐步实现:每一步 = 一小块代码 + pytest + 讲解,用户看懂后再进入下一步。
运行测试:`.venv/bin/python -m pytest src/lib/network_agent/tests`

设计来源:`resources/slides/Agent Orchestration.pptx`、`resources/notes/20261014_networkagent.md`(三张图)、
`resources/meetings/20261015_network_agent_prototype.md`(与 KK 的修订)。

## 来自 10/15 会议的修订

| 会上的意见 | 代码里怎么落实 |
|---|---|
| `hold` 改叫 `reserve`(KK) | 代码统一用 `reserve`,注释对应 slides 的 `hold` |
| accept 之后容量在哪里扣减 | ledger 独立成模块,pending → confirm / rollback 显式写回 |
| validate 失败没有出口 | validate 失败直接 `respond(error)` → END |
| deviation 包括拥塞、逐渐变慢,要找出哪一跳 | 拓扑和 ledger 按单条链路建账(不按 slide 23 的 (src,dst) 对) |
| 多路径增容(path1 50 → 需要 100,加 path2) | 单独一步(第 8 步) |
| learning 先归因再校准,保留历史 | 图 C 顺序:join → attribute → calibrate |
| 工具和小 agent 可被多张图复用 | 逻辑写在普通模块里,图节点只做编排 |

## 来自 10/22、10/27 会议的修订

| 会上的意见 | 代码里怎么落实 |
|---|---|
| `foreign_traffic` 改叫 `background_traffic`(KK) | ✅ 2026-10-30 全包改名(schema 的 `blocked_by` 取值、`MockNetwork.add_background`、测试与 demo) |
| 代码和测试同出一个 agent,缺独立验证(KK) | 留作之后的任务(见待决) |
| 扩展点要写明(priority、重新分配、抢占、接真实输入) | 5a 在对应节点的英文 docstring 里标 hook。priority 的实现已列入第 7 步(2026-11-02) |
| 对外不要把 quote demo 说成已有 hold/commit | 5a 补上 reserve/commit |

## 5a 对原图 A 的偏离(2026-10-30 用户确认)

原图让 hold/commit/modify/release 共用 `validate_op → recheck → place_on_circuit → compile_intent → ledger_pending → sense_call → confirm/rollback`,对不上 SENSE 两阶段流程,改为 reserve、commit 两条分支:

- 选 circuit、编译 intent 挪到 reserve:SENSE propagate(即 hold)就要完整 intent,commit 只需实例 id。
- recheck 放在 reserve、账本预扣之前(slide 23 原为 commit 前复查)。
- commit 失败不回滚账本:SENSE 侧仍是 reserved,可重试;只有 reserve 失败才回滚。
- 一个 offer ↔ 一个 commitment ↔ 一个新 SENSE 实例;整组 reserve 原子(任一失败则取消已 propagate 的实例、整组回滚)。
- modify / release / TTL 自动回收 / 幂等留到 5b。

## 步骤与进度

| # | 内容 | 产出 | LangGraph | 目标 | 状态 |
|---|---|---|---|---|---|
| 0 | 环境与骨架:venv、依赖、包结构、参数加载 | `config.py`、`tests/test_step0_smoke.py`、`env/pip/` | 否 | 10/20 前 | ✅ 2026-10-17 |
| 1 | 消息 schema(仅 planning 闭环):TransferRequest、QuoteRequest/Response、Offer、Reserve/Commit 请求与回执、Commitment、EndpointBinding、ErrorResponse。其余消息在首次用到的步骤再加 | `schemas.py`、`tests/test_step1_schemas.py` | 否 | 10/20 前 | ✅ 2026-10-18 |
| 2 | 拓扑与容量账本:站点/链路/路径;逐链路逐时间槽 observed/own/available;pending/confirm/rollback 事务 | `topology.py`、`ledger.py`、`tests/helpers.py`(demo 拓扑:slide 3 物理网络 aps-beamline-8id─anl-n01─anl-n02─esnet-atl─esnet-chi─ornl-n01,外加虚构的 esnet-nash 绕行;2026-10-21 按 slide 3 修订)、`tests/test_step2_topology_ledger.py`;config 加 `max_paths` | 否 | 10/20 前 | ✅ 2026-10-18 |
| 3a | Telemetry 一侧:模拟网络(他人占用、链路中断)、TelemetrySource 接口与 mock、LinkSample schema;账本改为 `apply(samples)` 写入 observed,观测值带过期时间 | `sim.py`、`telemetry.py`、`tests/test_step3a_telemetry.py` | 否 | 10/20 前 | ✅ 2026-10-19 |
| 3b | SENSE 一侧:SenseAdapter 接口(两阶段 propagate → commit,cancel;modify 移到 5b)与 mock(对照模拟网络准入、VLAN 分配、可注入失败);模拟网络分开存"他人占用"与"我们的预留";schema 补 Terminal、ServiceIntent、ServiceState | `sense.py`、`sim.py`、`tests/test_step3b_sense.py` | 否 | 10/20 前 | ✅ 2026-10-19 |
| 4 | 图 A quote 分支:validate_bundle → refresh_if_stale → find_placements → estimate_finish → respond;复现 slide 7 的 a1/a2/a3。放置搜索三条规则(earliest_start / max_rate / min_rate);RateModel 接口(第一版 Ideal);共用 context;config 加 `rate_step_gbps` | `graphs/protocol.py`、`placement.py`、`estimate.py`、`context.py`、`tests/test_step4_quote_graph.py` | 是 | 10/20 前 | ✅ 2026-10-20 |
| 5a | 图 A reserve/commit(2026-10-30 定稿,偏离原图,见下节):route_verb 分发 quote / reserve / commit;reserve = validate_reserve → recheck_capacity → place_on_circuit → compile_intent → ledger_pending → sense_propagate → record_reserve / ledger_rollback → respond;commit = validate_commit → sense_commit → ledger_confirm / (失败不动账本) → respond。分 3–5 部分写,每部分经用户审阅再继续 | `graphs/{protocol,quote,reserve,commit,common}.py`、`circuit.py`、`context.py`、`tests/test_step5a_{reserve,commit,demo}.py`(demo:`python -m <包路径>.tests.test_step5a_demo test1`…`test4`);图 `resources/other/network_agent/protocol_graph_a.html`(及 `visuals/`)同步 | 是 | 10/20 前 | ✅ 2026-11-01 |
| 5b | modify/release(含 SENSE modify)、TTL 到期回收、重复请求幂等;一并收尾 5a 遗留(孤儿实例重试 cancel、quote 有效期与 offer_book 清理、`sense.state()` 的 KeyError)。分 A–D 四部分写 | `graphs/{release,modify,protocol}.py`、`reclaim.py`(release 与到期回收共用)、`schemas.py`、`sense.py`、`ledger.py`、`context.py`、`config.py`(加 `quote_ttl_seconds`)、`tests/test_step5b_{release,sweep,modify,idempotency,demo}.py`(demo:`python -m <包路径>.tests.test_step5b_demo test1`…`test5`;五种消息各走一遍正常路径:`python -m <包路径>.tests.test_step5b_final_demo`);demo 的打印逻辑从 5a demo 提炼进 `tests/printing.py`;设计与实现记录见 `resources/notes/20261101_build_step5b.md`;图 A html 同步 | 是 | 可延后 | ✅ 2026-11-01(A–D 全部写完,172 个测试通过;B–D 应用户要求连续写完,未逐部分审阅) |
| 7 | 图 B Runtime:区分故障/拥塞/渐慢 → 逐跳扫描 → triage → 本地修复(复用第 5 步指令)→ repaired / at_risk;跨 workflow 按 priority 重新分配 / 抢占(来自 10/27 会议:先有一个 transfer、再来一个,按 priority 决定分配,会上的 60% / 40% 只是举例;让 `TransferRequest.priority` 真正起作用,目前无人读),见待决「跨 workflow 按 priority 预留」 | `graphs/runtime.py`;`circuit.py`(`place_on_circuit` 的 priority / preemption hook),可能还有 `schemas.py`(被抢占方的通知消息) | 是 | 之后 | |
| 8 | 多路径增容:找额外路径、拆分速率、增补方案;transport 侧留接口 | `multipath.py` | 是 | 之后 | |
| 9 | 图 C Learning:join_records → attribute_cause → calibrate(带状态标签)→ plan_adjustments → apply | `graphs/learning.py` | 是 | 之后 | |
| 10 | 第一个 LLM 接入点(可替换 policy 后):有证据的诊断 + 选下一次 probe,与规则版对比 | `policies/` | 是 | 之后 | |
| 11 | 与 Mininet / Telemetry Agent(另一位同学)对齐真实接口 | adapter | — | 之后 | |
| 12 | bundle 联合报价:quote 时给出经联合验证、能同时成立的 offer 组合(bundle plan),`admissible` 按 plan 判断;需改 `QuoteResponse`,先与 scheduling agent 对齐接口。见待决「同一 bundle 内各传输的 offer 相互冲突」 | `graphs/quote.py`、`placement.py`、`schemas.py` | 是 | 之后的版本(2026-11-01 用户决定) | |
| 13 | 端到端 demo(原第 6 步,2026-11-02 用户决定移到最后,编号改为 13,其余步骤编号不变):mock scheduling agent 驱动 quote → 选 offer → reserve → commit,两个 workflow 争用,打印 ledger 表(走 `run_experiment.py`)。输入用 1000genome trace(`external/SciNetGenesis/workflows/example_workflows/1000genome-chameleon-2ch-100k-001.json`,WfFormat 1.6:52 task、64 文件、约 2.4 GB),由一层转换生成 `TransferRequest` | `configs/` + `src/experiments/{tag}/`(含 trace → TransferRequest 转换) | 是 | 10/20 展示 | |

## 待决

- slide 7 的 a1 算术疑似笔误:50 TB 以 40 Gbps 自 09:00 起传需 10000 s,应在 11:47 完成,slide 写 13:47(a2 = 13:07、a3 = 14:34 均吻合)。第 4 步已按算术复现(11:46:40),待与 slides 作者确认。
- 估计完成时间目前用 IdealRateModel(实际速率 = 预留速率)。第 9 步换成校准模型后,若实际慢于预留,p95 会超出预留时段,placement 届时要按 p95 速率定预留时长。
- 跨路径去重(`find_placements` 里的 `dedupe`)以 `(start, gbps)` 为 key、保留短路径,前提是完成时间只由 (start, gbps) 决定(IdealRateModel)。第 9 步若 RateModel 按路径给出不同 p50/p95,需把去重挪到 `estimate_finish` 之后,key 改为 scheduling agent 实际看到的 `(start, gbps, p50, p95)`,否则可能删掉 p95 更好的方案。另:key 不含 `blocked_by`,同 key 时保留短路径的 `blocked_by`(slide 7 中 MAIN 为 background_traffic、ALT 为 None)。
- 被跨路径去重的方案可作 reserve 时的备选路径:主路径在 quote 之后被占满时,换路兑现同一个 offer,对 scheduling agent 透明。需要 `offer_book` 改为 offer_id → 方案列表;在 5a 设计 `recheck` 时决定是否采用。→ 5a 不采用,只在 `place_on_circuit` 标为 hook。
- 账本的 origin 还不会随时间推进(slide 23 的 advance the frontier);目前靠 horizon 足够长撑着,第 13 步 demo 若跑过一天需要补上。
- ~~`offer_book` 只增不删~~ 5b 已解决:`sweep_expired` 删掉过期 quote 的 offer,quote_id 记进 `expired_quotes`,之后 reserve 返回 `expired`。commit 需要的 transfer 信息改存在 `ReservedOffer.request`,不再查 offer_book。
- ~~observed 口径~~ 已在 3a 定为接口契约:observed = 不算我们自己预订时的可用容量(`schemas.LinkSample`)。接真实 SENSE / telemetry 时,由其 adapter 负责换算(例如 SENSE `maxReservableGbps` 若已扣掉我们的预留,需加回)。
- SENSE 的 `path_tprofile.inclusion_list` 语义待确认(Exp2 遗留问题):mock 把它当作强制路径;若真实 SENSE 只当偏好、实际走了别的路径,逐链路账本会与实际不符。
- 一个 ServiceIntent 只有一个带宽值;多段速率的 commitment 怎么落到 intent/circuit 上(拆成多个 intent、取最大值,或复用 warm circuit),在 5a 的 place_on_circuit / compile_intent 决定。→ 5a:目前 offer 都是单一恒定速率,一个 offer 编译成一个 intent;多段速率到出现时再定。
- mock SENSE 的 VLAN 池是全局一个,真实情况是每个端点各有可用 VLAN,两端需同时空闲。
- 路径枚举目前穷举所有无环路径,只适合 demo 规模;拓扑变大后换 Yen k 最短路径。
- 第 13 步 1000genome trace → `TransferRequest` 的转换规则待定:trace 是 Pegasus 在单机(pegasus-5)上跑的,没有站点信息,需自行决定 ① task / 文件放到哪个站点(哪些依赖边变成跨站点传输,src/dst 对应拓扑哪个节点);② 时间窗口如何由 task runtime 与 DAG 依赖推出;③ 数据量是否按比例放大(原始约 2.4 GB,在 100 Gbps 链路上不到 1 秒,争用不明显);④ "两个 workflow 争用"是两份 1000genome 还是 1000genome + helloworld-forkjoin。
- 第 13 步 demo 走入口时需要一个实验 tag,届时 `docs/current_experiment_plan.md` 需从 Exp2 切换(换实验由用户决定)。
- 独立验证(10/22 KK 的意见):由一个只看协议规格、不看实现的 subagent 写黑盒测试,再拿实现去跑。2026-10-30 用户决定留作之后的任务,5a 不做。
- reserve 时 offer 的开始时间可能已过:最早开始的 offer 就从 quote 的 now 开始,scheduling agent 隔几秒再 reserve,开始时间就已经过去了。5a 的做法:只有 offer 整段时间都已过去(`end <= now`)才拒绝(`expired`),否则照 quote 时的 [start, end) 原样预扣,传输晚开始就晚结束、可能略超出预留时段。根治办法是 quote 带有效期,或 reserve 时把开始时间顺延到 now,放到 5b 和 TTL 一起定。→ 5b:quote 带有效期 `valid_until`(`quote_ttl_seconds`),开始时间最多晚一个有效期;不做顺延。测试里有效期设为 900 s 而非设计时说的 120 s,因为 5a 有测试要在 09:10 reserve(等观测过期)。
- 5a 实际代码组织:三条分支各一个文件 `graphs/quote.py`(第 4 步的代码,2026-11-01 按用户建议从 protocol.py 拆出)、`graphs/reserve.py`、`graphs/commit.py`,`graphs/protocol.py` 只剩入口 `route_verb` 与合图;placement → intent 在 `circuit.py`;刷新过期观测抽成 `telemetry.refresh_stale`(quote 与 reserve 共用);账本加 `pending_group`(整组原子预扣)。`build_protocol_graph()` 把三条分支(各自是子图)合成完整的图 A;条件边 `on_error` 放在 `graphs/common.py`。`ReservedOffer` 在 C 部分加了 `placement` 字段(实际预订的 placement,commitment 的速率取自它)。commit 失败不回滚;重试时跳过 SENSE 已 committed 的实例,所以组内中途失败后重试是安全的。
- 5b 新增的已知空白:① 幂等缓存 `ctx.answered` 在 agent 生命周期内只增不删,按重试窗口清理留作 hook;`expired_quotes` 同样只增(只存 id)。② 回收是惰性的:长时间没有消息进来时不会回收,真实部署需要定时器调用 `reclaim.sweep_expired`。③ modify 只接受单段速率(一个 circuit 一个恒定速率);已开始的项不能移动开始时间。④ 孤儿实例(reserve 回滚时 cancel 失败)现在保留其 booking 直到 sweep 成功 cancel,与 release 的"cancel 失败不退账本"一致;这改变了 5a 的行为(原来立即退还)。
- 同一 bundle 内各传输的 offer 相互冲突(2026-11-01 用户发现):`find_placements` 对每条传输各自对着同一份账本搜索,没有把同组其他传输算进去,所以 offer 两两组合不一定能同时成立(slide 7 场景中 q1/T1/1+q1/T2/1、q1/T1/2+q1/T2/2 都因同一时间槽争用而 reserve 失败,q1/T1/2+q1/T2/1 可行)。这不是有意设计,是第 4 步遗留的空白。目前的兜底是 reserve 时 `pending_group` 整组原子检查,冲突时返回 `conflict`,不会超订;但 scheduling agent 看不到路径和链路容量,自己判断不了哪些组合冲突,只能反复试。另外 `admissible` 也是逐条传输判断的,all_or_nothing 下可能报"可接纳",实际却没有任何可行组合。修法待用户决定。2026-11-01 用户决定留到之后的版本解决,已列为第 12 步;方案草案(按条件重新搜索、返回若干根到叶的 bundle plan,而非整棵树)见 `resources/notes/20261028_build_step5a.md` 末尾两条问答。
- 跨 workflow 按 priority 预留(并入第 7 步 Runtime,2026-11-02 用户决定:按优先级重新分配、抢占是运行中的调整,属于 runtime 的工作):出处是 10/27 会议记录 2.3–2.4 节;按 priority 分配的场景在记录里未写明提出者,Harvey 的主要建议是把通向 priority / reallocation / preemption 的 hooks 记下来,KK 认可三者为下一步,但未定顺序、算法与日期。开工前要定:① 触发时机——高优先级请求到来时容量不够,或运行中容量下降(故障、拥塞)时,图 B 按 priority 决定先保谁、让谁缩小或让出;quote / reserve 是否也要读 priority(例如 quote 时就按份额分)另定;② 抢占的对象只限未 commit 的预订,还是也包括已 commit 的(要用 5b 的 modify 缩小或 release 让出,且须通知被抢占的 scheduling agent,需要新消息,或与图 B 的 at_risk 共用);③ 与 scheduling agent 的分工——跨 workflow 的取舍由 scheduler 汇总后再请求(10/27 记录 2.6 节),还是由 network agent 按 priority 裁决;④ 与第 12 步 bundle 联合报价的关系(同一 bundle 内也有 priority 之分)。
