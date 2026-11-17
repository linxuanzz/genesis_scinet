## A 部分：输入与检测（2026-11-07）

**改动位置**


| 文件                     | 改了什么                                                                                                                                                                                                                                                                                                                                                       |
| ---------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `schemas.py`           | 新增**临时** schema（未与 telemetry agent 对齐，文件里标了 PROVISIONAL）：`FlowProgress(flow_id, started_at, bytes_sent, sampled_at, source)`；`TelemetryAlert`，六种 kind，公共字段按第九节，`end` 可为 None（链路还没恢复时不知道何时结束），测得值和阈值命名为 `measured_gbps` / `threshold_gbps`；`Subscribe(kind, targets, threshold_gbps, min_duration_seconds, start, end)`，只定义、未接通；`Tick`；`RuntimeEvent = Tick |
| `sim.py`               | `start_flow(instance_id, at, nbytes)`：WMS 在 `at` 开始传，晚于预留开始就是"晚开始"；`add_slowdown(instance_id, start, end, factor)`：链路以外的系数；`flow_trace(instance_id, until)`：我们所有的流一起模拟，返回速率分段、已传字节、完成时间                                                                                                                                                                    |
| `telemetry.py`         | `FlowSource` 协议（临时）与 `MockFlows`（读 `flow_trace`）；`MockAlerts.poll(subscriptions, now)`：从模拟网络生成六类告警；`refresh_stale` 加参数 `force`：告警涉及的链路即使观测没过期也重新拉取                                                                                                                                                                                                         |
| `ledger.py`            | `Observation` 加 `up`（默认 True），`apply` 写入；同一槽内 0 容量的 up 样本和 down 样本并列时取 down。用来区分 link_down 和 congestion                                                                                                                                                                                                                                                    |
| `placement.py`         | `bytes_at(gbps, seconds)`、`gbps_of(nbytes, seconds)`：速率与字节互换，sim、telemetry、deviation 三处共用                                                                                                                                                                                                                                                                  |
| `context.py`           | `AgentContext` 加 `flows: FlowSource`（必填）和 `progress_seen`（每条流上一次读到的进度）；新增 `Committed(commitment, reserve_id, item)` 和 `committed()`：列出仍持有的 commitment 及其背后的预订项（路径、booking、SENSE 实例、请求）                                                                                                                                                                     |
| `config.py`            | 新增 `progress_lag_tolerance`（0 ≤ x < 1）；测试里是 0.05                                                                                                                                                                                                                                                                                                           |
| `deviation.py`（新）      | 检测逻辑：`detect(ctx, event, now) -> Detection`；数据结构 `Deviation`、`SlotDamage`；小函数 `due_bytes`、`is_behind`、`recent_rate`、`damaged_slots`、`watched`                                                                                                                                                                                                              |
| `graphs/runtime.py`（新） | `build_runtime_graph()`：`START → classify_event ─无偏差─► END / ─有偏差─► deviation_found（占位）→ END`                                                                                                                                                                                                                                                              |
| `tests/helpers.py`     | CFG 加容差；`make_ctx` 带上 `MockFlows`；新增 `make_committed_ctx(net, *offer_ids)`、`runtime(ctx, event, now)`                                                                                                                                                                                                                                                      |
| `__init__.py`          | 模块清单补上 deviation.py、graphs/runtime.py                                                                                                                                                                                                                                                                                                                      |
| 图 B html（两个）           | classify_event 的说明改成与代码一致（见下"html"），标题注明 classify_event 已写                                                                                                                                                                                                                                                                                                 |


**mock 怎么算流的进度**

- 某时刻一条流的速率 = min(预留速率, 每一跳留给它的) × 该流的 slowdown 系数。
  - 一跳留给我们的 = 容量 − 背景流量。如果比这一跳上我们所有活跃流的预留速率之和还少，就按预留速率等比例分。
  - 链路中断，或者时间在预留 [start, end) 之外，都给 0：circuit 不存在时不能传。
- 只有已开始、未完成的流参与分配。一条流传完时，重新计算其余流的速率，因为它让出了容量。
- 各段速率按时间积分得到已传字节，最多到总字节数。
- `started_at` 取第一个字节传出的时刻，不是 `start_flow` 的时刻：流在预留开始前就启动，或者一开始就碰上中断，都要等真正有字节传出。

**classify_event 的规则**（`deviation.detect`）

1. 看哪些 commitment：
  - tick：全部；
  - 链路告警：路径经过该链路的。`link_id` 可以是有向 id，也可以是物理 id（两个方向都算）；
  - flow 告警：`circuit_id == flow_id` 的那一条。
  - 已传完的（`bytes_sent >= request.bytes`）不检查。
2. 刷新观测，复用 `refresh_stale`，每个 commitment 的时段是 [实际开始，没开始就是 now, 预留结束)。tick 只刷新过期的。告警涉及的链路强制重新拉取：链路告警刷新那条链路，flow 告警刷新这条流的整条路径。
3. 流级：`due_bytes` = rate_profile 在 [started_at, now) 上的积分，最多到总字节数；没开始就是 0。`due − sent > 容差 × due` 才算落后，正好等于容差的不算。
4. 链路级：这个 commitment 的 booking 占的每个槽里，某一跳 `not up` 或 `observed < own`，就记一条 `SlotDamage`。
  - 当前和以后的槽（槽结束 > now）：受损就算偏差，不管流是否落后，这样也覆盖还没开始的 commitment。
  - 已经过去的槽：只在流落后时用来定位，不单独算偏差。所以已经过去、且被容差吸收了的拥塞不报；传输开始之前的槽根本不看。
5. 一个 commitment 最多一条 `Deviation`，cause 取最严重的那个：有 down 的槽 → `link_down`；否则有受损槽 → `congestion`；只是落后、各跳都正常 → `unlocated`。`links` 是所有受损的跳，按路径顺序排列。
6. 每读一次进度就记进 `ctx.progress_seen`，用上一次读数算 `recent_gbps`（real_rate），供 B 部分判断问题还在不在。
7. 收到格式错误的事件不丢弃，按 tick 处理（全部检查），原因记在 state 的 `invalid_event`。

**与第九节的关系**：没有偏离，有四处补充：

- 告警强制刷新（`refresh_stale(force=)`）：观测还没过期时，只刷新过期的就看不到告警说的变化；
- 账本观测带 `up`：否则中断（observed = 0）和"拥塞到 0"分不开；
- 过去的受损槽只用来定位；
- 格式错误的事件按 tick 处理。

另外发现一个设计空白，记进了 PLAN 待决：传输晚开始时不算偏差，但预留结束时它还没传完，剩下的字节没有预留覆盖；图 B 只在有偏差时才往下走，这种情况目前没人管。

**html**：节点和条件与图 B 一致，没有增删。classify_event 的说明原来只写了流级比较，现在补上链路级（"或某个以后要用的槽里有一跳 observed < own"）和刷新规则（告警的链路强制刷新，其余只刷新过期的）。`runtime_graph_b.html` 的 srcdoc 已按 `html.escape(quote=True)` 整段替换。占位节点 `deviation_found` 是临时的，没有画进图里。

**测试**

- `tests/test_step7_flows.py`（28 个）：
  - 进度：没开始、全速、晚开始、只在预留时段内传、拥塞 / 中断 / slowdown 分段、两条流按预留比例分且一条传完后另一条提速、传完封顶、错误输入、`MockFlows`；
  - 告警：链路状态变化只推一次、容量低于阈值（指定时段 / 当前时刻）、flow_below_rate → flow_stalled → flow_finished；
  - schema 校验：alert、subscribe、FlowProgress、RuntimeEvent 解析；容差超出范围时 config 报错。
- `tests/test_step7_classify.py`（20 个）：
  - 三种 cause：正常 → END、中断、拥塞、unlocated，中断与拥塞同时出现时报 link_down；
  - 链路级：正在跑的传输前方有中断、还没开始的 commitment 前方拥塞、已过去且被吸收的拥塞不报；
  - 晚开始不误报（含传输开始前的中断），`due_bytes` 从实际开始算；
  - 容差边界：正好 5% 不算、6% 算、4% 不算，容差取自 config；
  - 入口：已传完的不检查；tick 只刷新过期的而告警强制刷新（同一个中断，tick 看不到，link_down 告警看得到）；告警按链路 / flow 选 commitment，物理 id 两个方向都算；`MockAlerts` 生成的告警以 dict 形式送进图 B；格式错误的事件按 tick 处理；两次读数算出 recent rate。

共 220 个测试全部通过（新增 48 个，原有 172 个不变）；没有未使用的 import，代码中没有中文，私有信息检查通过。

---



## 留给 B 部分的接口

**图**：在 `build_runtime_graph()` 里把占位节点 `deviation_found` 换成 `scan_path`，条件边 `after_classify` 不用改。

**state**（`RuntimeState`，classify_event 写入）：


| 字段                            | 内容                   |
| ----------------------------- | -------------------- |
| `deviations: list[Deviation]` | 每个有偏差的 commitment 一条 |
| `parsed`                      | 解析后的事件               |
| `checked`                     | 看过的 commitment id    |
| `refreshed`                   | 拉取过观测的链路             |
| `invalid_event`               | 只在事件格式错误时有           |


`Deviation`（`deviation.py`）：


| 字段 / 属性                          | 给 scan_path 的用处                                                                                                                                                                               |
| -------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `committed: Committed`           | `.commitment`（id、rate_profile、circuit_id）、`.reserve_id`、`.item`（`placement.path` / `end`、`booking_id`、`instance_id`、`request.bytes` / `window.latest_finish` / `priority`）：重算与修复要的全在这里，不用再查账本 |
| `cause`、`links`                  | DeviationReport 的 cause 与 links；去重键 (commitment, cause)                                                                                                                                       |
| `damage: tuple[SlotDamage, ...]` | 每个受损槽：`link_id`、`start` / `end`、`observed_gbps`、`own_gbps`、`up`。可用来算"受损链路剩下的容量"（未来速率），以及修复第 2 步要的"未受损时段"                                                                                      |
| `progress: FlowProgress`         | `started_at`、`bytes_sent`、`sampled_at`                                                                                                                                                        |
| `due_bytes`、`lag_bytes`、`behind` | 落后多少、流级信号是否触发                                                                                                                                                                                 |
| `remaining_bytes`                | 总字节 − 已传                                                                                                                                                                                      |
| `recent_gbps`                    | 两次读数之间的速率，None 表示没有上一次读数；用来判断"问题还在不在"                                                                                                                                                         |


**context**：

- `ctx.committed()`：列出所有仍持有的 commitment，返回 `Committed`。scan_path 找"同一受损链路上的其他 commitment"时可以直接用；
- `ctx.progress_seen`：每条流上一次的读数；
- `ctx.rate_model`：算 p50 / p95。

**B 需要先决定的**：第二节的设计空白，即晚开始、预留结束时还没传完的传输，要不要也算作偏差、进入 scan_path。

---


> 对于schemas.py:
> 1. flowprogress中，bytes_sent / (sampleat-startat)就是速度吗？在哪比较了flowprogress和理论进度来判定低于flow_below_rate？flow_below_rate的阈值在哪设置的？
> 2. TelemetryAlert中的start和end是啥意思？这个间隔是固定的值吗？
> 3. “a directed link id, or a physical one (both ways)”，什么叫both way？难道不是二选一吗？不就是directed link吗，怎么还模棱两可的？
> 4. TelemetryAlert中的meausred和threshold只有gbps, 是因为现在的alertkind只需要gbps，不需要延迟、丢包率之类的信息？那如果是link_down/link_up/flow_finished/flow_stalled，那这两个值都是0？link_up为啥属于alert，这不是正常状态吗？
> 5. subscribe和telemetry alert的关系是什么？我以为前者会包含后者？subscribe是怎么被使用的？
> 6. "RuntimeEvent = Annotated[Tick | TelemetryAlert, Field(discriminator="kind")]   # what starts graph B
> RUNTIME_EVENT: TypeAdapter[Tick | TelemetryAlert] = TypeAdapter(RuntimeEvent)"没看懂这两段代码
> 7. DeviationReport中，lent_to是啥？被借的、低优先级的commit吗？为什么已经有了commit id还要有commitment？

**1. 那是平均速率；`flow_below_rate` 由 telemetry 判断，阈值现在没有人设**

`bytes_sent / (sampled_at − started_at)` 是**从开始到现在的平均速率**，不是当前速率：中间停过 15 分钟，也会摊进平均里。当前速率要用两次读数之差，即 `deviation.recent_rate(prev, cur)`，读数存在 `ctx.progress_seen`。平均速率只在 unlocated、且没有上一次读数时，作为退路拿来封顶预测（`forecast.off_path_cap`）。

"低于阈值"不是 network agent 判断的，分工如下：

| 谁 | 做什么 | 代码 |
|---|---|---|
| telemetry（mock 里是 `MockAlerts`） | 在最近 `min_duration_seconds` 的窗口里算吞吐，低于 `threshold_gbps` 就推 `flow_below_rate` | `telemetry.MockAlerts._conditions`：`gbps = (已传 − 窗口开始时已传) / 窗口长度`，再和 `sub.threshold_gbps` 比 |
| network agent（图 B） | 收到告警后**不看** measured / threshold，只把它当成"该查这条流了"的触发：选中这条流的 commitment，强制刷新它的路径，再走 tick 也会走的判断，即"应传 vs 已传、超过容差才算落后" | `deviation.watched` → `check` |

所以真正的判据只有一个：按预留应传的字节 vs 实际已传的字节，加上容差 `progress_lag_tolerance`。告警只决定**什么时候查、查哪几条**。

阈值写在 `Subscribe.threshold_gbps` 里，应由 network agent 发订阅时给。但订阅还**没接通**：目前只有测试里手写（例如 36）。设计里的意图是"预留速率的某个比例，例如 90%"，接通时这个比例应成为 config 参数。

**2. start / end 是"这个条件成立的时间段"，长度不固定，依 kind 而定**

| kind | start | end |
|---|---|---|
| `link_down` | 链路断开的时刻 | None：还没恢复，不知道何时结束 |
| `link_up` | 恢复的时刻 | None |
| `link_capacity_below` | 订阅给了时段：容量低于阈值的那一段（可以在将来，即 telemetry 当前认为将会发生的）；没给时段：now | 有时段时是那一段的结束；没给时段为 None |
| `flow_below_rate` / `flow_stalled` | now − `min_duration_seconds` | now：这是观测窗口，长度由订阅的 `min_duration_seconds` 决定 |
| `flow_finished` | 完成的时刻 | None |

同一个订阅产生的窗口长度相同，不同订阅可以不同，不存在全局固定值。另外如实说明：图 B 目前**没用到** start / end，只用 `link_id` / `flow_id` 选 commitment，具体哪个时段受损由刷新后的账本判断。它们现在只起记录作用。

**3. "both ways" 指物理链路的两个方向；按 kind 其实是二选一，但 schema 没强制**

一条物理链路（如 L2）是全双工的，拆成两条有向链路：`L2:esnet-atl>esnet-chi` 和 `L2:esnet-chi>esnet-atl`。账本、容量都按有向链路记。

- **`link_down` / `link_up`**：断的是光纤，两个方向一起断（sim 的 `add_outage` 也只接受物理 id）。telemetry 很可能只按物理链路报，所以允许 `link_id = "L2"`，意思是两个方向都算，`watched` 会把两条有向链路都匹配上。
- **`link_capacity_below`**：容量按方向算，只该用有向 id；mock 里传物理 id 会直接 KeyError。

所以确实不该模棱两可：按 kind 是确定的二选一，只是现在靠注释约定，schema 层没有检查（schema 不知道拓扑，判断不了一个字符串是物理 id 还是有向 id）。建议拆成两个字段：`link_id`（有向，`link_capacity_below` 用）和 `physical_link_id`（`link_down` / `link_up` 用），由校验器按 kind 强制。要改的话我来改。

**4. 只有 gbps，是因为图 B 只承诺带宽和时间；不适用的 kind 两个值是 None，不是 0；`link_up` 是"状态变化通知"**

- 图 B 对 scheduler 承诺的是"多少 Gbps、什么时段"，偏差的判据是字节与速率，所以目前只需要 gbps。延迟、丢包率会影响实际吞吐（例如 TCP 在丢包下跑不满），但它们表现出来就是"传输落后"，已经能被流级信号接住。将来如果第 9 步归因要区分原因，再加字段，例如 `measured_value` + `unit`。
- `link_down` / `link_up` / `flow_finished` / `flow_stalled` 的两个值是 **None**，表示不适用。0 会被误读为"测得 0 Gbps"。另外现在的校验器只要求 `link_capacity_below` / `flow_below_rate` 必须带这两个值，**没有禁止**其他 kind 带。这一点偏松，可以收紧。
- `link_up` 叫 "alert" 确实不准确，它是**恢复通知**，不是坏消息。用处在于：图 B 收到后强制刷新该链路，前方的损坏消失，之前判断"来不及"的可能变成 covered（同时清掉 unresolved 记录），或者不必再换路径。第九节把"恢复要不要推送"列为待与 SB 对齐的问题。命名上，`TelemetryAlert` 改成 `TelemetryEvent` / `TelemetryNotice` 更贴切，也可以先不改，等和 telemetry agent 对齐时一起定。

**5. Subscribe 是向下的请求，TelemetryAlert 是向上的结果：一对多，不是包含**

| | 方向 | 内容 |
|---|---|---|
| `Subscribe` | network agent → telemetry | "请盯着这些对象（targets）的这种条件（kind），阈值多少、窗口多长" |
| `TelemetryAlert` | telemetry → network agent | "你订的那个条件现在成立了"，带上是哪个对象、什么时段、测得值 |

一个订阅在时间上可以触发很多条告警。告警的 kind 等于订阅的 kind，阈值抄自订阅。mock 的 `MockAlerts` 还做了去重：同一条件持续期间只推一次，条件消失后再成立才再推。

现在的使用情况：**network agent 里没有任何地方创建 Subscribe**，只有测试手写订阅，交给 `MockAlerts.poll(subscriptions, now)`，再把产生的告警送进图 B。接通后应该是：
- 每次 commit / modify / release / 图 B 修复之后，network agent 重算订阅；
- `link_capacity_below` 的阈值 = 我们在这条链路这段时间订的总量；
- `flow_below_rate` 的阈值 = 预留速率的某个比例；
- 再把订阅发给 telemetry。

另外有一个缺口：告警里没有 `subscription_id`，收到告警时对不回是哪条订阅。接通时建议加上。

**6. 这两行定义"图 B 的输入是 Tick 或 TelemetryAlert 之一，按 kind 字段区分"，以及解析它的工具**

```python
RuntimeEvent = Annotated[Tick | TelemetryAlert, Field(discriminator="kind")]
```
- `Tick | TelemetryAlert`：类型上是二者之一。
- `Field(discriminator="kind")`：告诉 pydantic **看 `kind` 字段决定是哪一个**。`Tick.kind` 只能是 `"tick"`，`TelemetryAlert.kind` 是六种告警之一，两边的取值不重叠，所以看一眼 `kind` 就知道该用哪个模型校验。不加这一行，pydantic 会挨个试，报错信息也会混在一起。

```python
RUNTIME_EVENT = TypeAdapter(RuntimeEvent)
```
- `RuntimeEvent` 是一个类型表达式，不是 pydantic 模型类，没有 `.model_validate()`。`TypeAdapter` 把任意类型包成一个能校验的对象，提供 `validate_python` / `validate_json` / `dump_python` 等。

用法在 `graphs/runtime.py` 的 classify_event：

```python
RUNTIME_EVENT.validate_python({"kind": "tick"})                        # → Tick()
RUNTIME_EVENT.validate_python({"kind": "link_down", "link_id": "L2",
                               "start": ..., "observed_at": ..., "source": "mock"})   # → TelemetryAlert
RUNTIME_EVENT.validate_python({"kind": "reboot"})                      # → ValidationError：没有这种 kind
```
它接受 dict（telemetry 发来的 JSON），也接受已经是模型的对象。校验失败时，classify_event 按 tick 处理，原因记进 `invalid_event`。

**7. `lent_to` 是借到容量的那个（高优先级）；报告本身是关于出借方的。`commitment` 是更新后的完整承诺**

- `action = "lend"` 的那条报告，`commitment_id` 是**出借方**，即被压低速率、priority 低的那个；`lent_to` 是**借到 slack 的高优先级 commitment** 的 id。demo 里是：`DeviationReport(commitment_id="cmt-1"（TL，priority 1）, action="lend", lent_to="cmt-2"（TH，priority 2）)`。它告诉 TL 的 scheduler："你的承诺被改了（80 → 40 Gbps，结束推到 11:30，仍赶得上 17:00），原因是让给了 cmt-2"。
- `commitment` 是完整的 `Commitment` 对象：新的 `rate_profile`（速率、结束时间）、`circuit_id`、`binding`（VLAN 等）。repaired 时它是修复**之后**的版本，scheduler 和 WMS 要靠它知道新的结束时间。换路径时 VLAN 也变了，WMS 必须改用新的 binding 发数据，只有 id 是不够的。unresolved 时它是原样，方便 scheduler 不必回查就能决策。
- 顶层的 `commitment_id` 确实和 `commitment.commitment_id` 重复，校验器强制两者相等。保留它是为了和 `transfer_id` / `workflow_id` 一样做扁平的索引键，接收方按 id 路由、去重时不必拆开嵌套对象。如果你觉得冗余，可以去掉顶层的 id，或者 unresolved 时不带 `commitment`，二选一。

---

> 1. in ledger.py, "apply 写入；同一槽内 0 容量的 up 样本和 down 样本并列时取 down。用来区分 link_down 和 congestion", I don't understand.
> 2. in context.py, why context needs "FlowSource", and what is FlowSource? What is progress_seen? What is committed and committed() and why context needs it? Give me some examples.
> 3. what is `progress_lag_tolerance` used for?

**1. 一个槽被几段样本覆盖时，账本只能留一条观测；两段都是 0 时，留"断开"的那条**

背景有三点：

- **账本按槽记**（测试里一槽 15 分钟），telemetry 的样本按"状态不变的时间段"给，两者边界不一定对齐，所以一个槽可能被几段样本覆盖。
- `apply` 的原规则是**取最小的容量**：槽里任何一刻都不能高估可用容量。
- A 部分给 `Observation` 加了 `up`（链路是否通）。图 B 靠它判断原因：受损槽上 `up=False` 记为 `link_down`，`up=True` 但 observed < own 记为 `congestion`（`deviation.SlotDamage.cause`）。

问题出在**两段样本容量都是 0**的时候。例：L2 容量 100，09:00–09:20 被别人的流量占满（up，可用 0），09:20–09:30 光纤断了（down，可用 0）。09:15–09:30 这一槽收到两段样本：

| 样本 | up | 可用容量 |
|---|---|---|
| [09:15, 09:20) | True | 0 |
| [09:20, 09:30) | False | 0 |

只比容量会打平，打平时留哪条取决于样本的顺序：留下 up 的那条，这一槽就读成"通着、只是拥塞到 0"，cause 就会错报成 `congestion`。

所以比较时用 `(容量, up)` 这个二元组取最小。Python 里 `False < True`，所以 `(0, False) < (0, True)`：容量相同时取 down。规则是：**槽里只要有一刻断过，这一槽就读成断开**。理由是这样更保守，而且中断是更严重、更需要换路径的原因。

容量不同时照旧取小的：拥塞剩 20、另一段正常剩 40，就记 20、up。只有容量打平时 up 才起作用，而实际上只有"拥塞到 0"和"断开"会打平（down 的样本可用容量必为 0，`LinkSample` 的校验器强制）。

**2. FlowSource、progress_seen、Committed 与 committed()**

先说 context 放什么：graph 的 state 只活在**一次运行**里，跑完就丢；要在多次运行之间保留的东西，以及外部接口，都放在 `AgentContext`。调用方建一次，每次 invoke 都传进去。这四样都属于这一类。

**FlowSource**（`telemetry.py`）是一个接口，只有一个方法：

```python
class FlowSource(Protocol):
    def progress(self, instance_id: str, now: datetime) -> FlowProgress: ...
```

意思是"问一下：跑在这个 SENSE instance 上的那次传输，什么时候开始的、到 now 传了多少字节"。它和 `telemetry: TelemetrySource`、`sense: SenseAdapter` 一样是**外部接口**：
- 现在的实现是 `MockFlows`，从模拟网络 `sim.flow_trace` 算出来；
- 将来换成 telemetry agent 的真实测量，图 B 的代码不用改。

放进 context，是因为图 B 的节点只能通过 `runtime.context` 拿到外部接口。图 B 的主信号"应传 vs 已传"里，"已传"就来自它。

```python
ctx.flows.progress("si-1", t(10))
# → FlowProgress(flow_id="si-1", started_at=09:00, bytes_sent=13.5 TB, sampled_at=10:00, source="mock")
```

**progress_seen**：`dict[instance_id → 上一次读到的 FlowProgress]`。用途是算**最近速率**。一次读数只能告诉你"到现在一共传了多少"，速率要靠两次读数之差。而两次读数来自两次 tick，也就是图 B 的两次运行，state 留不住上一次的，只能放在 context。

```
09:50 tick：读到 10.5 TB → 存入 progress_seen["si-1"]
10:00 tick：读到 13.5 TB；与上一次相比 3 TB / 600 s = 40 Gbps → recent_gbps = 40
```

图 B 用它判断"问题还在不在"：unlocated 时，最近速率仍明显低于预留速率，就用它给预测封顶，否则认为已恢复（`forecast.off_path_cap`）。

**Committed / committed()**：图 B 要盯的是"已 commit、还没释放的承诺"，但需要的信息分散在两本账里：

| 在哪 | 有什么 | 缺什么 |
|---|---|---|
| `ctx.commitments[cid]` → `Commitment` | 发给 scheduler 的那份：id、circuit_id、rate_profile、binding | 没有路径、booking、总字节数、latest_finish、priority |
| `ctx.reservations[rid].items` → `ReservedOffer` | 路径（placement.path）、booking_id、instance_id、请求（bytes、window、priority） | 不知道自己对应哪个 commitment（要经 `commitment_ids` 转一次） |

`Committed(commitment, reserve_id, item)` 把两边拼成一条。`committed()` 遍历所有 `state == "committed"` 的 reservation，取其中还没 release 的 item，配上它的 commitment，返回列表：

```python
ctx = make_committed_ctx(net)          # reserve + commit q1/T1/1
ctx.committed()
# → [Committed(commitment=cmt-1（si-1，09:00–11:46:40 @ 40），
#              reserve_id="rsv-1",
#              item=ReservedOffer(offer_id="q1/T1/1", placement.path=MAIN,
#                                 booking_id="rsv-1/q1/T1/1", instance_id="si-1",
#                                 request=T1（50 TB，window 09:00–15:00，priority 1）))]
```

- 只 reserve、还没 commit 的不在里面：它们没有承诺，最多活 60 秒；
- release 之后也不在里面；
- 换路径修复后，item 换成新 circuit 的那个，commitment_id 不变。

图 B 的用法：
- `watched` 用它决定这次事件要查哪些 commitment：tick 查全部；链路告警查路径经过那条链路的；flow 告警查 `instance_id` 对上的；
- 后面算受损槽要用 `item.booking_id`，算剩余字节要用 `item.request.bytes`，算 deadline 要用 `item.request.window.latest_finish`，借用要比较 `item.request.priority`。

它是一个方法而不是 context 里的又一本账，是因为它只是**由现有两本账现算出来的视图**。再存一份，就得在 commit / release / modify / 修复时同步维护，容易不一致。

**3. `progress_lag_tolerance`：判断"慢了多少才算数"的容差**

config 参数，0 ≤ x < 1，测试里是 0.05，即 5%。作用是**挡住抖动和测量粒度带来的误报**：真实传输不会精确地按预留速率走，差一点就报，scheduler 会被淹没。现在用在三处，都是"差距超过容差才算"：

| 用在哪 | 判断 | 例子（cmt-1 @ 40 Gbps，10:00 检查） |
|---|---|---|
| 落后（`deviation.is_behind`，A） | 应传 − 已传 > 容差 × 应传 | 应传 18 TB，门槛 0.9 TB。09:00 停 2 分钟只少 0.6 TB（3.3%）→ 不报；源端只有 60%，少 7.2 TB → 报 |
| 预留内传不完（overrun，B） | 剩余 − 预留还能运的 > 容差 × 剩余 | 09:20 才开始：10:00 剩 38 TB，预留还能运 32 TB，差 6 TB（15.8%）→ 报 |
| 是否仍慢（`forecast.off_path_cap`，B） | 最近速率 < (1 − 容差) × 预留速率 | 最近 24 Gbps < 38 → 仍慢，预测以 24 封顶；最近 40 → 已恢复 |

正好等于容差的不算（`test_tolerance_boundary`）。调大：误报少，但发现得晚，留给修复的时间少；调小则相反。

另外，一个参数同时管着三件事，是我写 B 部分时顺手复用的。如果以后发现三者需要不同的值（例如"仍慢"想用更严的门槛），可以拆成三个 config 参数。

---

> 1. aren't the reserve_id and booking_id the same thing? what's the difference?

**不是一回事：reserve_id 是协议层"一次预订"的编号，一次可以包含多个 offer；booking_id 是账本里"一条路径上一份容量"的编号。一个 reserve_id 下面有一个或多个 booking_id。**

| | reserve_id | booking_id |
|---|---|---|
| 是谁的编号 | 一个 `Reservation`（`ctx.reservations` 的键） | 账本里的一个 `Booking`（`CapacityLedger._bookings` 的键） |
| 管多大范围 | 一次 reserve 请求选中的**所有** offer，整组一起 commit、过期，也可以整组或部分 release | **一个** offer：一条路径、每个槽占多少 Gbps、pending / confirmed |
| 谁看得见 | scheduling agent：`ReserveAck` 返回它，commit / release / modify 都拿它来指代预订 | 只有 network agent 内部；scheduler 从来看不到 |
| 谁用它 | 图 A 的各分支、过期回收（TTL 按整个 reservation 算） | 账本的 `pending` / `confirm` / `rollback` / `release` / `replace`。账本不知道 reservation 是什么，只认 booking |
| 例子 | `rsv-1` | `rsv-1/q1/T1/2`、`rsv-1/q1/T2/1` |

例子（5a/5b 的 demo）：scheduler 一次 reserve 了 T1 的 `q1/T1/2` 和 T2 的 `q1/T2/1`：

```
Reservation rsv-1 (state=committed)
  item q1/T1/2 → booking rsv-1/q1/T1/2   (MAIN, 12:00–13:06:40 @ 100)   → SENSE si-1 → cmt-1
  item q1/T2/1 → booking rsv-1/q1/T2/1   (MAIN, 09:00–09:03:20 @ 40)    → SENSE si-2 → cmt-2
```

- T2 提前传完，scheduler 发 `release(rsv-1, offer_ids=[q1/T2/1])`：账本退还 `rsv-1/q1/T2/1`，`rsv-1` 还在，T1 照常；
- reserve 时，`ledger.pending_group` 对这组 booking **一起**检查、一起写入，任何一个放不下都不写，这就是"一个 reservation、全有或全无"在账本层的落实；
- 每个 item 身上挂着四个 id：`offer_id`（query 时给的）、`booking_id`（账本）、`instance_id`（SENSE circuit）、commit 之后再加 `commitment_id`。reserve_id 在它们上一层。

看起来像同一个东西，是因为命名：图 A 的 reserve 分支把 booking_id 取成 `f"{reserve_id}/{offer_id}"`（`graphs/reserve.py` 的 `ledger_pending`），所以字符串以 reserve_id 开头。这只是为了好认，两者并不一一对应，下面两种情况会分开：

- **图 B 换路径**：同一个 reservation、同一个 offer 换了一份新的 booking `rsv-1/q1/T1/1/reroute-1`（新 circuit 的容量），旧的 booking `rsv-1/q1/T1/1` 被退还。reserve_id 不变，booking_id 变了。
- **orphan**：reserve 失败、SENSE 又没能取消 instance 时，`ctx.orphans` 记的是 instance → booking_id。这时 reservation 根本没建成，booking 却还在账本里占着，直到 expiry sweep 回收。

---

> talk about the deviation.py, including the use, the position, and the relationship between functions. Let me understand it quickly.

**用途**：回答"哪些已 commit 的承诺没拿到我们答应的，原因是什么"。它是图 B 第一个节点 classify_event 背后的逻辑，只读不改（唯一的写入是刷新账本观测和记 `progress_seen`）。

**位置**：

```
告警 / tick ─► graphs/runtime.py: classify_event ──► deviation.detect()  ─► list[Deviation]
                                  scan_path      ──► deviation.widen()   ─► 补充的 Deviation
                                                     forecast.assess()   ◄── 读 Deviation
```

- 上游：`context.committed()`（盯谁）、`ctx.flows`（进度）、`telemetry.refresh_stale`（刷新观测）、账本（observed / own）；
- 下游：`forecast.py` 用 `Deviation` 做预测，`repair.py` 用它的 cause / links 做修复和报告。

**函数关系**（自上而下调用）：

```
detect(ctx, event, now)                       入口：classify_event 调
 ├─ watched(ctx, event)                       这个事件要查哪些 commitment、强制刷新哪些链路
 └─ check(ctx, commitments, now, force)       逐个检查，返回 Detection
     ├─ ctx.flows.progress(...)               读进度；已传完的跳过
     ├─ refresh_stale(..., force=)            刷新观测（tick 只刷过期的，告警的链路强制刷）
     ├─ due_bytes(profile, started_at, now)   按预留应传多少（从实际开始算）
     ├─ is_behind(due, sent, tol)             信号 1：落后超过容差？
     ├─ due_bytes(profile, now, end) + is_behind   信号 2 overrun：预留内还传得完吗？
     ├─ recent_rate(prev, cur)                与上一次读数比，算最近速率
     └─ damaged_slots(ledger, c, since)       信号 3：各槽各跳 observed < own 或断开 → SlotDamage
         → 定 cause（link_down > congestion > late_start > unlocated），生成 Deviation

widen(ctx, deviations, checked, now)          scan_path 调：受损跳上还没查过的 commitment，再走一遍 check
```

**三个数据结构**（由小到大）：

| 结构 | 是什么 |
|---|---|
| `SlotDamage` | 一个槽、一跳上的损坏：哪条链路、哪段时间、observed、own、是否 up；`.cause` 由 up 决定是 link_down 还是 congestion |
| `Deviation` | 一个有偏差的 commitment：`committed`（承诺 + 预订项）、`cause`、`links`、`damage`、`progress`、`due_bytes`、`behind`、`overrun`、`recent_gbps`；附带属性 `lag_bytes`、`remaining_bytes` |
| `Detection` | 一次检查的结果：`deviations`、`checked`（看过的 commitment）、`refreshed`（刷新过的链路） |

**判定规则一句话**：behind 或 overrun，或者"从现在起"它订的槽里有一跳受损，就算偏差。已过去的受损槽只在 behind / overrun 时用来说明是哪一跳造成的。

---

> 1. so for SlotDamage, observed_gbps is must less than own_gbps?
> 2. what is the meaning of due_bytes, behind, overrun and recent_gbps in Deviation?

**1. 是的，一条 SlotDamage 里 observed 一定小于 own；但 own 是"我们在这跳这槽的全部预订"，不只是这一个 commitment 的**

`damaged_slots` 记一条 SlotDamage 的条件是：`not obs.up or obs.gbps < own − EPS`。

- up 的情况：条件本身就是 observed < own；
- down 的情况：down 时 observed 必为 0（`LinkSample` 的校验器强制）。而这个槽在这个 commitment 的 booking 里，它的速率 > 0，所以 own > 0，同样有 observed < own。

要注意 own 的含义：`own_gbps` 是**我们所有 booking** 在这一跳、这一槽的总和，不是这个 commitment 自己的速率。例：L2 某槽 observed 70，我们有 cmt-1 订 40、cmt-2 订 60，own = 100 > 70。这是一条损坏，两个 commitment 都会各记一条 SlotDamage。这说明"我们在这跳上答应出去的总量超过了它能给的"，不等于"cmt-1 只能拿到 70 以下"。实际每个能分到多少，由 B 部分的预测按速率比例算：cmt-1 分 70 × 40 / 100 = 28。

**2. Deviation 里这四个字段**

以 cmt-1（09:00–11:46:40 @ 40 Gbps，50 TB）为例，10:00 检查。

| 字段 | 含义 | 例子 |
|---|---|---|
| `due_bytes` | **按预留应该已传的字节**：rate_profile 从**实际开始时刻**积分到 now，最多到总字节数；还没开始就是 0 | 09:00 开始：18 TB；09:20 才开始：12 TB（只算 09:20 之后） |
| `behind` | 信号 1，**已经落后**：`due − sent > 容差 × due` | L2 09:30–09:45 中断：已传 13.5 TB，差 4.5 TB（25%）→ True；09:00 停 2 分钟，只差 3.3% → False |
| `overrun` | 信号 2，**预留内传不完**：已开始的传输，剩余字节 − 预留从 now 到结束还能运的字节 > 容差 × 剩余字节 | 09:20 才开始：剩 38 TB，预留还能运 32 TB，差 15.8% → True，而 behind 是 False；上面的中断例子里两者都是 True |
| `recent_gbps` | **最近速率**：这次读数与上一次读数（`ctx.progress_seen`）之差 / 间隔；第一次读、没有上一次时为 None | 09:50 读到 10.5 TB，10:00 读到 13.5 TB → 40 Gbps |

分工：
- `behind` 看**过去**：到现在为止少传了多少，从实际开始算，晚开始本身不算落后；
- `overrun` 看**未来**：照预留的速率继续传，结束前能不能传完。它接住了 behind 管不到的两种情况：晚开始，以及每次都落后不到容差、但累积起来传不完；
- 两者都是 False，也可能是偏差：前方有受损槽（例如计划在 11:00 的中断），这时 `damage` 非空；
- `recent_gbps` 不参与判定是否偏差，留给 B 部分判断"问题还在不在"：unlocated 时，最近速率仍明显低于预留速率，就用它给预测封顶。

这几个字段之上还有两个派生属性：`lag_bytes = due_bytes − 已传`（落后多少），`remaining_bytes = 总字节 − 已传`（还剩多少）。

---

> "09:20 才开始：剩 38 TB，预留还能运 32 TB，差 15.8%"
>
> Why it's not "40/8*60*146=43.8TB?"

两个数算的时间段不同。缺口是同一个，都是 6 TB。

- **你算的**是从**传输开始（09:20）到预留结束（11:46:40）**这整段，预留一共能运多少：
  40 Gbps = 5 GB/s，09:20 → 11:46:40 是 146.67 分钟 = 8800 s，5 GB/s × 8800 s = **44 TB**（取 146 分钟就是 43.8 TB）。
  要传 50 TB，只能运 44 TB，差 6 TB。
- **overrun 算的**是从**检查时刻（10:00）到预留结束**还能运多少：
  10:00 → 11:46:40 是 6400 s，5 GB/s × 6400 s = **32 TB**。
  这时已传 12 TB（09:20–10:00，40 分钟 × 5 GB/s），剩 50 − 12 = **38 TB**，差 38 − 32 = 6 TB。

两种算法的关系：44 TB = 已经运了的 12 TB + 还能运的 32 TB。所以"总量 50 vs 44"和"剩余 38 vs 32"差的是同一个 6 TB。

overrun 用后一种，即"剩余 vs 从现在起还能运的"，原因有两个：

1. 它只看**未来**，与过去发生了什么无关。如果之前还出过中断，"从开始算"的那 44 TB 就不对了，而"剩余字节"是读出来的实际值，"从 now 起还能运的"只依赖预留，两边都可靠。
2. 容差按剩余字节算：6 / 38 = 15.8% > 5%，所以报。越接近结束，剩余越少，同样的缺口占比越大，这正好对应"小落后积累到最后传不完"的情况。

---

> why can't we just keep using overrun and delete behind?

**可以删，代码也能跑通；但会发现得更晚。两者量的是同一个落后量，只是拿来比较的基数不同。**

准时开始、预留大小正好等于传输大小时：
- 预留从 now 起还能运的 = 总字节 − 应传；
- 所以 `剩余 − 还能运的 = (总字节 − 已传) − (总字节 − 应传) = 应传 − 已传 = 落后量`。

两个信号比的是同一个落后量，区别只在除以谁：

| 信号 | 条件 | 什么时候灵敏 |
|---|---|---|
| behind | 落后量 > 容差 × **应传** | 传输**前期**：应传还小，一点落后就过线 |
| overrun | 落后量 > 容差 × **剩余** | 传输**后期**：剩余变小，一点落后就过线 |

**删掉 behind 的代价：前期发现得晚。** 例：源端从 09:00 起只有 60% 速度（cmt-1 @ 40 Gbps，50 TB），每秒少传 2 GB：
- behind：落后量 / 应传 恒为 40%，第一次检查就报，例如 09:05；
- overrun：要等 2t > 5% × (50 TB − 3t)，t ≈ 1163 s，约 **09:19** 才报。

晚发现 15 分钟，留给修复的时间和余量就少了（能借的、能换的路径都可能已经被别人订走）。中断那种落后量大的情况，两者几乎同时触发。

**删掉 behind 的好处也是实在的：**
1. **修复后不再反复检出。** 现在延长预留之后，落后量补不回来，behind 每次 tick 都是 True，图 B 每次都要走 scan_path → triage 判为 covered（第 7 步 B–D 留下的空白 ②）。overrun 在延长后就变成 False，安静了。
2. **预留有富余时不报。** 例如 scheduler 已把结束时间放宽，慢一点也无妨。overrun 只在"真的会传不完"时才报，更贴近"是否需要动作"。
3. **前期的误报风险。** behind 在刚开始时门槛很小（应传小），开头几十秒的一次抖动就可能过 5%。而第一次读数时 unlocated 的预测用的是"开始以来的平均速率"，会被这次抖动拉低，可能导致一次不必要的延长。这是我写 B 时没有充分考虑的风险。

**另外两者都有的一个弱点**：它们都只看已经发生的落后量，没有用"现在仍然慢"来推未来。overrun 假设从 now 起会按预留速率跑满，所以对持续变慢的情况反应慢。真正按"最近速率"推未来的，是 scan_path 的预测和 triage。

**我的建议：先保留两者。** 早发现在运行时修复里更值钱，噪音的代价只是多跑一次 scan_path 和 triage，不会重复上报。等将来接真实 telemetry、看到前期抖动的实际误报率之后，再决定是删 behind，还是给它加一个前期的门槛（例如应传不足某个量时不判）。你若更看重简单和安静，删 behind 的改动很小：去掉 `behind` 字段，"已过去的受损槽用来定位"改为只在 overrun 时保留；A 的测试中依赖 behind 的几条要改。

---

> Overall, what did 7a do?

**7A 做的是图 B 的"眼睛"：让 network agent 在 commit 之后能看到传输的实际情况，并判断哪些承诺出了偏差、原因在哪。** 它不修、不报，只检测。

它由四块组成：

1. **输入（schemas.py，临时接口）**：图 B 由什么触发。
   - `Tick`：定时全查一遍，兜底；
   - `TelemetryAlert`：telemetry 推来的六种告警（`link_down` / `link_up`、`link_capacity_below`、`flow_below_rate`、`flow_finished` / `flow_stalled`）；
   - `Subscribe`：network agent 向 telemetry 订阅告警，只定义了，没接通；
   - 二者合成 `RuntimeEvent`，由 `RUNTIME_EVENT` 解析。
2. **传输进度（telemetry.py + sim.py）**：
   - 新接口 `FlowSource.progress()`：某条传输何时开始、已传多少字节；
   - mock 由模拟网络算：实际速率 = min(预留速率, 路径上最紧一跳剩给它的) × 链路以外的系数。可以造出中断、拥塞、端主机变慢、晚开始等情况；
   - `MockAlerts` 从同一个模拟网络生成告警。
3. **检测（deviation.py）**：对每个已 commit 的承诺看几个信号。
   - 流级：按预留应传的字节 vs 实际已传的字节，落后超过容差（`progress_lag_tolerance`）就算 behind；
   - 链路级：刷新观测后，它订的槽里某一跳断开或 observed < own，用来定位是哪一跳，也覆盖还没开始的承诺；
   - 给出 cause：`link_down` / `congestion` / `unlocated`；
   - 结果是 `Deviation`，里面带着后续 scan_path 和修复要用的全部数据。
4. **配套与骨架**：
   - 账本观测加 `up`，用来区分中断和拥塞到 0；
   - `refresh_stale(force=)`：告警涉及的链路强制刷新；
   - context 加 `flows`、`progress_seen`、`committed()`；
   - config 加容差；
   - 图 B 的骨架：classify_event → 无偏差就结束、有偏差走占位节点。

一句话：**A = 输入事件 + 读进度 + 判偏差（是否偏、偏在哪一跳、什么原因）。**

后来在 B 里对 A 做了两处补充：
- 新增 overrun 信号和 cause `late_start`，解决 A 留下的"晚开始、预留内传不完没人管"；
- 占位节点换成了完整的 scan_path → triage → 修复 → 上报。
