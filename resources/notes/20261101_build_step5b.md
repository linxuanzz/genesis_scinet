第 5b 步：图 A 的 release、modify 分支，TTL 到期回收，重复请求的幂等处理，以及 5a 遗留的几处收尾。下面是设计方案，**待确认后再写代码**。

## 一、范围

PLAN 里 5b 这一行列了三件事：modify/release、TTL 到期回收、重复请求幂等。5a 写下来，又遗留了几处要在 5b 一并解决：

| 遗留问题 | 来源 | 5b 的处理 |
|---|---|---|
| 过了 expires_at 的预订不会被自动回收 | 5a reserve.py 的 docstring | 本步做 TTL 回收 |
| rollback 时 cancel 也失败，SENSE 里留下孤儿实例 | 5a `ledger_rollback` | 回收时一并重试 cancel |
| reserve 时 offer 的开始时间已经过去 | PLAN 待决 | 给 quote 加有效期（见决策 3） |
| `offer_book` 只增不删 | PLAN 待决 | 回收时清掉过期 quote 的 offer |
| `sense.state()` 查不到实例时抛出 `KeyError`，而不是 `SenseError` | 5a 期间发现 | 改为抛 `SenseError("not_found")`，顺手修 |

## 二、图的形状

图 A 再加两条分支，入口前后各加一个节点：

```
START → dedupe_request ─命中─► END（直接返回上次的回复）
          │ 未命中
          ▼
        sweep_expired → route_verb ─ quote   → （不变）
                                   ├ reserve → （不变）
                                   ├ commit  → （不变）
                                   ├ release → validate_release → sense_cancel → ledger_release → respond
                                   └ modify  → validate_modify → recheck_capacity → ledger_replace
                                                 → sense_modify ─ok──► record_modify → respond
                                                               └fail─► ledger_restore → respond
                         （各分支之后）→ remember_response → END
```

- **release**：
  - 预订（reserved）和已提交（committed）的都能释放。
  - SENSE 先 cancel，账本再退还：pending 的 booking 走 `rollback`，confirmed 的走 `release`。
  - cancel 失败时，对应的账本**不退**。资源实际还占在网络里，账本应如实反映。返回 `sense_failure`，可以重试；已经 cancel 掉的那些照常退还。
- **modify**：在原路径、原 circuit 上，改一个 offer 的速率和/或时段。
  - 账本先原子地把旧 booking 换成新的；检查容量时，旧 booking 本身占的那部分算作可用。
  - 然后调 SENSE modify；失败就把旧 booking 换回来。
- **sweep_expired**：每条消息进来先扫一遍，做三件事：
  - 回收过期未提交的预订（复用 release 的函数）；
  - 重试孤儿实例的 cancel；
  - 清掉过期 quote 的 offer。
- **dedupe_request / remember_response**：处理同一个请求重复发来的情况（见决策 5）。

## 三、需要你定的五件事（每条附我的建议）

1. **release 的粒度**
   - 建议：`ReleaseRequest(request_id, reserve_id, offer_ids=None)`，不给 `offer_ids` 就释放整个预订，给了就只释放其中几项。
   - 理由：最常见的释放场景是某条传输提前传完，要把剩下的时段还回去。这是按单条传输释放，不是按整组。
2. **TTL 到期由谁触发**
   - 建议：惰性回收，也就是每条消息进来时，先由 `sweep_expired` 扫一遍。时间由调用方传入 `now`，测试容易写，结果也确定。
   - 代价：长时间没有消息进来，过期预订会一直占着 SENSE 资源。所以 `sweep_expired` 背后是一个普通函数，以后接真实系统时，由一个定时器定期调用同一个函数即可（标为 hook）。原设计说的"后台任务发 `verb=release`"，等于这个函数加一个定时器。
3. **offer 开始时间已过 / offer_book 清理**
   - 建议：给 quote 加有效期 `quote_ttl_seconds`，新增 config 字段，测试里设为 120 s。超过有效期的 offer，reserve 时返回 `expired`，`sweep_expired` 同时把它从 offer_book 里删掉。
   - 效果：开始时间最多被推迟一个有效期，而账本按 15 分钟一个时间槽记账，影响很小。
   - 不选的做法：reserve 时把开始时间顺延到 now。那样实际预订的时段就和报价对不上，ReserveAck 也得把新时段返回给 scheduling agent，接口要改。
4. **modify 能改什么**
   - 建议：只能改同一路径、同一 circuit 上某一项的速率和/或时段，请求格式为 `ModifyRequest(request_id, reserve_id, offer_id, rate_profile)`。
   - 换路径不在 modify 里做：由 scheduling agent 自己先 reserve 新的、再 release 旧的（make-before-break）。这两个动词都已经有了。
   - 已提交的项被 modify 后，回复里带回更新后的 commitment。
5. **幂等怎么处理**
   - 建议：
     - 以 (verb, request_id) 为键，quote 用 quote_id 当键；只缓存**成功**的回复。
     - 同一个 id、请求内容相同：直接返回缓存的回复，不重复执行。
     - 同一个 id、请求内容不同：返回 `invalid_request`。
   - 理由：失败的回复不缓存，这样 commit 失败后，用同一个 request_id 重发就能真正重试。

## 四、分几部分写

| 部分 | 内容 |
|---|---|
| A | release：`ReleaseRequest` / `ReleaseAck`，`graphs/release.py`，Reservation 记录每一项的状态；修 `sense.state()` 的 KeyError |
| B | 回收：`sweep_expired`（过期预订、孤儿实例、过期 offer），`quote_ttl_seconds` |
| C | modify：`ModifyRequest` / `ModifyAck`，SENSE `modify`（接口与 mock），账本 `replace`，`graphs/modify.py` |
| D | 幂等（`dedupe_request` / `remember_response`），5b 的 demo，更新图 A 的 html，PLAN 收尾 |

---

> 回到5b。同意你的建议。写代码前先补充resources/other/network_agent/protocol_graph_a.html。

五条决策都按建议定下。图 A 已经更新，`visuals/protocol-graph-a.html` 是片段，`protocol_graph_a.html` 是独立页面，两者同步：

- 入口前后加了三个所有命令共用的节点（紫色）：`dedupe_request` → `sweep_expired` → `route_verb`，各分支结束后统一经过 `remember_response`。
- 新增 release、modify 两条泳道，标为 *planned*，绿色表示"已设计、尚未实现"。release 是一条直线：`validate_release → sense_cancel → ledger_release → respond`。modify 在 `sense_modify` 处分成 `record_modify` 和 `ledger_restore` 两路。
- quote 和 reserve 两条泳道补了 5b 的改动：offer 会过期，reserve 遇到过期的 offer 返回 `expired`。
- 下拉菜单改成可以选五个命令中的任意一个。

## 五、A 部分：release

**改动位置**

| 文件 | 改了什么 |
|---|---|
| `schemas.py` | 新增 `ReleaseRequest(request_id, reserve_id, offer_ids=None)` 和 `ReleaseAck(reserve_id, offer_ids)`。`offer_ids` 不给表示释放全部还占着的项；给了不能是空列表，也不能重复 |
| `context.py` | `Reservation` 新增 `released`（已退还的 offer_id 集合）和 `commitment_ids`（offer_id → commitment_id，由 commit 写入）；新增属性 `held`（还没退还的项）和方法 `mark_released()`（全部退还后 `state` 变成 `"released"`） |
| `ledger.py` | 新增 `free(booking_id)`：pending 的走 `rollback`，confirmed 的走 `release` |
| `sense.py` | `state()` 查不到实例时，改为抛 `SenseError("state", "not_found")`（原来抛 KeyError）。新增 `cancel_instances()`：逐个 cancel，遇到失败继续往下做；SENSE 已经显示 cancelled 的实例跳过，所以重试是安全的 |
| `graphs/release.py`（新） | release 分支：`validate_release → sense_cancel → ledger_release → respond` |
| `graphs/common.py` | 新增 `parse_request()`，把四个 validate 节点里重复的"解析请求、格式错误就返回 invalid_request"抽成一个函数（release 是第四处用到） |
| `graphs/quote.py`、`reserve.py`、`commit.py` | 改用 `parse_request`。`reserve.ledger_rollback` 改用 `cancel_instances`（这是它的第二处使用）。reserve 判断"offer 已被预订"时只看 `held`，所以退还之后的 offer 可以重新 reserve。commit 只处理 `held` 中的项，已经 released 的预订会返回 conflict，并记录 `commitment_ids` |
| `graphs/protocol.py` | `Verb` 加上 `"release"`，release 子图接入主图 |
| `tests/helpers.py` | 新增 `release(ctx, reserve_id="rsv-1", offer_ids=None, now=t(9))` |
| `tests/test_step5b_release.py`（新） | 13 个测试，见下 |

**release 分支的行为**

- `validate_release`：
  - 预订不存在 → `not_found`；
  - 指定的 offer 不在这个预订里 → `not_found`；
  - 指定的 offer 已经退还过 → `conflict`；
  - 整单都已退还过 → `conflict`。
- `sense_cancel`：逐个 cancel，遇到失败继续往下做。只要有一个失败，就返回 `sense_failure`，detail 里写明哪些还占着、哪些已经退还。
- `ledger_release`：只退还 cancel 成功的那些项：退还 booking，删除对应的 commitment，并标记为 released。**cancel 失败后也照样执行这一步**（图里 `sense_cancel → ledger_release` 是一条无条件边），这样能退还的都退还了。cancel 失败的项继续占着 booking，因为它在网络里确实还占着资源。

**测试**（`tests/test_step5b_release.py`）

- 成功：
  - 释放未提交的预订：账本清零，两个 SENSE 实例都变成 cancelled，状态为 released；
  - 释放已提交的预订：commitment 被删除；
  - 部分释放：T2 提前传完，退还 09:00 的时间槽，T1 在 12:00 的 100 Gbps 不受影响，commitment 只剩 T1；
  - 部分释放后再 commit，只提交剩下的那项；
  - 退还后的 offer 可以重新 reserve，得到 `rsv-2`。
- 拒绝：
  - 预订或 offer 不存在 → `not_found`；
  - 退还两次 → `conflict`；
  - 整单退还后再 commit → `conflict`；
  - `offer_ids=[]` 格式错误。
- SENSE cancel 失败：si-1 失败、si-2 成功，于是 q1/T2/1 被退还，q1/T1/2 的 booking 仍是 pending，实例还占着；重试后全部退还。
- `sense.state("si-9")` 抛出 `SenseError(not_found)`。
- 通过图 A 的入口走一遍 quote → reserve → release。

共 130 个测试全部通过（新增 13 个）；没有未使用的 import，代码中没有中文，私有信息检查通过。

---

> 为什么给全局增加了dedupe_request、sweep_expired和remember_response

这三件事对每个命令都一样，而且必须在分支开始之前或结束之后做，所以放在主图的入口和出口，不在每条分支里各写一遍。

**dedupe_request / remember_response：同一个请求重复发来**

agent 之间是跨网络发消息的。scheduling agent 发出 reserve 后如果没收到回复（超时、网络抖动），唯一能做的就是重发。现在的代码遇到重发，会出现这几种问题：

| 重发 | 现在的结果 | 问题 |
|---|---|---|
| reserve r1 | `conflict: offers already reserved` | 第一次其实成功了，scheduling agent 却以为失败了，不知道 rsv-1 的存在。这份预订会一直占着容量，直到 TTL 到期 |
| commit c1 | `conflict: rsv-1 is already committed` | 同样是把成功当成失败，也拿不到 CommitAck 里的 VLAN 和 binding |
| release | `conflict: already released` | 同上 |
| quote q1 | 重新报一次价，覆盖 offer_book 里同名的 offer | 账本变化后，第二次的 q1/T1/1 可能和第一次不是同一个方案，scheduling agent 手上的 offer 就对不上了 |

处理办法是第一次成功时把回复存起来（remember_response），之后遇到同一个 (verb, request_id) 就直接返回存下的回复（dedupe_request），不再执行一遍。

放在全局的理由：
1. 五个命令都需要，判断逻辑完全相同，放在主图里只写一次；
2. dedupe 必须在分支产生任何副作用之前判断，remember 必须在分支给出回复之后执行。能同时看到"进分支之前"和"分支的回复"的，只有主图这一层。

**sweep_expired：过期的东西必须先清掉，后面的分支才能看到正确的状态**

现在过了 TTL 的预订不会被回收。5a 的测试 `test_expired_reservation` 就记录了这一点：09:01 过期之后，booking 仍然是 pending。这意味着这部分容量会一直被一份已经作废的预订占着，之后的 quote 看不到它，reserve 也用不了它，SENSE 里对应的实例也一直占着网络资源。

5b 的设计是惰性回收：不另开定时器，而是每条消息进来时先清理一遍。它放在 `route_verb` 之前，原因是：
1. 不管来的是哪个命令，都要先清理。quote 要看到被回收的容量，reserve 要能用上这部分容量，commit 和 release 要看到预订已经作废，所以它对所有命令都必须执行；
2. 必须在分支读取账本之前执行，否则这一次请求看到的仍然是旧状态。

它排在 dedupe 之后：如果是重发的请求，直接返回存下的回复就行，不需要做任何工作。

**为什么不选别的做法**

- 每条分支自己处理：五条分支各写一遍 dedupe 和 sweep，就违反了"第二次用到就提炼"。而且 quote 分支和 reserve 分支各自只清理和自己相关的部分，很容易漏掉。
- sweep 用定时器：真实部署时需要，因为长时间没有消息进来，过期的预订会一直占着 SENSE 资源。所以 sweep 背后是一个普通函数，定时器以后可以直接调用它（图上标为 hook）。但在测试和 demo 里，时间 `now` 是调用方传入的，惰性回收的结果是确定的，更容易测试。

## 六、B 部分：过期回收与 quote 有效期

**改动位置**

| 文件 | 改了什么 |
|---|---|
| `reclaim.py`（新） | release 分支和过期回收共用的几块：`cancel_items()`（按预订项 cancel，返回成功和失败的 offer_id）、`give_back()`（退还 booking、删除 commitment、标记 released）；`sweep_expired(ctx, now)` 和它的返回值 `SweepReport` |
| `config.py` | 新增 `quote_ttl_seconds` |
| `schemas.py` | `QuoteResponse` 新增 `valid_until` |
| `context.py` | `QuotedOffer` 新增 `expires_at`；`ReservedOffer` 新增 `request`（commit 从这里取 transfer_id / workflow_id，不再查 offer_book）；`Reservation.state` 多一个 `"expired"`，新增 `is_expired(now)`；`AgentContext` 新增 `orphans`（instance_id → booking_id）和 `expired_quotes` |
| `graphs/quote.py` | respond 写入 `valid_until = now + quote_ttl_seconds` |
| `graphs/reserve.py` | 过期 quote 的 offer 返回 `expired`，无论 sweep 是否已经把它删掉。回滚时 cancel 失败的实例记进 `orphans`，**保留它的 booking**，等 sweep 成功 cancel 后再退还 |
| `graphs/commit.py` | 已过期（或已被 sweep 回收）的预订返回 `expired`，不再是 `conflict` |
| `graphs/release.py` | 改用 `cancel_items` / `give_back` |
| `graphs/protocol.py` | `START → sweep_expired → route_verb`，回收结果写进 state 的 `swept` |

**sweep_expired 做三件事**

1. 过期且未提交的预订：逐项 cancel，退还 booking，全部退完后状态变成 `expired`。cancel 失败的项继续占着，记在 `stuck` 里，下次 sweep 再试。
2. 孤儿实例：重试 cancel，成功的退还 booking。
3. 过期 quote 的 offer：从 offer_book 删除，quote_id 记进 `expired_quotes`。

**两处与设计不同，需要你知道**

- **测试里的 quote 有效期是 900 s，不是设计时说的 120 s。** 5a 的 `test_recheck_catches_capacity_lost_since_quote` 要在 09:10 reserve，等 quote 时的观测过期（观测有效期 5 分钟）。120 s 的话，这个 offer 先因为 quote 过期被拒，测不到 recheck。900 s 正好是一个时间槽。
- **孤儿实例保留 booking**，这改变了 5a 的行为：原来回滚时 cancel 失败，账本照样全部退还。现在与 release 的规则一致：资源还占在网络里，账本就不退。5a 的 `test_failed_cancel_is_reported` 相应改了断言。

## 七、C 部分：modify

**改动位置**

| 文件 | 改了什么 |
|---|---|
| `schemas.py` | 新增 `ModifyRequest(request_id, reserve_id, offer_id, rate_profile)` 和 `ModifyAck(reserve_id, offer_id, rate_profile, commitment=None)`；rate_profile 的校验（非空、有序、不重叠）抽成 `_check_profile`，Offer 和 ModifyRequest 共用 |
| `sense.py` | 接口新增 `modify(instance_id, intent, now)`。mock 先拿掉旧的占用再检查新的，不够就恢复旧的并抛 `SenseError`；实例、VLAN、状态都不变 |
| `ledger.py` | 新增 `replace(booking_id, profile)`：同一路径、同一状态，原子地换掉 profile，检查时不计旧 booking；放不下就保留旧的 |
| `context.py` | `Reservation.is_expired(now)`（commit、modify、sweep 三处共用） |
| `graphs/modify.py`（新） | `validate_modify → recheck_capacity → ledger_replace → sense_modify → record_modify / ledger_restore → respond` |

**validate_modify 的规则**

- 预订或 offer 不存在 → `not_found`；预订已过期 → `expired`；该项已退还 → `conflict`。
- 新 profile 只能是**一段**：一个 circuit 只有一个恒定速率（circuit.py），多段要拆成多个 circuit，留到出现时再定。
- 已经开始的项（`start <= now`）不能移动开始时间，只能改速率和结束时间；还没开始的，新开始时间不能早于 now；结束时间不能已经过去，也不能超出账本范围。都返回 `invalid_request`。

**失败路径**：账本放不下 → `conflict`，什么都没改。SENSE 拒绝 → `ledger_restore` 把旧 profile 换回来，返回 `sense_failure`。

## 八、D 部分：幂等、demo、收尾

**幂等**（`graphs/protocol.py`）

- `dedupe_request`：按 verb 解析请求，以 (verb, request_id) 为键（quote 用 quote_id）查 `ctx.answered`。请求内容相同就直接返回缓存的回复，并在 state 里标 `replayed`，后面什么都不跑，包括 sweep；内容不同就返回 `invalid_request`。请求格式错误或 verb 未知时不查缓存，交给分支或 route_verb 报错。
- `remember_response`：各分支之后，只缓存成功的回复。
- 已知空白：缓存在 agent 生命周期内只增不删，按重试窗口清理留作 hook，已记进 PLAN 待决。

**demo**（`tests/test_step5b_demo.py`，`python -m <包路径>.tests.test_step5b_demo test1` … `test5`）

| 场景 | 内容 |
|---|---|
| test1 | 两项都 commit；T2 提前传完，只退还它；T1 改成 12:00–14:00 @ 50 Gbps；再退还剩下的 |
| test2 | reserve 后一直不 commit；下一条消息（新的 quote）先回收 rsv-1，迟到的 commit 返回 `expired` |
| test3 | 回复丢失后重发：重发的 reserve、commit 从缓存返回；注入失败的 commit 不缓存，重发就是真重试；r1 被复用到别的 offer → `invalid_request` |
| test4 | 09:16 才 reserve，quote 已过期 → `expired`；重新 quote 后成功 |
| test5 | commit 后 L2 在 13:00–14:00 多了 30 Gbps 背景流量，telemetry 还没报；把 T1 拉到 14:00 @ 100 Gbps，账本放行、SENSE 拒绝，账本换回旧的；改成 70 Gbps 成功 |

5a 和 5b 两个 demo 共用的打印逻辑（`Session`、请求和回复的打印）从 5a demo 提炼进了 `tests/printing.py`，`quote_t1_t2` 挪进 `tests/helpers.py`。

**其他**

- 图 A html 两个文件同步：release、modify 去掉 *planned*，各节点的条件按实际代码补全（quote 的 `valid_until`、reserve 的孤儿实例、commit 的 conflict 等），图例里删掉"未实现"一项。
- PLAN：5b 标 ✅；待决里划掉 offer_book 清理，补上 offer 开始时间的处理结果，新增一条"5b 新增的已知空白"。
- 共 171 个测试全部通过（5b 新增 41 个）；没有未使用的 import，代码中没有中文，私有信息检查通过。

---

> B部分，为什么release现在要用cancel_items, give_back

是"第二处使用就提炼"。A 部分写 release 时，这两段逻辑直接写在它的两个节点里：
- `sense_cancel`：对每个要退还的项 cancel 它的 SENSE 实例。遇到失败继续往下做，最后分出成功和失败的 offer_id。
- `ledger_release`：对 cancel 成功的项，退还 booking，删除 commitment，标记 released。

B 部分的 sweep 回收过期预订时，要做的事完全一样：cancel 实例，退还成功的，失败的继续占着。这就成了第二处使用，所以两段逻辑提炼成了 `reclaim.py` 的 `cancel_items` 和 `give_back`，release 和 sweep 都调用它们。release 的行为没有变，A 部分的测试原样通过。两者唯一的区别是最后的标记，由参数 `done="released"` 或 `"expired"` 区分。

为什么不让 sweep 直接调用 release 分支：
- sweep 不是一条请求，没有 request_id，也不需要返回 ErrorResponse；
- 它运行在图 A 进入分支之前；
- 以后还要能被定时器直接调用。

所以共用的应该是下面这层普通函数，而不是图。函数放在 `reclaim.py` 而不是 `release.py`，也是为了不让 sweep 依赖某个分支的文件。

---

> AgentContext的Orphans是啥？

`orphans: dict[instance_id → booking_id]`，记录"网络里还占着资源，但没有任何预订认领"的 SENSE 实例。

它只有一个来源：reserve 失败后的回滚。reserve 对一组 offer 是全有或全无的，比如 T1 的实例已经建好，T2 被 SENSE 拒绝，就要把 T1 的实例 cancel 掉。如果这个 cancel 也失败了，T1 的实例就还在 SENSE 里，占着网络容量。但 reserve 整体失败了，没有生成 Reservation，调度 agent 也没拿到 reserve_id，所以没人能 release 它。这就是孤儿。

- **5a 的做法**：账本照样全部退还，只在错误信息里提一句。结果是账本以为这段容量空着，网络里其实还占着，下一个 quote 可能把它卖出去，造成超订。
- **5b 的做法**：这个实例的 booking 保留为 pending，同时记进 `orphans`。之后每次 sweep 都重试 cancel，成功了才退还 booking，并从 `orphans` 里删掉。这和 release 的规则一致：cancel 失败就不退账本，因为资源还在网络里。

对应的测试是 `test_failed_cancel_is_reported`：回滚后 `orphans == {"si-1": "rsv-1/q1/T2/1"}`，这个 booking 仍是 pending；下一次 sweep cancel 成功后才退还。

---

> sweep expired做了什么，从宏观角度给我讲讲

network agent 会发出两种有期限的承诺。另外还有一种意外的遗留，就是孤儿：

| 东西 | 期限 | 占着什么 |
|---|---|---|
| quote 的 offer | `valid_until`（quote 后 `quote_ttl_seconds`） | 只占 `offer_book` 里的一条记录；quote 不扣账本 |
| 未 commit 的预订 | `expires_at`（reserve 后 60 s） | 账本里的 pending booking，以及 SENSE 里 reserved 状态的实例 |
| 孤儿实例 | 没有期限，应该尽快清掉 | 账本里的 pending booking，以及 SENSE 里的实例 |

期限到了，如果没人回收：账本的 own 永远扣着，SENSE 一直占着实例，容量就漏掉了；offer_book 也只增不减。`sweep_expired` 就是做回收的。它让三本账（账本、SENSE、offer_book）跟时间保持一致，依次做三件事：

1. **过期预订**：状态是 reserved、已过 `expires_at` 的预订，cancel 它的实例，退还 booking，状态变成 `expired`。cancel 失败的项继续占着，记进 `stuck`，下次再试。committed 的预订不归它管，因为那已经是真实的 circuit。
2. **孤儿**：重试 cancel，成功的退还 booking。
3. **过期 quote**：从 offer_book 删掉这些 offer，quote_id 记进 `expired_quotes`。这样之后对它的 reserve 回答的是 `expired`，而不是 `not_found`。

**放在哪、什么时候跑**：在图 A 里，每条消息进来、去重之后、进入分支之前跑一次（惰性）。好处是各分支看到的世界里，过期的东西已经清掉了，分支不必各写一套回收逻辑，只需在 validate 里给出 `expired` 错误码。`now` 由调用方传入，所以测试是确定的。缓存重放（replayed）的请求什么都不跑，sweep 也不跑。

**代价**：没有消息进来时什么都不回收，SENSE 会一直留着过期的实例。所以它写成普通函数，返回 `SweepReport`，真实部署时再加一个定时器调用同一个函数。这是留下的 hook。

---

> 能否理解B部分本质就是给quote加了一个有效期，然后牵连到quote response, quote offer, 一组reserve（reservation），commit的validate都得做出对应的字段新增或者修改？

只对了一部分。quote 有效期是 B 的三件事之一；另外两件是**回收过期预订**和**孤儿**。你列的改动里，有一半其实来自"过期预订"，而不是 quote 有效期。按原因拆开：

**① quote 有效期（新增）**
- `config.quote_ttl_seconds`
- `QuoteResponse.valid_until`：告诉调度 agent 这些 offer 什么时候失效
- `QuotedOffer.expires_at`：agent 自己记着
- reserve 的 validate：offer 过期，或已被 sweep 删掉但 quote_id 在 `expired_quotes` 里，都返回 `expired`
- sweep 第 3 件：删除 offer，记录 tombstone
- 间接影响：`ReservedOffer.request`。以前 commit 从 offer_book 读 transfer 信息，现在 offer_book 会被清，所以 reserve 时把 request 存进预订项，commit 改读 `item.request`

**② 回收过期预订**（预订的 60 s 期限 5a 就有：ReserveAck 带 `expires_at`，commit 也会检查；但过期后没人回收）
- `Reservation.state` 增加 `"expired"`，新增 `is_expired(now)`，`mark_released(done=...)`
- sweep 第 1 件
- commit 的 validate：先判断 `is_expired`，再判断 `state != reserved` 返回 conflict。sweep 把预订标成 expired 之后，迟到的 commit 应该得到 `expired`，而不是 conflict。**这一条来自②，与 quote 有效期无关**

**③ 孤儿**
- `ctx.orphans`，reserve 的 `ledger_rollback` 不再立刻退还，sweep 第 2 件

需要强调的一点：quote 有效期**只管 reserve 这一关**。一旦 reserve 成功，quote 过不过期就不重要了，因为预订有自己的期限；commit 从不检查 quote 是否有效。

---

> 为什么QuotedOffer reservedoffer Reservation不放在schemas.py中

因为这几个类和 schemas.py 里的东西不是一类。schemas.py 只放**线上消息**，也就是 agent 之间交换的 JSON：和调度 agent 往来的 quote/reserve/commit 等，以及 telemetry、SENSE 的消息。`QuotedOffer`、`ReservedOffer`、`Reservation` 是 network agent 自己的**内部账本记录**，从不发出去，所以放在 context.py，和装着它们的 `offer_book`、`reservations` 放在一起。

具体有三点不同：

1. **装的是不对外的东西。** 调度 agent 只看到 `Offer`（rate_profile、预测完成时间、blocked_by），看不到背后的 `Placement`（走哪条路径、按什么规则放的）。`ReservedOffer` 记着 booking_id、SENSE 的 instance_id、发给 SENSE 的 intent，这些都是 agent 内部的实现细节。如果放进 schemas.py，看起来就像协议的一部分。
2. **要求不同。** schemas.py 里都是 pydantic 模型：不可变，拒绝未知字段，在边界上校验外来 JSON。内部记录不需要防外部输入，用 dataclass 就够了；而且 `Reservation` 必须是可变的（state、released、commitment_ids 会被 commit、release、sweep 改写），还带着 `held`、`is_expired`、`mark_released` 这样的行为。
3. **依赖方向。** `QuotedOffer` 和 `ReservedOffer` 引用了 `Placement`，而 placement.py 依赖 ledger.py 和 schemas.py。把它们放进 schemas.py，就会形成 schemas → placement → schemas 的循环 import。现在的方向是单向的：schemas 是最底层，谁都不依赖；context 在最上层，把账本、拓扑、外部接口和这几本账组装起来。

反过来，`Commitment` 放在 schemas.py，因为它会作为 CommitAck 的内容发给调度 agent。`commitments` 这本账直接存线上消息本身，不需要另外的内部记录。

---

> modify中，recheck_capacity不就是refresh if stale吗？

对。modify 的 `recheck_capacity` 就是对新 profile 的时间范围（同一条路径，`[新 start, 新 end)`）调用一次 `refresh_stale`，节点里没有别的逻辑。reserve 的同名节点也一样，只是对一组 offer 的范围一起调用。

真正的容量检查不在这个节点里，而在下一步：reserve 的 `ledger_pending`、modify 的 `ledger_replace`。账本在加锁的"检查再写入"里一次完成判断和扣减，放不下就抛 `InsufficientCapacity`。拆成两个节点，是因为二者分工不同：
- 前一个只保证账本里的 observed 数字是新鲜的；
- 后一个才判断放不放得下，并写入。

如果先在 recheck 里检查、再到下一步写入，中间就留了一个窗口：别的请求可能在这期间扣掉同一段容量。所以检查必须和写入放在一起。

单独留一个节点（而不是把 refresh 塞进 ledger_replace）的理由是：图上能看到"先刷新观测"这一步，它会把刷新了哪些 link 写进 state 的 `refreshed`，方便调试和测试断言。

不过名字确实容易误导："recheck" 听起来像是在检查容量，实际只是刷新。这个名字沿用了 5a 设计里的 `recheck_capacity`。如果要改名，比如统一改成 `refresh_stale`，reserve、modify 两个分支和图 A 的 html 要一起改。

---

> dedupe_request中
> 1. identify的"return (verb, getattr(req, id_field)), req"是啥意思
> 2. if seen is None:是啥意思

**1. `return (verb, getattr(req, id_field)), req`**

这一行返回一个二元组 `(key, req)`：

- `key = (verb, getattr(req, id_field))` 是这条请求在缓存里的键。`id_field` 是从 `REQUESTS` 表里查到的字段名：quote 是 `"quote_id"`，其余四个 verb 都是 `"request_id"`。`getattr(req, id_field)` 就是按字段名取值，相当于 `req.quote_id` 或 `req.request_id`。所以 key 的形式是 `("reserve", "r1")` 或 `("quote", "q1")`。
- `req` 是用该 verb 的模型解析好的请求对象，比如 `ReserveRequest(...)`。

两者都要返回，因为调用方要分两步用：
- 先用 key 查缓存；
- 命中了再拿 req 和缓存里存的请求比较，判断是不是同一个请求。

所以 `dedupe_request` 里有两处拆包：
- `known[0]` 取 key 去查缓存；
- `(verb, request_id), req = known` 把 key 再拆成 verb 和 request_id，用来写错误信息。

键里带 verb，是因为不同 verb 的 id 互不相干：commit 用了 `"r1"` 不等于 reserve 的 `"r1"`（测试 `test_ids_are_per_verb`）。

请求是解析之后再比较，而不是直接比较 raw dict。这样同一个请求哪怕字段顺序不同、时间写法不同（如 `+00:00` 和 `Z`），也会被认作同一个。

**2. `if seen is None: return {}`**

`seen` 是缓存里查到的记录 `Answered(request, response)`。它在两种情况下是 None：

- `known` 是 None：verb 未知或请求格式错误，没法算出 key，也就不查缓存（`... if known else None`）；
- key 不在 `ctx.answered` 里（`dict.get` 查不到就返回 None）：这是一条新请求，或者之前的回复是错误，没被缓存。

两种情况都返回 `{}`，即不写任何字段。`after_dedupe` 看到 state 里没有 `response`，就继续走 sweep_expired → route_verb → 分支，正常处理这条请求。格式错误的请求由分支自己的 `parse_request` 报 `invalid_request`，未知 verb 由 route_verb 报。

只有 `seen` 不是 None 时才往下走：
- 请求内容相同 → 返回缓存的回复，并标上 `replayed`；
- 内容不同 → 返回 `invalid_request`。

这两种结果都会写入 `response`，`after_dedupe` 于是直接走到 END。

---

> getattr(req, id_field)是啥

`getattr` 是 Python 内置函数：`getattr(obj, "name")` 等价于 `obj.name`，区别是属性名是一个**字符串变量**，运行时才确定。

这里要用它，是因为不同 verb 的标识字段名不同，写死 `req.request_id` 不行：

```python
REQUESTS = {"quote": (QuoteRequest, "quote_id"), "reserve": (ReserveRequest, "request_id"), ...}
model, id_field = REQUESTS[verb]       # verb="quote" → id_field = "quote_id"
getattr(req, id_field)                 # 即 req.quote_id，比如 "q1"
```

- verb 是 `"quote"`：`id_field` 是 `"quote_id"`，取到的是 `req.quote_id`；
- verb 是 `"reserve"`：`id_field` 是 `"request_id"`，取到的是 `req.request_id`。

不用 getattr 的话，就得写成 `req.quote_id if verb == "quote" else req.request_id`。用表加 getattr，以后新增 verb 时只需在 `REQUESTS` 里加一行。

---

> D部分的test1，针对的是reserve，commit，release，modify四种消息吗

消息确实覆盖了五种（还有 quote），但 test1 **针对的是 5b 新增的 release 和 modify**。前面的 quote、reserve、commit 只是铺垫，用来造出一个已 commit 的预订，这几步 5a 的 demo 已经演示过。

test1 依次发出的消息：

| 时间 | 消息 | 回复 | 演示什么 |
|---|---|---|---|
| 09:00:00 | quote q1 | T1、T2 的 offer | 铺垫 |
| 09:00:10 | reserve r1 | ReserveAck rsv-1 | 铺垫 |
| 09:00:20 | commit c1 | CommitAck：cmt-1（T1 12:00–13:06:40 @ 100）、cmt-2（T2 09:00–09:03:20 @ 40） | 铺垫 |
| 09:04:00 | release x1，只点名 `q1/T2/1` | ReleaseAck：released `['q1/T2/1']` | **部分退还**：组里其余的项保持不动 |
| 09:05:00 | modify m1：T1 改为 12:00–14:00 @ 50 | ModifyAck，附带更新后的 cmt-1 | **modify 已 commit 的项**：账本换 profile，SENSE 改实例，commitment 同步更新 |
| 09:06:00 | release x2，不点名 offer | ReleaseAck：released `['q1/T1/2']` | **不点名 = 退还剩下所有还占着的项**；之后 rsv-1 变为 released |

三个 5b 要点都是在**已 commit** 的状态下演示的（退还 confirmed 的 booking、删除 commitment、更新 commitment）。只 reserve、未 commit 时的 release 和 modify 由 `test_step5b_release.py`、`test_step5b_modify.py` 覆盖。

另外发现一处叙述不准确：场景说 "T2 finished early"，但 T2 的 commitment 本来就在 09:03:20 结束，09:04 的 release 已经在它结束之后，算不上"提前完成"。退还的也只是过去的时间段，看不出账本里有容量回来。要演示"提前完成、把后面的容量还回去"，release 应放在 09:03:20 之前（例如 09:02），这样账本里 09:02–09:03:20 的 own 会回到 0。

---

> 能否增加一个5b_final_demo，能把五种例子的正常情况全过一遍

已新增 `tests/test_step5b_final_demo.py`。只有一个场景，不用传参数：`python -m <包路径>.tests.test_step5b_final_demo`。五种消息都通过图 A 的统一入口发送，每种走一遍正常路径，每条消息之后打印账本、预订和 SENSE 实例：

| 时间 | 消息 | 回复 | 账本 / SENSE 的变化 |
|---|---|---|---|
| 09:00:00 | quote q1 | 6 个 offer，valid until 09:15 | 不扣账本，只记进 offer_book |
| 09:00:10 | reserve r1（T1 12:00 @ 100，T2 09:00 @ 40） | ReserveAck rsv-1，expires 09:01:10 | own 记上 pending booking；SENSE 两个实例为 reserved |
| 09:00:20 | commit c1 | CommitAck：cmt-1、cmt-2 | booking 变为 confirmed；实例变为 committed |
| 09:01:00 | modify m1：T1 改为 12:00–14:00 @ 50 | ModifyAck，附更新后的 cmt-1 | 12:00–14:00 的 own 从 100 变为 50；si-1 原地改为 50 Gbps |
| 09:02:00 | release x1，只点名 T2（提前完成） | ReleaseAck `['q1/T2/1']` | 09:00–09:15 的 own 归 0；si-2 被 cancel |
| 09:03:00 | release x2，不点名（workflow 取消） | ReleaseAck `['q1/T1/2']` | own 全部归 0，commitments 清空，rsv-1 变为 released，两个实例都是 cancelled |

测试函数 `test_final_demo_printout` 断言：六个回复的类型依次正确，结束时 rsv-1 为 released、没有 commitment、所有 SENSE 实例都已 cancel。

顺带的整理：`R1`、`C1` 原来在 `test_step5b_demo.py` 和 `test_step5b_idempotency.py` 里各写了一份，`modify_t1` 这次也要第二次用到，所以三者都挪进了 `tests/helpers.py`，三个文件共用。共 172 个测试通过。PLAN 的 5b 行补上了这条 demo 命令。

**更正上一条回答**：我说 test1 在 09:04 release T2 时"看不出账本里有容量回来"，这是错的。账本的 slot 是 15 分钟（`slot_seconds: 900`），T2 的 booking 落在 09:00–09:15 这个 slot 里；09:04 仍在这个 slot 内，所以 release 之后 09:00–09:15 的 own 确实从 40 变回 0，test1 的输出里看得到。不准确的只有叙述本身：T2 本来就在 09:03:20 结束，09:04 已经不算"提前完成"。final demo 把这次 release 放在 09:02，叙述就对上了。

---

> python -m <包路径>.tests.test_step5b_final_demo
>
> 我的包路径是什么

包路径取决于在哪个目录下运行。在本仓库里有两种写法，都试过可以运行：

- 在仓库根目录（`genesis_scinet/`）下：`python -m src.lib.network_agent.tests.test_step5b_final_demo`。`src/` 和 `src/lib/` 下没有 `__init__.py`，Python 把它们当作命名空间包处理，所以这样也能找到。
- 在 `src/lib/` 下：`python -m network_agent.tests.test_step5b_final_demo`。

代码里写成 `<package path>`、不写死，是因为同一份代码还会同步到两个共享仓库，在那里路径不同（例如 SciNetGenesis 里是 `ucr/network_agent/`）。而且推到那边的代码注释里不能出现本仓库的目录结构。

发现一处不一致：demo 文件的 docstring 写的是 "from the repository root"，举的例子却是 `network_agent.tests...`，这个例子只有在 `network_agent/` 的上一级目录运行才对。建议把说明改成 "from the directory that contains network_agent/"，三个 demo（5a、5b、5b final）一起改。

---

> 为什么test5b_final_demo里，quote 的回复（q1/T1/1 09:00 @ 40、q1/T1/2 12:00 @ 100、q1/T1/3 09:00 @ 20，路径都是 L1→L2→L3）没有L4和L5的offer

L4/L5 这条路径其实算过了，只是它算出的方案和主路径完全重合，被跨路径去重掉了。

quote 的 `find_placements` 对每条候选路径（`topology.paths`，最多 `max_paths` 条）各跑一次 `placement.search`，再用 `placement.dedupe` 跨路径去重。去重的键是 `(start, gbps)`，按路径从短到长保留第一个。理由是调度 agent 看不到路径：开始时间和速率都相同的两个 offer，对它来说没有区别。

直接对两条路径各跑一次 search 的结果：

| transfer | 路径 | earliest_start | max_rate | min_rate |
|---|---|---|---|---|
| T1 | L1→L2→L3 | 09:00 @ 40 | 12:00 @ 100 | 09:00 @ 20 |
| T1 | L1→L4→L5→L3 | 09:00 @ 40 | （同 earliest_start，路径内已去重） | 09:00 @ 20 |
| T2 | L1→L2→L3 | 09:00 @ 40 | 12:00 @ 100 | 09:00 @ 10 |
| T2 | L1→L4→L5→L3 | 09:00 @ 40 | （同上） | 09:00 @ 10 |

- L4、L5 的容量只有 40 Gbps，所以备选路径上最快就是 09:00 @ 40。主路径上 L2 09:00–12:00 有 60 Gbps 背景流量，剩下的也恰好是 40。两条路径给出同一个 `(09:00, 40)`，主路径更短，留下主路径。
- min_rate 只取决于数据量和截止时间（50 TB 在 6 小时内跑完 → 向上取整到 20），与路径无关，所以也重合。
- 备选路径到不了 100 Gbps，max_rate 就是 09:00 @ 40，在路径内部已经和 earliest_start 合并了。

所以三个 offer 都标着主路径。注意 `blocked_by` 也是按主路径算的：q1/T1/1 标 `background_traffic`，是因为主路径受限于 L2 上的背景流量；如果走备选路径，限制它的就是链路容量本身。

被去重掉的备选路径方案以后有两个用处，都已经在 PLAN 里记着：
1. **reserve 时换路兑现**：主路径在 quote 之后被占满时，用备选路径兑现同一个 offer，对调度 agent 透明。5a 没有采用，只在 `place_on_circuit` 标为 hook。
2. **bundle 联合报价**（第 12 步）：例如 T1 选 q1/T1/1、T2 选 q1/T2/1（都是 09:00 @ 40），两者都落在主路径 L2 上，合起来要 80，但 L2 只剩 40，reserve 会失败。如果一个走 L4/L5，两个都放得下。这就是之前定下推迟到第 12 步解决的 offer 冲突问题。
