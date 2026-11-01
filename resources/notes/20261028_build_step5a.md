第 5a 步：图 A 的 reserve / commit 分支。开工前先看了一遍项目结构的变化和 10/22、10/27 的会议记录，下面是设计方案，**待确认后再写代码**。

## 一、结构变化，以及之后写代码要遵守的约束


| 变化                                                                                        | 对写代码的影响                                                                          |
| ----------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------- |
| `src/lib/network_agent` 通过 `tools/` 下的脚本同步到 SciNetGenesis（`ucr/network_agent/`）和 kklab 仓库 | 代码注释和字符串**只用英文**；不能出现人名、会议、`PLAN.md`、`src.lib.` 这类私人信息。写完先跑 `scinet.sh check` 自查 |
| 测试改成了包内相对导入（`from ..schemas import`）                                                      | 新测试照这个写                                                                          |
| PLAN 移到了 `resources/other/network_agent/PLAN.md`                                          | 进度和待决都写在那里                                                                       |
| 推送 SciNetGenesis                                                                          | 由用户自己运行 `scinet.sh sync`，agent 只提交、推送本仓库                                         |


开工时的状态：91 个测试全部通过，`scinet.sh check` 通过。

10/22、10/27 会议里和 5a 有关的意见：

1. **KK 建议把** `foreign_traffic` **改叫** `background_traffic`（10/22）。代码里还没改，它出现在 schema 的 `blocked_by` 取值里。
2. **KK 指出代码和测试都出自同一个 agent，缺少独立验证**（10/22）。
3. **Harvey 建议把扩展点（hooks）明确写下来**（10/27），比如 priority、重新分配、抢占、接入真实输入。
4. **对外不要把 quote demo 说成已经有 hold/commit**（10/27）。5a 正好补上这部分。



## 二、5a 设计（建议）



### 图的形状：和原图有偏差

原图 A 让 hold/commit/modify/release 共用一套骨架：`validate_op → recheck → place_on_circuit → compile_intent → ledger_pending → sense_call → confirm/rollback`。

真正落到 SENSE 的两阶段流程上，这套骨架对不上，所以建议把 reserve 和 commit 拆成两条分支：

```
START → route_verb ─ quote   → （第 4 步的 quote 分支，不变）
                   ├ reserve → validate_reserve → recheck_capacity → place_on_circuit → compile_intent
                   │             → ledger_pending → sense_propagate ─ok──► record_reserve → respond
                   │                                               └fail─► ledger_rollback → respond
                   └ commit  → validate_commit → sense_commit ─ok──► ledger_confirm → respond
                                                              └fail─────────────────► respond
```

偏离原图的三处，原因如下：

- **选 circuit 和编译 intent 挪到了 reserve。** SENSE 的 propagate（即 hold）就要提交完整的 intent，创建实例；到了 commit 时只需要给实例 id。所以"放到哪个 circuit 上"必须在 reserve 时就定下来。
- **recheck 放在 reserve。** 账本是在 reserve 时预扣的，所以要在预扣之前刷新一次过期的观测值。slide 23 原本说的是"commit 前复查一次"，这一点是有意改的。
- **commit 失败时不回滚账本。** commit 失败后，SENSE 那边的资源仍处于 reserved 状态，scheduling agent 可以重试。只有 reserve 失败时才回滚。



### 几个具体决定

1. **一个 offer 对应一个 commitment，对应一个新建的 SENSE 实例。** 5a 不复用 warm circuit；复用放在 `place_on_circuit` 里作为一个写明的扩展点。目前的 offer 都是单一恒定速率，所以待决里那条"多段速率怎么对应到 intent"暂时不会出现。
2. **一次 reserve 是原子的。** 整组 offer 一起预扣、一起 propagate；只要有一个失败，就把已经 propagate 的取消、账本全部回滚，对应 slide 19 的 "one hold for the whole group"。
3. `offer_book` **里除了 placement，还要存原来的** `TransferRequest`**。** 生成 commitment 时要用到 `workflow_id`，所以第 4 步的代码和测试要做一点小改动。
4. `EndpointBinding.interface` **改成可选字段。** SENSE 只返回 VLAN，主机网卡名要由站点配置提供，mock 里先留空。
5. **TTL：** commit 时如果 reserve 已经过期，返回 `expired`。到期后自动回收放在 5b。
6. **扩展点用英文 docstring 标在对应的节点上：** 换备用路径兑现同一个 offer、复用 circuit、priority 和抢占。



### 待用户决定

1. 上面的图形状和偏差是否可以？确认后同步进 PLAN.md。
2. `foreign_traffic` 是否改成 `background_traffic`？建议在 5a 之前作为一个单独的小改动先改。改名会动到对外的 schema，越晚改，牵扯的同步越多。
3. 独立验证：是否由一个独立的 subagent，只看协议规格（schema 和 slides 里 reserve/commit 的语义）、不看实现代码，写一份 5a 的黑盒测试，再拿实现去跑它。它不能完全替代另一个人来写测试，但能部分回应"实现和测试同源"的问题。

---

> 1. 可以，并且同时修改resources/other/network_agent对应的html。 2. foreign_traffic 改成 background_traffic 3. 测试的问题先留作之后的任务，当前不做。 此外，你不要把代码一次性全写完。而是写一部分，告诉我改动位置，以及写了什么，等我审阅完之后，再写下一部分代码。我预计整体代码分成3-5部分写完，使得既不太多，又不太琐碎。你也可以按照你的节奏来，看每次写多少合适。

三个决定都已落实，这一部分（第 0 部分）只做准备工作，还没写 5a 代码：

- **改名**：`src/lib/network_agent` 里的 `foreign` 全部改成 `background`，包括 schema 中 `blocked_by` 的取值 `background_traffic`、`MockNetwork._background` / `add_background`、测试名和 demo 参数 `background_gbps`、demo 输出里的 "Background traffic"。纯改名，没有改逻辑，91 个测试全部通过。
- **图**：`visuals/protocol-graph-a.html` 改成 quote / reserve / commit 三条并列分支，下拉框可以单独看某一条；斜体标出扩展点，底部写明和初稿的三处偏离、5b 的范围。`protocol_graph_a.html`（独立打开的版本）把新图嵌进原来的外壳，外壳本身不动。
- **PLAN.md**：新增"来自 10/22、10/27 会议的修订"和"5a 对原图 A 的偏离"两节；5a 那一行改为新的图形状，状态改为进行中；待决里补上了 5a 对两条旧待决（备选路径、多段速率）的处理，以及"独立验证留作之后"。

5a 代码打算分四部分写：

| 部分 | 内容 | 主要改动 |
|---|---|---|
| A | 数据底座：`offer_book` 同时存 placement 和原 `TransferRequest`；context 加 SENSE adapter、reserve 表、commitment 表；`EndpointBinding.interface` 改为可选 | `context.py`、`schemas.py`、`graphs/protocol.py` 的 quote `respond`、step 4 测试 |
| B | reserve 分支：validate_reserve → … → record_reserve / ledger_rollback → respond | `graphs/protocol.py`、`tests/test_step5a_reserve.py` |
| C | commit 分支，加上 `route_verb`，把三条分支合成一张图 | `graphs/protocol.py`、`tests/test_step5a_commit.py` |
| D | demo：quote → 选 offer → reserve → commit，打印账本和 SENSE 实例的变化 | 测试文件里的 demo 部分 |

---

> 写A

A 部分是数据底座：把 reserve / commit 要用的东西放进 context，还没有新节点。92 个测试全部通过（新增 1 个）。

- `context.py`：context 里现在有三本账，后一本按 id 指向前一本：`offer_book`（offer_id → `QuotedOffer`）→ `reservations`（reserve_id → `Reservation`）→ `commitments`（commitment_id → `Commitment`）。
  - `QuotedOffer` = quote_id + 原 `TransferRequest` + `Placement`。存 request 是为了后面生成 commitment 时拿到 `workflow_id`；存 quote_id 是为了 reserve 时核对 offer 确实属于请求里那个 quote。
  - `Reservation` = reserve_id、quote_id、`items`、`expires_at`、`state`（reserved / committed）。每个 item 是一个 `ReservedOffer`：offer_id、账本 booking_id、发给 SENSE 的 intent、SENSE 实例 id、VLAN。intent 存下来，是因为 commit 时 `EndpointBinding` 的 src/dst URI 就取它的 terminals。
  - `AgentContext` 新增 `sense: SenseAdapter` 字段。
- `schemas.py`：`EndpointBinding.interface` 改为可选，默认 None。
- `graphs/protocol.py`：quote 的 `respond` 往 `offer_book` 写的是 `QuotedOffer`，不再只存 placement。
- 测试：`make_net` / `make_ctx` / `CountingTelemetry` 从 step 4 测试挪进 `tests/helpers.py`（5a 测试要第二次用到它们），`make_ctx` 加上了 `MockSense`；step 4 测试改成读 `offer_book[...].placement`，并检查存下来的 request 和 quote_id；step 1 新增 `interface` 可省略的测试。

---

> 我没懂QuotedOffer、ReservedOffer、Reservation在流程中所处的位置。scheduling agent发quote，network agent计算、查询后返回offer。这三个数据结构在哪？

三者都**不出 network agent**，scheduling agent 看不到。它们是 network agent 给自己记的账：每发出一条对外消息，network agent 就在 context 里留一份内部记录，记下对方看不到、但下一步要用到的信息。

| 阶段 | scheduling agent 收到的消息 | network agent 自己留的记录 | 记录里多出来的、下一步要用的信息 |
|---|---|---|---|
| quote | `QuoteResponse`，里面是若干 `Offer` | 每个 offer 一条 `QuotedOffer`，存进 `offer_book` | 走哪条 path、原始的 `TransferRequest` |
| reserve | `ReserveAck`（reserve_id、expires_at） | 一条 `Reservation`，存进 `reservations`；里面每个 offer 一个 `ReservedOffer` | 账本 booking_id、SENSE 实例 id、intent、VLAN |
| commit | `CommitAck`，里面是若干 `Commitment` | `Commitment` 存进 `commitments`；`Reservation.state` 改为 committed | — |

按时间顺序走一遍：

```
① quote
   scheduling ──QuoteRequest──► network
   network 算出 placement（含 path）→ 转成 Offer（不含 path）
   network 在 offer_book 记：offer_id → QuotedOffer(quote_id, request, placement)
   scheduling ◄──QuoteResponse(Offers)── network

② reserve：scheduling 只交回 quote_id 和选中的 offer_ids
   scheduling ──ReserveRequest(quote_id, offer_ids)──► network
   network 用 offer_id 查 offer_book → 拿到 QuotedOffer → 知道走哪条 path、多少 Gbps、哪段时间
   每个 offer：账本 pending（得到 booking_id）+ SENSE propagate（得到 instance_id、VLAN）
             → 记成一个 ReservedOffer
   整组 → 一个 Reservation(reserve_id, items=[ReservedOffer...], expires_at)，存进 reservations
   scheduling ◄──ReserveAck(reserve_id, expires_at)── network

③ commit：scheduling 只交回 reserve_id
   scheduling ──CommitRequest(reserve_id)──► network
   network 查 reservations[reserve_id] → 对每个 ReservedOffer：
       SENSE commit(instance_id)、账本 confirm(booking_id)
       生成 Commitment：binding 取 intent 的两端 URI 和 VLAN；workflow_id 取 offer_book[offer_id].request
   scheduling ◄──CommitAck(Commitments)── network
```

为什么非要留这些记录：每一步，scheduling agent 交回来的只是一个 id（offer_id、reserve_id），因为 path、booking、SENSE 实例这些细节不对它公开。network agent 只有在上一步把细节记下来，下一步才能凭 id 把它们找回来。可以把 `QuotedOffer` 看成报价单的存根，`Reservation` 看成预订单的存根：发给客户的是报价单和预订确认，存根留在自己手里。

`ReservedOffer` 和 `Reservation` 是一对多的关系：一次 reserve 可以选好几个 offer（比如一个 workflow 的几条传输一起订），它们要么一起 commit，要么一起作废，所以外面包一层 `Reservation`，里面每个 offer 一个 `ReservedOffer`。

---

> 1. ReservedOffer只是A到B的传输的offer吗，reservation是整个workflow，包含A到B，B到C，....，所以reservation包含reservedoffer的list？ 2. ReservedOffer包含一个serviceIntent，其中包含path_inclusion，这意味着从A到B经过的更细粒度的传输路径？ 3. "network 用 offer_id 查 offer_book → 拿到 QuotedOffer"，既然如此，为什么还需要quote_id，只给offer_id不就行了吗？

**1.** 前半句对：一个 `ReservedOffer` 对应一条传输（A→B）被选中的那个 offer。后半句要修正一下：`Reservation` 不一定是整个 workflow，而是**一次 ReserveRequest 选中的那一组 offer**，也就是 scheduling agent 决定"一起订、一起成败"的那几条传输，它们来自同一个 quote 的 bundle。

- 它可以是整个 workflow 的所有传输（A→B、B→C……），也可以只是其中一部分。比如先订前一阶段的，后一阶段等数据量估得更准再订，这样一个 workflow 就会有好几个 `Reservation`。
- 所以确实是 `Reservation.items: list[ReservedOffer]`。
- 一个限制：同一条传输在一个 reservation 里只能选一个 offer。比如 T1 不能同时订 a1 和 a2，那等于订了两份容量。B 部分的 `validate_reserve` 会检查这一点。

**2.** 对，就是"A 到 B 中间经过哪几跳"。传输请求只说两端，即 src=anl-n02、dst=ornl-n01，对应 intent 的两个 `terminals`。placement 选定的是一条具体路径，即有向链路序列 `(L1, L2, L3)`，中间经过 esnet-atl、esnet-chi。`path_inclusion` 把这条序列交给 SENSE，意思是"走这几跳"。

它不是"更细粒度的传输"，传输还是同一条，它说的是这条传输**走哪条路**。之所以要告诉 SENSE，是因为账本是按链路记的：预扣的是 L1、L2、L3 上的容量，SENSE 实际也必须走这三跳，账本才和现实一致。两个注意点（PLAN 待决里都有）：

- 真实 SENSE 把 inclusion_list 当成强制路径还是当成偏好，还没确认。
- 真实 adapter 要把 `L1:anl-n02>esnet-atl` 这种内部 id 翻译成 SENSE 的 Path URI。

**3.** 单说查表，确实只要 offer_id 就够了：现在的 offer_id 是 `q1/T1/2` 这种格式，本身全局唯一。留着 quote_id 有三个原因：

- **offer_id 对外应当是不透明的。** scheduling agent 不该靠解析 `q1/T1/2` 里的前缀来知道它属于哪个 quote，offer_id 的格式以后可能会变（比如换成 UUID）。消息里显式带 quote_id，含义写在协议里，不藏在 id 的格式里。
- **用来核对。** `validate_reserve` 会检查每个 offer 的 `QuotedOffer.quote_id` 是否等于请求里的 quote_id，不一致就返回 `invalid_request`。这能挡住 scheduling agent 的 bug，比如把旧 quote 和新 quote 的 offer 混在一起订：两个 quote 是基于不同时刻的账本算的，all_or_nothing 这类语义也是按 quote 定义的。
- **以后按 quote 做整体管理。** 5b 要清理过期 offer、处理重复请求，都是按 quote 为单位比较自然。

所以它对查表来说是冗余的，价值在核对和协议清晰。"一个 reservation 里的 offer 必须来自同一个 quote"是我加的设计约束，不是 slides 里明确写的，你觉得没必要的话 B 部分可以放开。

---

> 开始写B。

B 部分是 reserve 分支，106 个测试全部通过（新增 14 个）。

**新文件**

- `graphs/reserve.py`：reserve 分支的 9 个节点和 `build_reserve_graph()`。目前先单独成图，C 部分再由 `protocol.py` 的 `route_verb` 把它和 quote、commit 合成一张图。
  ```
  validate_reserve ─fail─► respond
    → recheck_capacity → place_on_circuit → compile_intent → ledger_pending ─fail─► respond
    → sense_propagate ─fail─► ledger_rollback → respond
    → record_reserve → respond
  ```
  - `validate_reserve`：只查不写。按顺序检查：offer 是否报过价（`not_found`）、是否属于请求里的 quote、同一传输是否选了两个 offer（`invalid_request`）、是否已被别的 reservation 订走（`conflict`）、offer 的时间段是否已整段过去（`expired`）。全部通过后分配 `reserve_id`（`rsv-1`、`rsv-2`……）。
  - `recheck_capacity`：只刷新这些 offer 路径上过期的观测值，不自己判断容量够不够。真正的判断交给 `ledger_pending` 的原子"先查后写"，因为同一组里的 offer 可能共用链路，单独查每个都够、合起来不够，只有依次预扣才查得出来。
  - `place_on_circuit`：5a 原样返回 placement（每个 offer 新开一个 circuit）。复用 warm circuit、换备用路径、优先级/抢占这三个扩展点写在 `circuit.place_on_circuit` 的 docstring 里。
  - `compile_intent`：每个 offer 编译成一个 `ServiceIntent`；alias = `{reserve_id}/{offer_id}`，方便在 SENSE 侧追溯。
  - `ledger_pending`：整组一次预扣，booking_id = `{reserve_id}/{offer_id}`；有一个不够就全部不写，返回 `conflict`，并且不会调用 SENSE。
  - `sense_propagate`：逐个 propagate，遇到第一个失败就停，并记下已经建好的实例。
  - `ledger_rollback`：取消已建的 SENSE 实例，再把整组 booking 回滚；取消也失败的话，在错误信息里写明还有哪些实例留在 SENSE（清理放在 5b）。
  - `record_reserve`：写入 `ctx.reservations`，`expires_at = now + TTL`（请求里的 `ttl_seconds` 优先，否则用 config）。
  - `respond`：有错就返回 `ErrorResponse`，否则返回 `ReserveAck`。
- `circuit.py`：`place_on_circuit`（扩展点）和 `compile_intent`（placement → intent：两端、path_inclusion、Mbps、时间段）。QoS 固定为 `guaranteedCapped`：预留必须"有保证"且"有上限"，否则逐链路账本对不上网络，所以写成常量，不放进 config。

**对已有代码的改动**

- `ledger.py`：新增 `pending_group(items)`，整组原子预扣；`pending` 改为调用它，行为不变。
- `telemetry.py`：quote 节点里"找过期 slot → 一次拉样本 → 写账本"的逻辑抽成 `refresh_stale(ledger, source, spans, now)`，quote 和 reserve 共用（第二次用到就提进模块）。
- `placement.py`：`Placement` 加属性 `rate_profile`，quote 的 `estimate_finish` 和 reserve 的 `ledger_pending` 共用。
- `context.py`：加 `new_id(prefix)`，生成 `rsv-1` 这样的 id。
- `tests/helpers.py`：`tr()`、`quote()` 从 step 4 测试挪进来。

**测试**（`tests/test_step5a_reserve.py`，场景都是 slide 7 网络在 09:00 对 T1、T2 报价后再 reserve）

- 成功：账本三跳各 pending 40 Gbps、L2 剩 0；SENSE 实例为 reserved、VLAN 3001、路径正确；intent 内容；整组两个 offer 各一个实例；TTL 覆盖。
- 拒绝且不留痕迹：未报价、quote 不符、同一传输选两个、时间已过、格式错误、重复 reserve。
- quote 之后网络变了：
  - 09:10 reserve 时观测已过期，recheck 刷新后发现 L2 不够 → `conflict`，SENSE 根本没被调用；
  - 09:01 reserve 时观测还新鲜，账本不知道网络变了，SENSE 接受第一个、拒绝第二个 → 第一个被取消、账本全部回滚；
  - 回滚时取消也失败 → 错误信息里报告留在 SENSE 的实例。
- 账本：两个各自放得下、合起来放不下的 booking，`pending_group` 一个都不写。

**一个新的已知问题**（已写进 PLAN 待决）：最早开始的 offer 就从 quote 的 now 开始，scheduling agent 晚几秒 reserve，开始时间就已经过去了。5a 只在 offer 整段时间都过去时才拒绝，否则按 quote 时的时段原样预扣。根治办法（quote 设有效期，或把开始时间顺延到 now）放到 5b 和 TTL 一起定。

---

> "一个要你知道的取舍……最早开始的那个 offer，开始时间就是报价时的 now。scheduling agent 隔几秒再 reserve，这个开始时间就已经过去了。……"没懂啥意思

用 slide 7 的 a1 举个例子。

```
09:00:00  scheduling agent 发 quote，network agent 的 now = 09:00:00
          a1 = 从 09:00:00 起，40 Gbps，到 11:46:40 结束
          （50 TB 在 40 Gbps 下正好要 10000 秒，开始时间取的就是 now）
09:00:30  scheduling agent 想了 30 秒，决定要 a1，发 reserve
```

问题在于，reserve 到达时 a1 的开始时间 09:00:00 已经过去 30 秒了，这 30 秒里不可能有数据在传。接下来有两种处理方式：

**做法一：拒绝。** 规则是"offer 的开始时间已过就拒绝"。可最早开始的 offer 总是从报价那一刻开始，而 reserve 总会晚到一点，哪怕只晚 1 秒，这类 offer 也永远订不上。这显然不行。

**做法二：照原样订（5a 现在的做法）。** 账本和 SENSE 都按 09:00:00–11:46:40、40 Gbps 来订。但数据最早 09:00:30 才开始传，10000 秒后是 11:47:10 才传完，比预留的结束时间晚了 30 秒。

这 30 秒的超出影响有多大，要分两头看：

- **账本：基本没影响。** 账本按 15 分钟一个时间槽记，11:46:40 落在 11:45–12:00 这个槽里，这个槽整槽都记着 40 Gbps，所以 11:47:10 仍在已预留的范围内。
- **SENSE：有影响。** intent 写的结束时间是 11:46:40，到点 circuit 就撤了，最后 30 秒的数据只能走普通路由（没有带宽保证），或者变慢。

所以 5a 只拒绝"整段都已过去"的 offer（比如 12:00 才来订 a1），其他情况照原样订，接受这几秒到几十秒的超出。

**根治办法有两个，都还没做：**

1. **quote 设有效期。** 比如 offer 只在报价后 60 秒内能订，超时就返回 `expired`，让 scheduling agent 重新报价。这样能把超出量控制在有效期以内，但不能消除超出。
2. **reserve 时把开始时间顺延。** 按 [now, now + 时长) 来订，速率不变，整体往后挪 30 秒。代价是：挪过去的时段要重新查容量（往后挪可能碰到更挤的槽）；完成时间也和 scheduling agent 在 offer 里看到的不一样了，`ReserveAck` 需要把实际的起止时间告诉它。

这两个办法都和"过期"有关，所以放到 5b，和 reserve 的 TTL 一起定。

---

> 继续写。下一步是c还是5b？

下一步是 C；5b 要等 5a 的 C、D 都完成后再做。C 部分已写完，116 个测试全部通过（新增 10 个）。

**新文件**

- `graphs/commit.py`：commit 分支。
  ```
  validate_commit ─fail─► respond
    → sense_commit ─fail─► respond        （账本不动，reservation 保留，可以重试）
    → ledger_confirm → respond
  ```
  - `validate_commit`：找不到 reservation → `not_found`；已经 commit 过 → `conflict`；`now >= expires_at` → `expired`（过期的预留仍占着容量，回收是 5b 的事）。
  - `sense_commit`：逐个实例调用 SENSE commit。**先查一下实例状态，已经是 committed 的就跳过**。这样一组里中途失败（前一个已 commit、后一个没有）之后，重试不会对前一个再 commit 一次（SENSE 会拒绝，因为它已经不是 reserved 了）。
  - `ledger_confirm`：账本 booking 从 pending 改为 confirmed（不再扣一次容量，容量在 reserve 时已经扣过）；为每个 offer 生成一个 `Commitment`：transfer_id 和 workflow_id 取自 `offer_book` 里存的原请求，circuit_id = SENSE 实例 id，速率取自实际预订的 placement，`EndpointBinding` 的两端 URI 取自 intent 的 terminals、VLAN 取自 SENSE 返回的状态；写入 `ctx.commitments`，reservation 标为 committed。
  - commit 失败为什么不回滚：SENSE 那边实例仍是 reserved，容量仍被占着，scheduling agent 可以在 TTL 内重试。回滚是 reserve 失败时才需要的。
- `graphs/common.py`：条件边 `on_error`（state 里有 `error` 就去 respond，否则继续）。reserve 和 commit 都用，第二次用到就提出来了。

**完整的图 A**（`graphs/protocol.py` 的 `build_protocol_graph()`）

```
START → route_verb ─ quote   → quote 子图
                   ├ reserve → reserve 子图
                   ├ commit  → commit 子图
                   └ 未知 verb → END（返回 invalid_request）
```

三条分支各自是一张编译好的子图，直接作为父图的节点挂上去。父图的 state 只有四个字段：`verb`、`raw`、`now`、`response`。LangGraph 在子图和父图之间只传双方都有的字段，所以子图内部的中间结果（paths、bookings 等）不会漏到父图里。测试里也验证了这一点。

调用方式：`graph.invoke({"verb": "reserve", "raw": {...}, "now": ...}, context=ctx)`。

**对 A、B 部分代码的改动**

- `ReservedOffer` 加了 `placement` 字段：commit 生成 `Commitment` 时要用实际预订的速率和时段。将来启用"换备用路径"后，它可能和报价时的 placement 不同，所以单独存一份。
- 测试辅助 `reserve()`、`commit()`、`make_quoted_ctx()`（报好价的 T1、T2）挪进了 `tests/helpers.py`。

**测试**（`tests/test_step5a_commit.py`）

- 成功：Commitment 各字段；SENSE 为 committed、账本为 confirmed、reservation 标记为 committed；commit 前后账本的 own 不变（不重复扣）；一组两个 offer 各自一个 commitment、VLAN 各不相同。
- 拒绝：reservation 不存在、已过期（过期后 booking 仍是 pending）、重复 commit。
- SENSE 失败：commit 失败后账本、SENSE、reservation 都保持原样，TTL 内重试成功；一组里第二个失败后重试，只补 commit 第二个（第一个没有被 commit 两次）。
- 整张图：用同一张图依次发 quote → reserve → commit 三条消息；未知 verb 返回 `invalid_request`。

---

> 1. "确认了 LangGraph 父图只共享与子图重合的字段，中间字段会自动过滤，所以三条分支可以直接作为子图节点接入主图"是啥意思 2. 我建议把quote也单独从protocol.py拎出来作为一个单独的py文件？

**1.** 先看三张图各自的 state 有哪些字段：

| 图 | state 字段 |
|---|---|
| 父图（`ProtocolState`） | verb、raw、now、response |
| quote 子图（`QuoteState`） | raw、now、request、paths、refreshed、placements、rejections、offers、response |
| reserve 子图（`ReserveState`） | raw、now、request、reserve_id、quoted、refreshed、chosen、intents、bookings、instances、error、response |

把编译好的子图直接当成父图的一个节点（`g.add_node("quote", build_quote_graph())`）时，LangGraph 这样传数据：

```
父图 state {verb, raw, now}
      │  进入子图：只把子图也声明了的字段交给它 → {raw, now}
      ▼
quote 子图内部跑完所有节点，自己的 state 里攒下 request、paths、offers ……、response
      │  回到父图：只把父图也声明了的字段写回 → {raw, now, response}
      ▼
父图 state {verb, raw, now, response}       ← paths、offers 这些中间结果不会出现在这里
```

也就是说，**父子图双方都有的字段（raw、now、response）就是它们之间的接口**，其余字段各自留在自己的图里。写 C 之前我拿一个小例子试过这一点，C 的测试 `test_one_graph_quote_reserve_commit` 里也断言了：父图跑完 quote 后，state 里只有 `verb, raw, now, response` 四个键。

**2.** 同意，已经拆了：

- 新文件 `graphs/quote.py`：第 4 步 quote 分支的全部代码（`QuoteState`、5 个节点、`build_quote_graph()`），内容没有改。
- `graphs/protocol.py` 只剩入口：`ProtocolState`、`route_verb`、`after_route`、`build_protocol_graph()`。
- 这样 `graphs/` 下是一个入口文件加三条分支各一个文件（quote.py、reserve.py、commit.py），再加共用的 common.py，结构是对称的。
- 测试里 `from ..graphs.protocol import build_quote_graph` 改成了 `from ..graphs.quote import ...`。116 个测试全部通过。
