代码结构已经重组好了。这次只移动文件、改 import，没有改任何行为：272 个测试全部通过，demo 能正常运行，私有信息检查 0 命中。

```
network_agent/
├── src/
│   ├── models/      config  schemas  topology        参数、跨 agent 消息、拓扑
│   ├── state/       ledger                           容量账本
│   ├── planning/    placement  estimate  circuit     放置、完成时间估计、circuit 编译
│   ├── sim/         sim                              模拟网络
│   ├── adapters/    telemetry  sense                 外部系统接口 + mock
│   ├── context/     context                          图之间共享的运行上下文
│   ├── shared/      operations  reclaim              图 A / 图 B 共用的状态变更操作
│   ├── runtime/     deviation  forecast  repair      图 B 的业务逻辑
│   └── graphs/
│       ├── protocol/   protocol query reserve commit release modify common   （图 A）
│       └── runtime/    runtime                                                （图 B）
└── tests/           不动，import 改成 from ..src.models.schemas import ...

```

各层按依赖顺序排列，后面的层只依赖前面的层。我用脚本检查过，没有反向依赖。

**和讨论时的方案有两处不同，需要你确认**

1. `context.py` **单独放进** `context/`**，没有和 ledger 一起放在** `state/`**。** 它要用到账本、适配器和估计模型，放进 `state/` 的话，state 和 adapters 会互相依赖，形成循环。
2. **共用操作这一层叫** `shared/`**，不叫** `lib/`**。** 同步脚本的私有信息检查会拦 `src/lib/` 和 `src.lib.`（用来防止把本仓库的路径带出去）。`network_agent/src/lib/` 正好命中这两条规则，sync 会被拒。如果你更想用 `lib`，就得放宽 [private_patterns.txt](../../tools/common/private_patterns.txt) 里这两条规则，但我不建议这样做。

**一起更新的文件**

- 每层的 `__init__.py` 加了一行说明，[network_agent/__init__.py](../../src/lib/network_agent/__init__.py) 里的目录表也改成了新结构。
- [PLAN.md](../../resources/other/network_agent/PLAN.md) 新增了「代码目录结构」一节，第 8、9 步的计划路径也改成了新路径。
- [manage_kklab_scinet_agents.md](../../tools/manage_kklab_scinet_agents/manage_kklab_scinet_agents.md) 里的相对导入示例改成了新写法。
- 这一步的记录追加到了 [20261107_buildruntime_step7c.md](../../resources/notes/20261107_buildruntime_step7c.md)。

**下次 sync 前要通知同事。** telemetry_agent 里有 12 个文件直接 import 了 network_agent，要按下表改：


| 原来                                     | 改成                                                  |
| -------------------------------------- | --------------------------------------------------- |
| `network_agent.schemas`                | `network_agent.src.models.schemas`                  |
| `network_agent.config`                 | `network_agent.src.models.config`                   |
| `network_agent.topology`               | `network_agent.src.models.topology`                 |
| `network_agent.ledger`                 | `network_agent.src.state.ledger`                    |
| `network_agent.placement` / `estimate` | `network_agent.src.planning.placement` / `estimate` |
| `network_agent.sim`                    | `network_agent.src.sim.sim`                         |
| `network_agent.telemetry`              | `network_agent.src.adapters.telemetry`              |
| `network_agent.context`                | `network_agent.src.context.context`                 |
| `network_agent.graphs.protocol`        | `network_agent.src.graphs.protocol.protocol`        |
| `network_agent.tests.helpers`          | 不变                                                  |


此外，他们的 `demo.py` 用的 `build_quote_graph` 在本仓库里早就改名为 `build_query_graph` 了，所以他们那边本来就有一处对不上。

`resources/notes/` 里旧笔记的代码链接指向旧路径，现在都会失效。这些笔记是人工维护的，我没有改。

现在还没有 commit。
---

> 从overview汇报角度，需要汇报runtime这部分的哪些设计和概念？

**一句话定位**：图 A（protocol）负责**许下承诺**（query → reserve → commit），图 B（runtime）负责承诺之后的**兑现**：发现偏差 → 判断 → 本地修复 → 上报。本地修不好的交给 scheduling agent 决定（再走图 A）。

**建议讲的 7 个点**（按汇报顺序）

1. **流程图（一张图讲完）**

   ```
   事件 → classify_event → scan_path → ◇triage → ◇plan_local_repair → execute_repair → report_deviation
          发现偏差          扩大范围+预测   要不要修    修哪几种、按什么顺序     执行(失败回滚)      上报
   ```
   两个 ◇ 是判断点，其余节点只做编排。

2. **触发：事件驱动，Tick 兜底**
   - telemetry 推告警（link_down/up、容量低于阈值、flow 速率低、flow 卡住/完成），只检查相关承诺，并强制刷新相关链路。
   - 周期性 Tick 检查全部承诺，防止告警丢失或不支持。
   - 格式不对的事件不丢弃，当作 Tick 处理。
   - 告警 schema 目前是**暂定**的，需要和 telemetry 同事对齐（可以作为开放问题提出）。

3. **偏差：三种信号 + 四种原因**
   - 信号：behind（实际字节落后于应到字节）、overrun（剩下的字节在预留内传不完）、链路级（某 hop 给的容量小于我们订的）。链路级信号对还没开始的传输也有效，所以能**提前**发现问题。
   - 原因：link_down / congestion / late_start（用户自己晚开始，不是网络的错）/ unlocated（路径上找不到问题，比如端主机慢）。
   - 原因决定后面能用哪些修复，也会写进上报。

4. **扩大范围 + 预测**
   - 一个 hop 坏了，经过它的其他承诺也会受影响，即使告警没有提到它们，scan_path 也会主动把它们找出来。
   - 对每个偏差，用账本和观测推算未来的速率，给出 p50/p95 完成时间，判断现有预留还能不能按时传完（covered）。

5. **分诊（triage）：只修真正需要修的**
   - covered：现有预留还够，不动。
   - already_reported：之前上报过修不好，原因和承诺都没变，不重复修也不重复报。
   - to_repair：进入修复。

6. **本地修复：改动最小的优先**
   - extend（延长结束时间）→ raise_rate（提高速率）→ reroute（换路径，先建新的再拆旧的，make-before-break）→ borrow（让共享 hop 的低优先级承诺降速，前提是它们仍能在自己的 deadline 前完成）。
   - 高优先级先修，先拿到容量；任何一步失败都回滚，再试下一步。
   - 按原因限制：unlocated 只允许 extend（问题不在网络里，加速率或换路径没用）；late_start 不允许借（不能让别人为用户的晚开始买单）。
   - 修复动作复用图 A 的状态变更操作，不另写一套。

7. **上报 + 策略可替换（重点卖点）**
   - 每个受影响的承诺生成一条 DeviationReport：repaired（附修复方式和新承诺）或 unresolved（交给 scheduling agent）。借出速率的一方也会上报（action = lend）。按原因分组。
   - 两个判断点放在 `RuntimePolicy` 接口后面。现在用规则版 `RulePolicy`，以后可以换成 learning 或 LLM 策略，图结构不用改。这是后续研究的切入点。

**不必在 overview 里讲的**：expected_gbps 的按比例分配公式、速率段的计算、p95 向上取整到秒、`_placement_through_by` 这类实现细节。如果被问到，再展开第 4、6 点。

**可以作为开放问题提出**：告警 schema 和推送通道（目前是 hook）需要和 telemetry / scheduling 两边对齐；unlocated 的归因留给后面的 learning 图。

---

> 1. Triage的covered这个命名不太清楚，重命名。
> 2. 告警的推送和定时检查对应的代码分别在哪
> 3. 所以和telemetry agent的对接，我只需要让负责人实现三种信号behind，overrun，链路级就行？原因和信号哪些是telemetry提供的，哪些是network agent我们自己计算的？
> 4. 扩大范围和做预测对应scan_path吗？

**1. `covered` 改名为 `finishes_in_reservation`**

意思是：偏差确实存在，但按预测，剩下的字节在现有预留结束前就能传完（p95 ≤ 预留的 end），所以不用修。按"同一概念各层同名"的规则，以下几处一起改了：

- `Assessment.finishes_in_reservation`（判断依据）
- `TriageVerdict` 的取值 `"finishes_in_reservation"`
- `Triage.finishes_in_reservation`
- 图 B 的 state 键 `finishes_in_reservation`
- 相关测试和打印，以及图 B 的两个 html 和 PLAN.md 中对应的文字

272 个测试全部通过。

**2. 告警推送和定时检查的代码位置**

先说结论：**代码里没有真正的推送接收端和定时器**。图 B 每次只处理一个事件，由调用方执行 `build_runtime_graph().invoke({"event": ..., "now": ...})`（见测试中的 `helpers.runtime`）。谁来收告警、多久发一次 Tick，留给部署时决定。现在有的代码：

| 内容 | 位置 |
|---|---|
| 告警消息格式 `TelemetryAlert`（暂定） | `src/models/schemas.py` |
| 订阅格式 `Subscribe`（暂定，**还没有接进流程**） | `src/models/schemas.py` |
| 模拟 telemetry 推送：`MockAlerts.poll`（只在测试里用） | `src/adapters/telemetry.py` |
| 定时检查的事件 `Tick` | `src/models/schemas.py` |
| 事件决定检查哪些承诺：`commitments_for_event`。Tick → 全部承诺，只刷新过期的观测；链路告警 → 经过该链路的承诺；flow 告警 → 该 flow 的承诺。告警会强制重新拉取相关链路 | `src/runtime/deviation.py` |
| 格式不对的事件当作 Tick 处理 | `src/graphs/runtime/runtime.py` 的 `classify_event` |

**3. 不是。三种信号和四种原因都是 network agent 自己算的，telemetry 只提供原始观测**

telemetry 需要提供三个接口：

| 接口 | 方式 | 提供什么 | 状态 |
|---|---|---|---|
| `TelemetrySource.link_samples` → `LinkSample` | 拉取 | 每条有向链路在某段时间内是否 up，以及 `available_gbps` | 图 A 已经在用 |
| `FlowSource.progress` → `FlowProgress` | 拉取 | 某个传输（目前用 SENSE instance id 标识）的开始时间 `started_at` 和已传字节 `bytes_sent` | 暂定，需要对齐 |
| `TelemetryAlert` + `Subscribe` | 推送 | 订阅的条件成立时发告警 | 暂定，需要对齐 |

我们用这些数据自己算：

| 信号 / 原因 | 用到的 telemetry 数据 | 我们这边怎么算 |
|---|---|---|
| behind | FlowProgress | 按预留的速率安排，从实际开始时间算到现在"应传多少"，和已传字节比较 |
| overrun | FlowProgress | 剩下的字节和预留剩余时间能传的量比较 |
| 链路级 | LinkSample | 观测容量和账本里我们自己订的量比较 |
| link_down / congestion | LinkSample.up | 出问题的 hop 是否 down |
| late_start | FlowProgress.started_at | 和预留开始时间比较 |
| unlocated | — | 已落后或传不完，但路径上找不到问题 |

所以对接时要和负责人对齐的是这三个接口的**语义**，主要有：

- `available_gbps` 不能扣除我们自己的预留，否则会被扣两次；
- flow 怎么和我们的承诺对应（instance id）；
- 观测的有效期 `valid_until`；
- 告警的阈值、持续时间和推送方式。

另外，告警只是让检查更快、范围更小。只靠 Tick 加上两个拉取接口，功能上已经够用。所以对 telemetry 来说优先级是：link_samples（已有）> flow progress > 告警。

**4. 对，基本就是 scan_path**

- **扩大范围**：`find_deviations_on_damaged_hops`。classify_event 已经找出事件涉及的偏差；scan_path 再把经过同一个坏 hop、还没检查过的承诺也拉进来检查。Tick 已经检查了全部承诺，所以这一步不会再加入新的。
- **做预测**：`assess_all`。对每个偏差给出剩余字节、未来预期速率和 p50 / p95 完成时间（`Assessment`）。这一步也可能刷新观测。
- 判断"能不能在预留内传完"（`finishes_in_reservation`）的依据在 scan_path 算出，但真正分组是在 triage。

---

> 1. "build_runtime_graph().invoke({"event", "now"})"这里的event是告警还是tick？还是说二者共用event这一个格式？
> 2. 你说telemetry只提供原始数据，但是TelemetryAlert又包含了AlertKind，为什么？TelemetryAlert不是Tele agent传过来的message吗？telemetryalert和subscribe是怎么被使用的？如果还没有被使用，应该被怎么使用？
> 3. tick的格式在哪，应该怎么被使用？和TelemetryAlert和subscribe有关系吗？
> 4. late_start是指用户约定了9点开始，却10点才开始传数据导致的赶不上？

**1. 两种都可以，但不是共用同一个格式**

`event` 的类型是 `Tick | TelemetryAlert`（`schemas.RuntimeEvent`），两者只共用一个字段 `kind`，用它来区分：`kind == "tick"` 是 Tick，`kind` 是 `link_down` 等六种取值之一时是告警。`classify_event` 用 `RUNTIME_EVENT.validate_python` 根据 `kind` 解析成对应的类型，可以传 model，也可以传 JSON dict。每次 invoke 只处理一个事件。

**2. 告警是触发器，不是结论**

- `TelemetryAlert` 确实是 telemetry agent 发来的消息。`AlertKind` 表示**哪个订阅条件成立了**，比如"L2 down 了"或"si-1 的速率连续 60 秒低于 36 Gbps"。这是 telemetry 对**原始测量值**做的阈值判断，不是 behind、overrun 这类信号，也不是原因。telemetry 不知道我们的承诺、预留和截止时间。
- 图 B 从告警里**只读三样东西**：`kind`（链路告警还是 flow 告警）、`link_id` / `flow_id`（检查哪些承诺），以及"这些链路要强制重新拉取"。`measured_gbps`、`threshold_gbps`、`start` / `end` 都没有用到。是否偏差、原因是什么，都是重新拉 `LinkSample` 和 `FlowProgress` 后由我们自己算。这样即使告警不准、迟到或重复，结论也不会错，最多是多检查一次。
- **现在的使用情况**：图 B 的入口已经能处理 `TelemetryAlert`。`Subscribe` 只有格式和 mock（`MockAlerts.poll` 按订阅条件模拟 telemetry 的推送，只在测试里用），**没有接进流程**：没有代码生成订阅、发送订阅，也没有代码接收推送。
- **应该怎么用**（建议）：
  1. **commit 之后**（图 A 的 commit，以及 modify、reroute 改了 circuit 之后），network agent 为每个承诺生成订阅：
     - 路径上每个 hop 订阅 `link_down` / `link_up`；
     - 每个 hop 订阅 `link_capacity_below`，阈值 = 我们在这个 hop、这段时间内订的量，时间范围 = 预留的时间段；
     - 传输本身（SENSE instance id）订阅 `flow_below_rate`（阈值 ≈ 预留速率 × (1 − 容差)）、`flow_stalled`、`flow_finished`。
  2. telemetry 持续检查这些条件，条件**刚成立**时推一条 `TelemetryAlert`，条件解除之前不重复推送（mock 就是这样实现的）。
  3. network agent 这边有一个接收端，收到告警就调用一次图 B。
  4. release 或到期后取消订阅；预留变化后更新阈值。
- **还缺的部分**：发送 / 接收订阅的通道（目前是 hook），**取消订阅的消息格式**（schemas 里还没有），以及"commit 后生成订阅"的代码。这些都需要和 telemetry 负责人对齐后再做。

**3. Tick 只在 network agent 内部用，和 telemetry 无关**

- 格式：`schemas.Tick`，只有一个字段 `kind = "tick"`，没有其他内容。
- 用法：network agent 自己的定时器每隔 N 秒发一个 Tick，调用一次图 B，检查**全部**承诺。这时只刷新已经过期的观测（`valid_until` 已过）。
- 和告警 / 订阅的关系：两者是**互补**的，Tick 不经过 telemetry。告警让问题被**更快**发现，Tick 保证告警丢了、没订阅、或 telemetry 不支持某种告警时，问题也**一定**会被发现。
- 现在还没有定时器，间隔 N 也不在 config 里。将来实现时，N 必须放进 config。

**4. 基本是这个意思，但有三个前提**

代码：`late = started_at > profile[0].start`，也就是第一个字节晚于预留开始时间（例如预留 9:00 开始，10:00 才开始传）。

1. **晚开始本身不算偏差。** behind 是从**实际开始时间**算"应传多少"，所以晚开始不会被判为 behind。只有当剩下的字节在预留剩余时间里**传不完**（overrun）时，才会成为偏差。
2. **链路有问题时，原因优先报链路。** 只有路径上没有找到损坏的 hop 时，原因才是 late_start；如果同时有 hop down 或拥塞，原因报 link_down / congestion。
3. 9:00 是**我们预留的开始时间**（在用户给的时间窗口内放置的），不一定是用户亲口说的时间。

late_start 的修复只用 extend / raise_rate / reroute，**不用 borrow**：不能让别人为用户自己的晚开始买单。

---

> 1. TelemetryAlert中的measured_gbps只针对两种below场景对吗？threshold_gbps是谁确定的，怎么确定的？
> 2. Tick和TelemetryAlert走的流程是一模一样的，都是走runtime graph？只不过触发途径不同？
> 3. 对于Tick，是怎么刷新从telemetry agent得到的观测的？毕竟观测如果陈旧，tick就没用了。

**1. 对，只针对 `link_capacity_below` 和 `flow_below_rate`**

- schema 里这两种告警**必须**带 `measured_gbps`（实测值）和 `threshold_gbps`（阈值）；其他四种不需要。不过校验并没有禁止其他告警带这两个字段，严格说是"只对这两种有意义"。
- **阈值由 network agent 决定**，写在 `Subscribe.threshold_gbps` 里发给 telemetry；告警里的 `threshold_gbps` 只是把订阅时的阈值原样带回来。telemetry 不决定阈值。
- 怎么定：
  - `link_capacity_below`：`Subscribe` 的说明里已经定了——**我们在这条链路、这段时间内订的量**。可用容量（不含我们）低于它，就说明链路给不出我们订的量。我们在这条链路上的预留变了，订阅就要更新。
  - `flow_below_rate`：代码里**还没定**。建议用 预留速率 × (1 − `progress_lag_tolerance`)，和 behind 用同一个容差。测试里写死的 36 就是 40 × 0.9。
- 因为 `Subscribe` 还没接进流程，现在**没有代码计算阈值**。以后应该由生成订阅的代码，从账本（我们订的量）和 config（容差）算出来，不能写死。

**2. 对，走同一张图，只是触发方式和检查范围不同**

两者都调用同一个 `build_runtime_graph().invoke(...)`，经过同样的节点。差别只在第一步 `classify_event` 里的 `commitments_for_event`：

| | Tick | 链路告警 | flow 告警 |
|---|---|---|---|
| 检查哪些承诺 | 全部 | 经过这条链路的 | 这个 flow 的 |
| 链路观测怎么刷新 | 只刷新过期的 | 告警涉及的链路强制重新拉取，其余过期的也刷新 | 该 flow 路径上的链路强制重新拉取 |

从 scan_path 开始逻辑完全相同。唯一的区别是：Tick 已经检查了全部承诺，所以 scan_path 的"扩大范围"不会再加入新的。

**3. Tick 怎么刷新观测：flow 进度每次都是新的，链路观测看有效期**

两类观测的处理方式不同：

- **flow 进度（`FlowProgress`）：每次都重新拉取，不缓存。** `find_deviations` 对每个承诺都调用 `ctx.flows.progress(...)`。所以 behind、overrun 这两个 flow 层信号在每次 Tick 都是最新的，Tick 不会因为观测陈旧而完全失效。
- **链路观测（`LinkSample`）：存在账本里，过期才重新拉取。** 每次 Tick 的流程：
  1. `find_deviations` 对每个承诺取一段 (路径, 实际开始时间或 now, 预留结束时间)，交给 `refresh_stale`。
  2. `refresh_stale` 找出这些路径上 `valid_until ≤ now` 的账本时间片（`ledger.is_stale`），**合并成一次** `telemetry.link_samples(...)` 拉取，写回账本。
  3. 到了 scan_path，`assess_all` 再按 (路径, now, 截止时间) 刷新一次过期的时间片，因为修复可能会用到预留结束之后的时间。
- **`valid_until` 由 telemetry 决定**：每个 `LinkSample` 自带有效期。mock 是 now + `validity_seconds`，测试里设为 300 秒。
- **局限**：在有效期内，即使链路其实已经变了，Tick 也会沿用账本里的旧值。这时 flow 层信号还能发现问题（会落后），但定位到某个 hop 的那部分（link 层信号和 link_down / congestion 原因）要等观测过期或收到告警才能更新。所以 Tick 间隔要和 telemetry 给的有效期一起考虑：Tick 比有效期短很多时，多出来的 Tick 只更新了 flow 进度。这是需要和 telemetry 对齐的一点（有效期给多长）。

---

> 1. 所以Tick对于flow进度都会问本地的network？在真实情况下，network agent似乎不应该有network的备份，而是应该直接去问telemetry agent吗？

**对，真实部署时就是直接问 telemetry agent。现在问的是"本地 network"，只是因为测试里用 mock 代替了 telemetry。**

- network agent 的代码**只依赖接口，不依赖 network**。`find_deviations` 调用的是 `ctx.flows.progress(...)`，`ctx.flows` 的类型是接口 `FlowSource`。链路观测走的也是接口：`ctx.telemetry`（`TelemetrySource`）。背后具体是谁，由创建 `AgentContext` 时传入什么决定。
- 测试里（`tests/helpers.make_ctx`）传的是 `MockFlows(net)` 和 `MockTelemetry(net)`，它们从模拟网络 `MockNetwork` 读数据。`MockNetwork`（`src/sim/`）是**代替真实世界**的模拟器（数字孪生的替身），不是 network agent 持有的网络备份。它扮演"真实网络 + telemetry 测量"的角色，network agent 自己读不到它，只能通过接口间接拿到数据。
- 真实部署时，把这两个 mock 换成去问 telemetry agent 的实现，例如 `TelemetryAgentFlows.progress` 发请求给 telemetry agent，返回 `FlowProgress`。图 B 的代码不用改。`MockAlerts` 同理，会换成接收 telemetry 推送的接收端。
- network agent 本地**确实**保留的东西，不是网络的备份，而是：
  - **账本（`ledger`）**：我们自己订的量（own），加上从 telemetry 拿到的链路观测的**缓存**（observed，带 `valid_until`）。缓存是为了查询和预留时不用每次都问 telemetry，过期就重新拉取。
  - **`progress_seen`**：每个传输的**上一次**进度读数，只用来和这次读数相减，算出最近的速率（`recent_gbps`）。flow 进度本身不缓存，每次都重新问。
- 所以：flow 进度每次都实时问 telemetry；链路观测问 telemetry 后在账本里缓存到 `valid_until`。

---

> 为什么flow直接问telemetry agent，link却是问ledger？这种不对称设计是怎么考虑的

先纠正一点：**两者的数据都来自 telemetry**。区别只在 link 观测拉回来后**缓存在账本里**，flow 进度不缓存。也就是 link 是"先 `refresh_stale` 把过期的部分从 telemetry 拉回账本，再读账本"，flow 是"每次直接问"。PLAN 和笔记里没有单独写下这个理由，下面是从代码和数据的性质看出的考虑：

| | link 观测（`LinkSample`） | flow 进度（`FlowProgress`） |
|---|---|---|
| 谁用 | 图 A（query / reserve / modify 的放置搜索）**和**图 B | 只有图 B |
| 读取量 | 大：放置搜索要扫多条候选路径 × 每个 hop × 未来几小时的每个时间片，一次查询就要读很多次 | 小：每个承诺每次检查读一次 |
| 描述的时间 | 一段时间，**包括未来**（数据源"目前认为"的未来可用容量，例如别人已登记的预留） | 只有**现在**这一刻 |
| 变化速度 | 相对慢，数据源用 `valid_until` 说明能信多久 | 一直在变：传输进行时 `bytes_sent` 每秒都在涨，缓存的值读出来就已经过时 |
| 要和什么一起用 | 必须和**我们自己订的量**合起来才能得到可用容量：available = observed − own。own 本来就在账本里，按 链路 × 时间片 组织 | 只和这个承诺的预留比较，不进容量核算 |

所以：

- **link 进账本**，是因为它本身就是容量核算的一部分（observed 和 own 必须放在同一张 链路 × 时间片 表里），读取量大，而且有明确的有效期，缓存划算、也安全。图 A 从第 3 步开始就是这样设计的，图 B 直接沿用。
- **flow 不缓存**，是因为它只有"现在"才有意义，又一直在变，缓存不会省下什么，反而一定是旧的。它也没有 链路 × 时间片 的结构，放不进账本。本地只留 `progress_seen`（上一次读数），用来算最近速率，不是缓存。

**这种设计的代价**就是上一问提到的：链路在有效期内变了，Tick 看不到，要等过期或收到告警（告警会强制重新拉取）。如果这个延迟不可接受，可以让 telemetry 给更短的 `valid_until`，或者让 Tick 也强制刷新正在用的链路（这样会多一些 telemetry 调用）。这是设计取舍，目前选的是前者：靠 telemetry 给的有效期加告警。

---

> 是否会出现这样的情况：TelemetryAlert都过来了，network agent本地的legdger的link还在有效期内，结果发现不了问题？

**主要情况下不会：告警会无视有效期，强制重新拉取。** `commitments_for_event` 对告警返回一组"强制刷新的链路"（`force_refresh`），`refresh_stale` 对这些链路**不看 `valid_until`**，在相关承诺的时间段上全部重新拉取：

- 链路告警：告警的链路，在**所有**经过它的承诺的 [实际开始或 now, 预留结束) 上强制刷新。
- flow 告警：该 flow 路径上的**每个** hop，在它的 [实际开始或 now, 预留结束) 上强制刷新。

所以"告警到了但账本里还是旧值"在检测范围内不会发生（测试 `test_step7_classify` 覆盖了这一点）。

**但有三个边缘情况（从代码推断，还没有专门的测试）：**

1. **强制刷新只到预留结束为止。** scan_path 的 `assess_all` 会把范围延长到截止时间（latest_finish），但那段**只刷新过期的**，不强制。所以预留结束到截止时间之间，告警链路上仍在有效期内的旧值会被沿用。**检测不受影响**（偏差只看预留内的时间片），但 `finish_if_kept` 的预测和 extend / raise_rate 这类需要用到预留之后时间的修复，可能基于旧值做决定。最坏情况是修到一段其实已经坏了的时间里，要等下一次检查再发现。
2. **flow 告警扩大范围时不强制。** flow 告警只强制刷新这一个承诺的时间段。scan_path 把同一坏 hop 上的其他承诺拉进来时（`find_deviations_on_damaged_hops`）不带强制刷新，所以它们超出前一个承诺时间段的部分，如果还在有效期内，用的是旧值。（链路告警没有这个问题，因为它一开始就覆盖了所有经过该链路的承诺。）
3. **telemetry 自身前后不一致。** 我们不使用告警里的 `measured_gbps`，而是重新拉 `link_samples` 来判断。如果 telemetry 的告警基于比 `link_samples` 更新的数据（例如采样接口有延迟），重新拉回来的还是旧数据：链路告警可能什么都查不出，flow 告警则可能被归为 unlocated。这需要和 telemetry 约定：告警发出时，`link_samples` 必须已经反映触发告警的那次测量。

**建议的修法（还没改，等你决定）**：把告警的强制刷新范围从"到预留结束"延长到"到截止时间"，并让 scan_path 扩大范围时沿用同一组强制刷新的链路。这样 1 和 2 都能解决，代价是告警时多拉一些时间片。

---

> "。告警一到，就会无视有效期，强制重新拉取。commitments_for_event 会针对告警算出一组需要强制刷新的链路。refresh_stale 刷新这些链路时不看 valid_until，直接重新拉取"体现在代码哪个位置

调用链从图 B 的第一个节点往下，共四处：

1. **入口**：`src/graphs/runtime/runtime.py:79`，`classify_event` 调用 `find_deviations_for_event(runtime.context, event, state["now"])`。
2. **算出要强制刷新的链路**：`src/runtime/deviation.py` 的 `commitments_for_event`，它返回 (要检查的承诺, 要强制刷新的链路)：
   - 第 133 行，Tick：`return every, set()`，强制刷新集合为空；
   - 第 136 行，flow 告警：`return hit, {该 flow 路径上的所有链路}`；
   - 第 140 行，链路告警：`return hit, match & {...}`，即告警的那条链路（物理 id 会匹配两个方向）。
3. **往下传**：
   - `deviation.py:145–146`，`find_deviations_for_event` 拿到 `force_refresh`，交给 `find_deviations`；
   - `deviation.py:169–172`，`find_deviations` 调用 `refresh_stale(..., now, force=force_refresh)`，时间段是每个承诺的 [实际开始或 now, 预留结束)。
4. **不看有效期的那一行**：`src/adapters/telemetry.py:64`

   ```python
   if link in force or ledger.is_stale(link, i, now):
   ```
   链路在 `force` 里，就直接标记为要拉取，`or` 后面的有效期检查（`is_stale`：`valid_until <= now`）根本不会执行；不在 `force` 里的才按有效期判断。标记出的时间片在第 66–69 行合并成一次 `link_samples` 调用，写回账本。

---

> 解释find_deviations_for_event->commitments_for_event->find_deviations这三个函数在干什么

三者是分工关系：**`commitments_for_event` 定范围，`find_deviations` 做检查，`find_deviations_for_event` 把两者接起来。**（都在 `src/runtime/deviation.py`）

**1. `find_deviations_for_event(ctx, event, now)`：入口，只做衔接**

只有两行：先用 `commitments_for_event` 算出"查哪些承诺、强制刷新哪些链路"，再交给 `find_deviations`。图 B 的 `classify_event` 调用它。之所以单独拆出 `find_deviations`，是因为 scan_path 的 `find_deviations_on_damaged_hops` 也要用同一套检查，只是范围来源不同（来自已发现的坏 hop，而不是事件）。

**2. `commitments_for_event(ctx, event)`：根据事件定范围**

返回 (要检查的承诺, 要强制刷新的链路)。只看 `ctx.committed()`，也就是已 commit 的承诺：

| 事件 | 检查哪些承诺 | 强制刷新哪些链路 |
|---|---|---|
| Tick | 全部 | 无（只刷新过期的） |
| flow 告警 | `instance_id == flow_id` 的那个承诺 | 它路径上的所有链路 |
| 链路告警 | 路径经过该链路的所有承诺（物理 id 两个方向都算） | 告警的那条链路 |

**3. `find_deviations(ctx, commitments, now, force_refresh)`：真正的检查**

对每个承诺依次做：

1. **读进度**：`ctx.flows.progress(instance_id, now)` 实时问 telemetry。已传完的跳过，不检查。
2. **刷新链路观测**：所有承诺一起调用一次 `refresh_stale`。时间段 = [实际开始时间（没开始就是 now）, 预留结束)；`force_refresh` 里的链路不看有效期。
3. **算两个 flow 层信号**（容差都是 config 的 `progress_lag_tolerance`）：
   - **behind**：`due_bytes` 按预留的速率安排，从**实际开始时间**积分到 now，得到"应传字节"；落后超过容差就是 behind。
   - **overrun**：剩余字节和"预留从 now 到结束还能传多少"比较，多出超过容差就是 overrun。只对已开始的传输判断。
4. **记下这次读数**：和上一次读数（`progress_seen`）相减得到最近速率 `recent_gbps`，然后把这次读数存起来，供下次用。
5. **找链路层损坏**：`damaged_slots` 遍历这个承诺订过的每个时间片、路径上的每个 hop，找出 down 或观测容量 < 我们订的量（`observed < own`）的地方。
   - 如果**没有** behind / overrun，只保留**还没结束**的损坏时间片：过去的损坏只用来解释落后，传输没落后就不用管。
6. **判断是否偏差**：behind、overrun、有损坏，三者都没有就跳过。
7. **定原因**（按优先级）：有 hop down → `link_down`；有损坏但 hop 都 up → `congestion`；没有损坏但晚开始 → `late_start`；都不是 → `unlocated`。
8. **记下坏的 hop**（按路径顺序），组装成 `Deviation`。

返回 `Detection`：偏差列表、检查过的承诺 id（`checked`，scan_path 用它避免重复检查）、刷新过的链路（`refreshed`）。

**例子**：cmt-1 预留 09:00–11:46:40、40 Gbps（每小时 18 TB），共 50 TB。L2 从 09:59 开始 down，10:00 收到 L2 的 `link_down` 告警。

- `commitments_for_event`：经过 L2 的只有 cmt-1 → 检查 [cmt-1]，强制刷新 L2。
- `find_deviations`：
  - 进度：09:00 开始，已传约 17.7 TB；应传 18 TB，只落后 0.3 TB（不到 10%）→ 不是 behind。
  - 剩余 32.3 TB，预留从 10:00 到结束还能传 32 TB，只多出 0.3 TB → 不是 overrun。
  - 强制刷新后，账本显示 L2 在 10:00 之后的时间片 down → 有损坏，原因 `link_down`，坏的 hop 是 L2。
- 结果：只靠链路层信号，在传输明显落后**之前**就发现了偏差。

---

> deviation的粒度是一个link吗，为什么属性里是links？

**不是。`Deviation` 的粒度是一个承诺（commitment）**：每个偏离的承诺对应一个 `Deviation`，用 `commitment_id` 标识。`links` 是**这个承诺的路径上所有坏掉的 hop**，所以可能有多个。

三层粒度：

| 字段 | 粒度 | 内容 |
|---|---|---|
| `Deviation` 本身 | 一个承诺 | 一个承诺一条 |
| `links` | 这个承诺路径上的 hop | 坏掉的 hop，按路径顺序，去重；unlocated / late_start 时为空 |
| `damage` | (hop, 时间片) | 每个 `SlotDamage` 是"某个 hop 在某个时间片给的容量比我们订的少，或者 down 了"，按时间再按路径顺序排列 |

例子：cmt-1 的路径是 L1 → L2 → L3，L2 在 10:00–10:30 down，L3 在 11:00–11:30 拥塞。结果只有**一个** `Deviation`：
- `cause = link_down`（有 down 就优先报 down）
- `links = (L2, L3)`
- `damage` = L2 在 10:00–10:30 的各个时间片 + L3 在 11:00–11:30 的各个时间片

反过来，如果 L2 坏了，而经过 L2 的承诺有 3 个，就会有 3 个 `Deviation`，每个的 `links` 里都有 L2。

**为什么按承诺而不是按 link：** 后面的每一步都以承诺为单位——预测（这个承诺剩下的字节能不能按时传完）、triage、修复（改的是这个承诺的预留）、上报（`DeviationReport` 给 scheduling agent，对方关心的是自己的传输）。link 只是"原因在哪"，作为承诺的属性带上即可。

**一个要注意的地方**：`cause` 每个承诺只有一个。上例中 L3 的拥塞不会体现在 `cause` 上，只保留在 `links` 和 `damage` 里。

---

> FlowSource.progress是在哪个步骤被需要调用telemetry agent的？scan path吗？指出代码

**整个包里只有两处调用 `ctx.flows.progress`，分布在图 B 的三个节点里：**

| 调用位置 | 被哪个节点用到 | 问的是谁的进度 | 用来干什么 |
|---|---|---|---|
| `src/runtime/deviation.py:165`，在 `find_deviations` 里 | **classify_event**（经 `find_deviations_for_event`，事件涉及的承诺）和 **scan_path**（经 `find_deviations_on_damaged_hops`，只问扩大范围后**新加入**的承诺） | 被检查的承诺 | 判断是否传完、算 behind / overrun、算最近速率 |
| `src/runtime/repair.py:318`，`_remaining_bytes` | **execute_repair** 里的 borrow：第 342 行（借之前看借出方还剩多少）、第 324 行 `_lender_result`（借完后预测借出方的完成时间） | **借出方**（被降速的低优先级承诺） | 借出方剩余字节 = 总字节 − 已传字节 |

所以：

- **主要调用点在 classify_event**，每个被检查的承诺问一次。
- **scan_path 只对新加入的承诺调用**。已经检查过的承诺，进度已经包含在 `Deviation.progress` 里，scan_path 的预测（`assess_all`）直接用它，不再问 telemetry。
- **execute_repair 只在 borrow 时调用**：借出方本身没有偏差，没有被检查过，手上没有它的进度，所以要现问。

triage、plan_local_repair、report_deviation 都不调用。

---

> ctx.flows.progress其实是实时去问telemetry agent吗

**设计上是，现在的代码里还不是。**

- **现在**：`FlowSource`（`src/adapters/telemetry.py:75`）只是一个接口，整个包里**唯一的实现是 `MockFlows`**（第 82 行），它读的是模拟网络 `MockNetwork.flow_trace`，`sampled_at` 直接填 now。没有任何代码去连 telemetry agent。
- **设计上**：部署时写一个真正的 `FlowSource` 实现，在 `progress(instance_id, now)` 被调用时**同步**向 telemetry agent 发请求，等它返回一个 `FlowProgress`。这是拉取（pull），不缓存，所以"每次检查都问一次"。`FlowProgress` 的格式和 `flow_id` 用什么标识（目前用 SENSE instance id）都还是暂定，需要和 telemetry 对齐。

**"实时"要打个折扣**：问是实时问的，但 telemetry 返回的是它**最近一次测量**的值，测量时间是 `sampled_at`，可能比 now 早几秒甚至更多。

**由此发现一个问题（还没改，等你决定）**：`find_deviations` 计算"应传字节"（behind）和"预留剩余能传多少"（overrun）时用的是 **now**，而 `bytes_sent` 是 `sampled_at` 时刻的值。telemetry 的测量有延迟时，会把这段延迟误判为落后。例如 40 Gbps 的传输，测量延迟 30 秒，就会多出 150 GB 的"假落后"。mock 里 `sampled_at = now`，所以测试没有暴露这个问题。修法：behind 和 overrun 都改成以 `p.sampled_at` 为时间点计算（`recent_rate` 已经是用 `sampled_at` 算的）。

另外，链路观测是所有链路合并成一次 `link_samples` 调用，flow 进度却是**每个承诺调用一次**。承诺多时，Tick 会对 telemetry 发 N 次请求。以后对接时可以考虑批量接口（一次传多个 flow_id）。

---

> FlowProgress中，相同flow的flow id和started_at是一致的吗？flow是path粒度还是link粒度？

**1. 同一个 flow 的 `flow_id` 和 `started_at` 都应该保持不变**

- `flow_id`：目前用我们的 **SENSE instance id**（暂定，待和 telemetry 对齐）。一个 instance 对应一个 circuit，所以同一个 flow 每次读数的 `flow_id` 都一样，图 B 也是用它找到对应的承诺（`commitments_for_event`、`ctx.progress_seen`）。
- `started_at`：**第一个字节开始传的时间**。还没开始时是 None；一旦开始就是固定的事实，之后每次读数都应该一样。中途卡住再恢复也**不会改变**它（mock 里取的是第一个速率大于 0 的时间点，`FlowTrace.first_byte`）。
- 注意：schema 只校验**单次读数**内部是否自洽（没开始就不能有已传字节；`started_at` 不能晚于 `sampled_at`），**不校验多次读数之间是否一致**。代码默认 telemetry 给的是一致的（behind 从 `started_at` 积分、`recent_rate` 用前后两次读数相减）。这一点要写进和 telemetry 的约定。
- **例外是 reroute**：换路径会建一个新的 SENSE instance，WMS 把剩下的传输切过去（mock 的 `switch_flow`）。这时对同一个承诺来说：
  - `flow_id` 变成新 instance id；
  - `started_at` 是切换后第一个字节的时间；
  - `bytes_sent` 从 0 重新计数。

  前后仍然一致，因为 reroute 时新的 reserved offer 的 `request.bytes` 已经改成剩余字节（`operations.open_circuit`），"剩余 = 总量 − 已传"照样成立。`progress_seen` 按 instance id 存，所以最近速率在新 flow 上从头算。承诺的 `commitment_id` 不变。

**2. flow 是 path 粒度（端到端），不是 link 粒度**

- 一个 flow = 一个传输在一条 circuit（SENSE instance）上的端到端数据流，覆盖整条路径。telemetry 可能在某个端口或端主机上测，但给我们的是**一个 flow 一个数字**（已传字节），不分 hop。
- 所以 flow 进度只能回答"这个传输整体慢没慢"（behind / overrun），回答不了"慢在哪个 hop"。定位到 hop 靠的是 link 粒度的 `LinkSample`（`damaged_slots`）。两者对不上——flow 慢、但所有 link 都正常——就是 `unlocated`。
- 以后做多路径（第 8 步）时，一个传输会拆成多条 circuit，就会对应多个 flow，每个仍是各自路径的端到端粒度。

---

> bytes sent是数据已经发出去，还是数据已经被收到？

**现在没有定义，这是一个需要和 telemetry 对齐的空白。**

- schema（`FlowProgress`，暂定）只写了"已经传了多少字节"，没有说是发送端发出的，还是接收端收到的。
- mock 里两者没有区别：`MockNetwork` 按路径给的速率积分，没有传播时延、丢包和重传，发出即收到。

**真实网络里两者会有差别：**

1. **在途数据**：已发出、还没到达的部分，大约是 带宽 × 往返时延。例如 40 Gbps × 50 ms ≈ 250 MB。
2. **重传**：丢包时，发送端会把同一份数据再发一次。按"发出"计数会把重传也算进去，**高估进度**。
3. **测量位置**：如果 telemetry 在路径中间某个交换机端口测，得到的是介于两者之间的数。

**对我们的影响**：
- 在途数据相对 TB 级的传输和 10% 的容差很小，基本不影响判断。
- 重传影响比较大：丢包严重时，"发出"的字节数还在涨，实际送达的却很少。这时按发出计数可能**判断不出 behind**，传输到最后才发现赶不上。

**建议**：和 telemetry 约定为**接收端已收到（或已确认收到）的字节，不含重传**。截止时间承诺的是"数据在截止前到达"，所以送达量才是我们关心的。`flow_finished` 也应该表示数据全部送达。对齐之后，字段名可以从 `bytes_sent` 改成更准确的 `bytes_delivered`（需要你决定，目前没改）。

---

> 所以总的来说，telemetry只需要提供substribe()的接口，telemetryAlert的推送格式，以及progress()的接口以及FlowProgress的返回格式？

**基本对，但漏了一个，而且漏的是最重要的：`link_samples()` 和它返回的 `LinkSample`。** 另外订阅还缺"取消 / 更新"。完整清单：

| # | 接口 | 方向 | 格式 | 现状 | 优先级 |
|---|---|---|---|---|---|
| 1 | `link_samples(link_ids, start, end, now)` | 我们拉取 | `LinkSample` | 图 A 从第 3 步就在用，图 B 也靠它定位坏 hop | 必需（已有） |
| 2 | `progress(flow_id, now)` | 我们拉取 | `FlowProgress` | 暂定，只有 mock | 必需 |
| 3 | `subscribe(...)` + **取消 / 更新订阅** | 我们发给 telemetry | `Subscribe`；取消的格式还没有 | 暂定，没接进流程 | 可选 |
| 4 | 告警推送 | telemetry 推给我们 | `TelemetryAlert` | 暂定，图 B 已能处理 | 可选 |

只靠 1 + 2，加上我们自己的 Tick，图 B 功能上就完整了。3 + 4 让问题被更快发现、检查范围更小，属于优化。

**每个接口要约定的语义**（格式之外更容易出错的地方）：

1. `LinkSample`：
   - `available_gbps` **不扣除我们自己的预留**，否则会被扣两次；
   - 未来时间段给的是数据源目前的估计（例如别人已登记的预留），不是流量预测；
   - `valid_until` 由 telemetry 给出，它决定了 Tick 能多快看到链路变化。
2. `FlowProgress`：
   - `flow_id` 用什么标识（目前是 SENSE instance id）；
   - `started_at` 在多次读数之间保持不变；
   - 字节数是**送达**的、不含重传；
   - `sampled_at` 是真实的测量时间；
   - 可以考虑批量接口，一次查多个 flow。
3. 订阅：
   - 阈值由我们给，我们的预留变化时要能更新或取消订阅；
   - 观测窗口（`min_duration_seconds`）用来防抖动。
4. 告警：
   - 条件刚成立时推一次，条件解除前不重复推；
   - 推送时，`link_samples` 必须已经反映触发告警的那次测量；
   - 推送通道是什么（消息队列、HTTP 回调等）。

**不需要 telemetry 提供的**：Tick（我们自己的定时器）、behind / overrun / 链路级三种信号、四种原因，这些都是我们自己算的。

---

> deviation的cause是怎么得出的？又有何用处？

**怎么得出（`src/runtime/deviation.py`）**

分两步，都在 `find_deviations` 里：

1. **每个损坏的时间片先有自己的原因**（第 56–57 行，`SlotDamage.cause`）：hop 是 down 的 → `link_down`；hop 是 up 但给的容量比我们订的少 → `congestion`。
2. **再合成承诺的原因**（第 195–198 行），按优先级取第一个成立的：

| 优先级 | 条件 | cause |
|---|---|---|
| 1 | 损坏里有任何一个 down | `link_down` |
| 2 | 有损坏，但都是 up | `congestion` |
| 3 | 没有损坏，且第一个字节晚于预留开始时间 | `late_start` |
| 4 | 都不是（落后或传不完，路径上却找不到问题） | `unlocated` |

前两种原因**在网络里**，能定位到 hop（`links` 非空）；后两种路径上没有问题（`links` 为空），其中 late_start 是用户自己的原因，unlocated 是原因不在路径上（例如端主机磁盘慢）。

**有什么用：决定后面每一步怎么处理**

| 用在哪 | 代码 | 作用 |
|---|---|---|
| 预测（scan_path） | `forecast.py:118`，`off_path_cap` | **只对 unlocated** 估一个速率上限：问题不在网络里，账本看不出来，就用实际观测到的速率（最近速率，或开始以来的平均速率）作为未来速率的上限，否则预测会过于乐观 |
| 决定修什么（plan_local_repair） | `repair.py:108–113` | unlocated 且仍然慢（有上限）→ **只试 extend**：加速率或换路径解决不了网络外的限制 |
| | `repair.py:121` | **只有 link_down / congestion 才能 borrow**：原因在网络里，才值得让低优先级的承诺让出速率；late_start 是用户自己的原因，不能让别人买单 |
| 去重（triage） | `repair.py:99` | 之前报过 unresolved，只有**原因和承诺都没变**才判为 already_reported；原因变了（比如从 congestion 变成 link_down）就重新处理 |
| 上报（report_deviation） | `repair.py:383–396` | `DeviationReport.cause` 告诉 scheduling agent 为什么出问题，报告按原因分组；`reported_unresolved` 也记下原因，供下次去重 |
| 以后（learning 图） | — | unlocated 的偏差留给 learning 图去归因 |

**一个细节**：目前 `link_down` 和 `congestion` 在修复上**没有区别**（两者都允许全部四种修法），区别只体现在上报里。late_start 没有速率上限，可以 extend / raise_rate / reroute，只是不能 borrow。

---

> flow的priority体现在哪个字段？谁设置的？borrow在哪体现了高优先级抢低优先级？

**1. 字段：`TransferRequest.priority`（`src/models/schemas.py:58`）**

- 非负整数，**越大越重要**。
- 粒度是**一个传输请求**，不是 flow。flow 只是这个传输在某条 circuit 上的数据流；reroute 后 flow 换了，priority 跟着请求走，不变。图 B 里通过 `Assessment.priority`（`forecast.py:54`）→ `reserved_offer.request.priority` 读取。

**2. 谁设置：scheduling agent**

它在 query 时把每个传输的 `TransferRequest`（含 priority）放进 `QueryRequest.bundle` 发给我们。network agent 只读不改。目前**只有图 B 读它**；图 A 的 query / reserve 还不看 priority（PLAN 里的待决项"跨 workflow 按 priority 预留"）。

**3. 高优先级怎么"抢"低优先级（`src/runtime/repair.py`）**

体现在三处：

1. **修复顺序**：`plan_all`（第 150 行）按 priority 从高到低排序，`execute` 按这个顺序修，所以高优先级先拿到空闲容量。
2. **谁能被借**：`_lenders`（第 304–314 行）挑出满足以下条件的承诺：
   - priority **严格低于**要修的承诺（第 309 行）；
   - 和它共用至少一个 hop；
   - 预留时间和 [now, 截止时间) 有重叠；
   - 不在 `cannot_lend` 里：本轮也在修的、或已报 unresolved 在等 scheduling agent 决定的，都不能借。

   按 priority **从低到高**排（第 314 行），最不重要的先借。
3. **怎么借**：`borrow`（第 329–371 行）对每个借出方：
   - 速率**一次降一档**（`lower_rates`，第 347 行）；
   - 每降一档，用 `_placement_through_by` 检查借出方**仍能在它自己的截止时间前传完**（第 350 行），不行就停，不再往下降；
   - 用 `_try_modify` 真的改掉借出方的预留（第 353 行）。这一步就是"抢"：借出方在共用 hop 上订的量减少，账本里空出容量；
   - 然后让高优先级的承诺**重新试 extend 和 raise_rate**（第 357–360 行），用上刚空出的容量。成功就返回，借出方也作为一条 `action="lend"` 的结果上报；
   - 全部借完都没用，就把借出方**改回原样**（第 364–368 行）。

**注意：这不是真正的抢占。** 借出方必须仍能按时完成，所以只是**拿走它的余量（slack）**，不会让它变成 unresolved。真正的抢占（牺牲低优先级、让它赶不上截止时间）还没做，PLAN 的第 7 步空白 ⑥ 里记着。借用也是贪心的：从最低优先级开始、每次降一档、够用就停，不做全局最优（空白 ③）。

---

> Deviation的due_bytes是啥？不能直接从progress中得到吗？

**`due_bytes` 是"按我们的预留，到现在应该传完多少字节"，`progress.bytes_sent` 是"实际传了多少"。** 一个是应该传的，一个是实际传的，两者相减才知道落后多少（`Deviation.lag_bytes = due_bytes − progress.bytes_sent`）。

**不能从 progress 得到**：progress 来自 telemetry，只有实际值（开始时间、已传字节）。"应该传多少"取决于**我们的预留**，telemetry 不知道，只能由我们自己算：

- 计算：`due_bytes(rate_profile, started_at, now, 总字节)`（`deviation.py:94`）。把承诺的速率安排（`commitment.rate_profile`）从**实际开始时间**积分到 now，最多不超过总字节。
- 从实际开始时间算起，所以晚开始不会被误判为落后；还没开始时为 0。

例子（`test_step7_classify.py:57`）：预留 40 Gbps（每小时 18 TB），09:00 开始，10:00 检查时：
- `due_bytes` = 18 TB（应该传的）
- `progress.bytes_sent` = 13.5 TB（实际传的）
- `lag_bytes` = 4.5 TB，超过 18 TB 的 10% → behind

**它存在 `Deviation` 里有什么用**：behind 已经在 `find_deviations` 里用它算出来了。之后的步骤（预测、triage、修复、上报）**都不再读 `due_bytes` / `lag_bytes`**，目前只有测试和演示打印在用，用来说明"为什么判为 behind"。如果你觉得多余，可以从 `Deviation` 里去掉，只保留 `behind`。

---

> 更准确的说，一个deviation的粒度其实是一个commit下的一个reservedoffer？

**对，基本就是这样。** 这里的 "commit" 指一个已 commit 的 `Reservation`（一次 reserve 的一组 offer，整组 commit），不是单个承诺。层级是（`src/context/context.py`）：

```
Reservation（reserve_id，一次 reserve，可含多个 offer，整组 commit / release）
 └── ReservedOffer × N（每个对应一个传输：账本 booking、SENSE instance、placement）
       └── commit 时每个 reserved offer 生成一个 Commitment（Reservation.commitment_ids: offer_id → commitment_id）
```

`Committed` 就是把这三者绑在一起：`(commitment, reserve_id, reserved_offer)`。`ctx.committed()` 对每个已 commit 的 reservation 里**还没 release 的**每个 reserved offer 返回一个 `Committed`。一个 `Deviation` 对应一个 `Committed`，所以：

> 一个 Deviation = 一个已 commit 的 reservation 里的一个 reserved offer = 一个 commitment = 一个传输在一条 circuit 上（一个 flow）

**一点补充**：标识用的是 **`commitment_id`**，不是 reserved offer。因为修复时 reserved offer 会**被替换**（modify 改了 placement，reroute 换了 booking、SENSE instance 和 VLAN；见 `operations.record_change`），而 `commitment_id` 保持不变。所以更准确地说，Deviation 的粒度是"一个 commitment，以及它**当前**的 reserved offer"。triage 去重、上报、`reported_unresolved` 都按 `commitment_id` 记录，就是为了修复前后能对得上。

---

> 如果要往当前架构中加入LLM的决策，在graph中的哪些node加，或者新增nodes？

**原则：LLM 只在"选择"上做决定，算数和改状态都留给确定性代码。** 具体是：

- 选项由代码生成，LLM 只能从中选，选完由代码校验；
- 执行（账本、SENSE）仍由代码完成，失败就回滚；
- LLM 出错、超时或给出非法输出时，退回规则版。

按这个原则，现有架构已经留好了位置，**不需要改图结构**：

**1. 首选：图 B 的 `plan_local_repair` 节点**

- 写一个 `LLMPolicy`，实现 `RuntimePolicy.plan_local_repair`，传给 `build_runtime_graph(policy)`，图不用改。
- LLM 决定"试哪些修法、按什么顺序"。代码先用规则算出**允许的**修法（剩余字节在截止前能否传完、unlocated 只能 extend、late_start 不能 borrow），LLM 的输出必须是它的子集。
- 为什么选这里：这是真正需要权衡的地方——换路径还是等、借谁的、要不要动别人。能利用的上下文多（优先级、原因、历史、其他承诺），而且执行有回滚兜底，LLM 选错了最多是修不好，不会破坏状态。

**2. 不建议给 LLM 的节点**

- `classify_event`、`scan_path`：都是数值计算（积分、比较、预测），规则准确又便宜。
- `triage`：核心判据"能否在预留内传完"是算出来的；"已报过且没变化"是精确比较。LLM 在这里没有优势。（`RuntimePolicy.triage` 接口在，真想换也可以，但不推荐。）
- `execute_repair`：会改账本和 SENSE，必须是确定性的。

**3. 新增节点：放在图 C（learning），不放在图 B**

PLAN 第 10 步就是"第一个 LLM 接入点：有证据的诊断 + 选下一次 probe，与规则版对比"，对应第 9 步图 C 的 `attribute_cause` 节点（join_records → attribute_cause → calibrate → plan_adjustments → apply）。

最适合 LLM 的问题是 **unlocated 的归因**：路径上看不出问题，需要结合端主机、历史记录、其他 flow 来推断原因，并决定下一步去测什么（probe）。这种开放性的诊断规则写不全。放在图 C 而不是图 B，是因为图 B 要快速响应，诊断可以离线慢慢做。

**4. 可选：`report_deviation` 加一段自然语言说明**

给 scheduling agent 或人看的原因解释。风险最低，但价值也最低，可以放到最后。

**图 A**：目前没有策略接口，放置是规则搜索（earliest_start / max_rate / min_rate）。以后可以把"给 scheduling agent 提供哪些 offer"抽成一个策略，但不是第一步。

**工程上要准备的：**

- LLM 客户端作为适配器，放在 `src/adapters/`；模型、超时等参数放进 config。
- 策略代码按 PLAN 放在 `policies/`。PLAN 里写的路径是重组前的，按新结构应该是 `src/policies/`，在 `runtime` 之后、`graphs` 之前。要不要更新 PLAN，由你决定。
- 测试用 mock LLM，保证结果可复现。
- 记录每次 LLM 的输入和决策，供图 C 和"与规则版对比"使用。
- 注意延迟：图 B 每个事件都要走一遍，LLM 调用要有超时，超时退回 `RulePolicy`。

---

> 但目前priority没有体现出harvey的关于multi-worklfow建议对吗？

**对，只体现了一小部分。** 先核对出处（`resources/meetings/20261027_scinet_network_telemetry.md` 2.3、2.4、2.6 节）：

- **场景（2.3 节）**：已有 background traffic，先启动一个 transfer，再来一个，**按两者的 priority 决定分配**，例如按优先级分份额（60% / 40% 只是举例，不是定好的算法）。会议记录**没有写明是谁提的**。原始转写第 586–599 行看起来像同一人连续说的，后面接的正是 Harvey 的 hooks 建议，所以可能也是 Harvey，但记录没有确认。
- **Harvey 明确的建议（2.4 节）**：不要求马上实现，而是**把通向并发请求、优先级、重新分配、抢占、真实输入的 hooks 明确记录下来**，让 demo 既能展示现在能跑什么，也能说明怎样一步步变成真实系统。
- **调用链（2.6 节）**：Workflow Agent → Scheduling Agent → Network Agent。scheduler 汇总多个 workflow 的需求后再来请求，priority 也沿这条路径传过来。

**对照现状：**

| 建议的内容 | 现状 |
|---|---|
| 新 transfer **到来时**按 priority 分配 / 重新分配 | ✗ 图 A 的 query / reserve 不读 priority，先到先得：后来的高优先级只能用剩下的容量，已有的低优先级不会让 |
| 按优先级**分份额**（如 60/40） | ✗ 没有权重或份额的概念 |
| **运行中**容量下降时按 priority 取舍 | 部分 ✓ 图 B 先修高优先级的，并可向低优先级借余量（borrow）。但只在故障 / 拥塞时触发，不在新请求到来时触发 |
| 抢占（让低优先级赶不上） | ✗ 被借的必须仍能按时完成 |
| 记录 hooks | 部分 ✓ 分散在几处：`circuit.place_on_circuit` 的说明里写了 priority / preemption hook，`graphs/protocol/reserve.py` 也提到；PLAN 待决"跨 workflow 按 priority 预留"列了开工前要定的 4 个问题。但**没有一份集中的 hooks 清单**，这正是 Harvey 要的东西 |

**还有一个隐含假设要确认**：`_lenders` 比较 priority 时**不看 workflow**，默认不同 workflow 的 priority 可以直接比较（全局可比）。如果 priority 只在一个 workflow 内部有意义，跨 workflow 的取舍按 2.6 节应该由 scheduler 做，那么 borrow 跨 workflow 借就不对了。这属于 PLAN 待决里的第 ③ 个问题（与 scheduling agent 的分工），还没定。

**建议的下一步**：先整理一份集中的 **hooks 清单**（每个 hook：在代码哪里、现在怎么做、以后接什么），直接回应 Harvey 的建议，也正好用于 overview 汇报。真正实现"到来时按 priority 分配"之前，要先定 PLAN 待决里的 4 个问题，这些需要你和合作方决定。

---

> triage的already_reported就是一个去重的过程，能够放在even和classify_event之间？我的理解是这个图的调用是为每一个出问题的link调用，然后修复的是整个path。所以去重需要在triage阶段为path去重？

先纠正两处理解，再回答能不能前移。

**1. 图是按事件调用的，不是按 link 调用**

每来一个事件（一个 Tick 或一条告警）调用一次图 B。一次调用会处理这个事件涉及的**所有**承诺：一条 L2 的告警可能查出 3 个偏离的承诺，它们在同一次调用里一起预测、triage、修复、上报。

**2. 修复和去重的单位都是承诺（commitment），不是 path**

每个承诺修的是**它自己的** circuit（它当前的 reserved offer）。两个承诺即使走同一条 path，也是两个承诺、分别处理。

**3. already_reported 不是同一次调用内的去重，而是跨调用的去重**

- **同一次调用内本来就不会重复**：一个承诺只产生一个 `Deviation`；scan_path 扩大范围时用 `checked` 跳过已检查过的承诺。
- **already_reported 解决的是跨调用的重复**：某个承诺**上一次**调用已经报了 unresolved，scheduling agent 还没处理（承诺没变）。这次 Tick 或告警又查出它，如果原因也没变，就不再修、也不再报，避免每次 Tick 都重复上报同一件事。

**4. 为什么不能放到 classify_event 之前**

判断"是否已报过且没变"需要**这次**检查的结果：

- **原因**是 classify_event 算出来的。原因变了（例如从 congestion 变成 link_down）要重新处理。
- **能否在预留内传完**是 scan_path 算出来的。如果已经恢复（`finishes_in_reservation`），要把它从 `reported_unresolved` 里**删掉**（`repair.py` 的 `triage_all`），下次再出问题才会重新上报。
- 承诺是否被 scheduling agent 改过或 release 了，也是在 `triage_all` 开头检查的。

如果放在 classify_event 之前，只能看到"之前报过"，不知道现在是恢复了、原因变了还是没变，只能一律跳过，就会**漏掉恢复和原因变化**。

如果目的是**省掉重复的检查**：检查本身很便宜（读一次进度、刷新过期观测），真正要避免的是重复的修复和上报，而这正是 triage 现在做到的。

**另外，同一事件重复到达**（例如同一条告警推了两次）也不需要在入口去重：telemetry 约定条件解除前不重复推；就算重复了，也只是多检查一次，already_reported 保证不会重复上报。