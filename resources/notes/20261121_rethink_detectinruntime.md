电信网管有个标准框架 FCAPS（ITU-T M.3400），其中的故障管理分四步：

**检测 → 定位 → 诊断 → 修复**

ESnet 和 perfSONAR 社区按严重程度和位置分类：

**1. 硬故障**：链路或设备断了。这类最容易发现。

**2. 软故障**：链路还通，但性能变差。拥塞只是其中一种，常见的还有：

- **物理层丢包**：光模块脏了、线缆老化。链路显示 up，却有少量丢包。在长距离高带宽的路径上，0.01% 的丢包就能让 TCP 吞吐大幅下降。这是科研网络里最典型、也最难查的问题。
- **配置问题**：MTU 不一致、QoS 限速或整形配错、交换机缓冲区太小。
- **路由变化**：路径被切到更长的线路上，RTT 变大，吞吐跟着掉。
- **中间设备**：防火墙或 IDS 对大流量限速。

**3. 端系统问题**：TCP 调优、磁盘 I/O、CPU、DTN 配置。

它们的定位方法是**分段测试**：沿路径分段做 perfSONAR 测量，把问题夹在某一段里。

对照你们：`link_down` 是硬故障，`congestion` 是软故障里的一种，`unlocated` 大致就是端系统问题。

---

### 为什么不能只通过flow level进行检测：

1. **问题在未来。** 比如 telemetry 已经知道 2 小时后有计划停机，或者别人预约了同一段链路导致我们届时不够用。当前 flow 跑得完全正常，但它后面订的时段注定会出问题。
2. **传输还没开始。** 没有 flow 可以测，只能看 link。

只用 flow 判定，就要等吞吐真的掉下来才处理，而那时可选的修复方案已经变少了：剩余时间短，extend 的空间小，reroute 也来不及准备。提前发现，正是网络有预约账本相比纯被动监控的优势。

---

### 新detection结构

所以完整的结构应该是：flow 层的三分类负责已经在跑的传输，link 预报负责未来时段和还没开始的传输。

```
已在跑的传输（flow 判定）
  ├─ 吞吐 < 预约 → 查 link
  │    ├─ 某一跳被挤占（上限问题） → extend / reroute / borrow
  │    └─ 路径正常（利用率低）     → extend（必要时 reroute 试探）
  ├─ 吞吐 = 预约，但剩余量 > 剩余预约能运的量（上限问题） → extend / raise / reroute / borrow
  └─ 吞吐 = 预约，量也相符 → 不动
未来时段 / 未开始的传输（link 预报）
  └─ 预约时段受损
```

其中，

```
某一跳被挤占（上限问题） → extend / reroute / borrow
```

这里考虑的情况是，网络上不只有scinet的流量，还有其他背景流量会挤占scinet的流量。所以即使在某一个link我们预约了50GB，但最终到手的可能只有30GB。

我之前以为这种情况只有extend / reroute可以解决，borrow不可以，因为我们的系统没法从背景流量borrow带宽的，如果是scinet自己的流量，又会进入同一个准入控制，不会出现自己挤占自己的情况。但是当受损的这一跳上同时有我们好几条电路时，borrow 还是有用。比如：

某一跳上我们有两条电路：A 订 30（高优先级），B 订 20（低优先级），合计 50。背景流量涨上来后，这一跳只剩 30 给我们。

- **不处理**：网络不知道我们内部的优先级，按比例分，A 拿 18，B 拿 12，两条都不达标。代码里的 `expected_gbps` 就是按这个比例来预测的。
- **borrow**：主动把 B 降下来，让出带宽给 A，A 回到 30，B 降到 0 或改去 extend。损失集中到低优先级的电路上。

---

### link预报

```
未来时段 / 未开始的传输：预约时段受损（link 预报）
  │
  ├─ ① 预报确定性
  │    ├─ 确定（计划停机、别人已登记的预约） → 立即进入 ②
  │    └─ 不确定（telemetry 预测的拥塞）     → 受损时段在提前量 X 以内才进入 ②，否则继续观察
  │
  ├─ ② 会不会来不及（forecast，p95）
  │    ├─ 时间余量能吸收，仍能在预约结束前传完 → 不动，继续观察
  │    └─ 会来不及                             → 进入 ③
  │
  ├─ ③ 受损类型与共享情况 → 决定可选方案
  │    ├─ 硬损：那一跳在该时段 down（如计划停机）
  │    │    ├─ reroute：受损时段绕开那一跳
  │    │    ├─ raise：在停机前多传（前提是路径有余量）
  │    │    └─ extend：停机期间不传，结束时间往后推
  │    │    （borrow 无用：那一跳大家都是 0）
  │    └─ 软损：那一跳 up，但该时段容量 < 我们订的量
  │         ├─ 那一跳只有我们一条电路 → reroute / raise（受损前多传）/ extend
  │         └─ 那一跳有我们多条电路   → 以上方案，再加 borrow（按优先级重新分配）
  │
  └─ ④ 传输是否已开始 → 决定修复代价
       ├─ 未开始：直接重新安排整个预约（换路径、改时间），不需要切换传输
       └─ 已开始：reroute 需要准备新电路 → 确认传输切换 → 释放旧电路，代价和风险更高
```

预报应该分成两部分：

#### 1. 数据对接

去接运维的维护日历和 SENSE/OSCARS 的预约表。

#### 2. 流量预测

#### a. 统计时间序列（最常用的基线）

骨干网链路的流量有很强的日周期和周周期。常用方法：

- **季节性基线**：取上周同一时段的值，或者取历史上同一时段的分位数；
- **EWMA、Holt-Winters**：指数平滑，带趋势项和周期项；
- **ARIMA / SARIMA**：经典的时间序列模型。

简单、可解释、需要的数据少，运营商实践中用得最多。

#### b. 机器学习

- LSTM、GRU、Transformer：单条链路的时间序列预测；
- 图神经网络（GNN）：把拓扑也作为输入，同时预测多条链路，能捕捉相邻链路之间流量的相互影响。

学术论文很多，但需要大量历史数据，效果也常常只比季节性基线好一点。ESnet 自己就有团队做过这类深度学习流量预测，具体论文可以查一下，和 SciNet 的场景最接近。

#### c. 需求驱动预测

科研网络的流量和普通互联网不同，主要是大块的“大象流”，突发性强，用周期性规律预测效果有限。更有效的思路是：**知道谁要传什么，就知道链路会多忙**，比如实验排程、已知的工作流计划。这正好是 SciNet “science-aware” 的卖点：上层科学工作流的调度信息本身就是一种流量预报。

**注意：**我们自己的预约已经记在账本里了（`own`），不需要预测。需求驱动预测真正有价值的，是别人已知、但还没登记成预约的计划，比如其他项目的实验排程、别的 agent 管的工作流。所以先要问清楚：network agent 能拿到这类信息吗？拿不到的话，这个模块就没有输入。

#### 预报暂定方案

只做统计时间序列，不考虑需求驱动预测。原因在于**两个模块要拆开算，不能直接相加。**  
历史流量序列里本身就包含了过去那些已知的大流量。如果直接用历史数据做季节性基线，再加上需求驱动的预测，同一类流量会被算两次。合理的组合方式是：

```
未来背景流量 = 统计基线（历史流量中扣掉已知大流量后的部分）
             + 需求驱动（已知的未来大流量）
```

**这要求历史数据能区分出哪些是已知流量。**如果区分不了，就退一步，只用统计基线，并且接受它对突发大流量预测不准。

顺序上建议先做统计基线，并和现在的“当前值持续”对比。这两者只需要历史链路数据，最容易做成第一个可测的实验。需求驱动等到弄清楚能拿到什么需求信息之后再接。

#### 预报的插入位置

预报这部分应该作为detect的一个环节，但 detect 只负责**读**预报，不负责**算**预报。预测应该作为独立模块，把结果写进账本。

原因是两者的节奏不同。如果每次 detect 都重算一遍预测，既浪费，又会让 detect 的耗时变得不可控。

- **detect** 是事件触发的（tick、告警），触发很频繁，要求快；
- **预测** 是在新数据到来或者有效期过了时才需要更新，计算可能较重（尤其将来换成模型以后）。

建议的结构：

```
预测模块（独立节奏：数据更新 / 过期时运行）
  └─ 把未来时段的预测值（带分位数和来源标签）写进账本的 observed

detect（每次事件触发）
  ├─ 1. 检查 flow：在跑的传输吞吐和量是否达标
  └─ 2. 读账本里的未来时段：预约的时段是否会受损（只读，不计算）
```

这和现在代码的结构是吻合的：`refresh_stale` 负责从数据源拉数据写进账本，`damaged_slots` 负责读账本判断受损。预测模块可以做成**又一个数据源**，放在 `refresh_stale` 背后，和 telemetry 并列，detect 的代码基本不用改。

要改的地方是账本：现在一个时段只存一个值，加上预测以后，需要能存分位数和“已登记还是预测”的标签，否则上面第 ① 步的确定性分级就无从做起。例子：

以一条链路 `chi>atl` 为例，设定如下：标称容量 100 Gbps，时段长度 10 分钟，现在是 10:00。我们有两条电路：A 订 30，B 订 20，都经过这条链路。

当前账本：每个时段对应一个 `Observation`（只有一个值），`own` 由所有经过这条链路的预约求和得出：

```
时段          observed                                       own   available
              gbps  up   source      at     valid_until      (A+B) (=obs−own)
10:00–10:10   60    ✓    telemetry   10:00  10:15           50    10
10:10–10:20   60    ✓    telemetry   10:00  10:15           50    10
10:20–10:30   60    ✓    telemetry   10:00  10:15           50    10   ← 只是把当前测量值外推出去
10:30–10:40    0    ✗    sense       09:00  12:00           50     0   ← 计划停机（已登记）
10:40–10:50   40    ✓    sense       09:00  12:00           50     0   ← 别人登记了 60 的预约（受损：40 < 50）
10:50–11:00  100    ✓    topology    —      过期            50    50   ← 没有数据，用标称容量
```

问题在于：从数据结构上看不出哪一行是确定的、哪一行只是猜测。10:20 那一行的 60 是“外推”，10:40 那一行的 40 是“已登记”，但两者都只是一个数字，`source` 字段也区分不出这种差异。

有了预测之后的账本：`Observation` 加**分位数**（p50 / p95）。依据类型（测量值、已登记、预测）不单独存一栏，由 `source` 经固定映射推出：

| source | 依据类型 |
|---|---|
| telemetry | measured（测量值） |
| prediction | predicted（预测） |
| sense | registered（已登记） |
| maintenance | registered（已登记） |

```
时段          p50   p95   up   source       valid_until   own   available(p50/p95)
10:00–10:10   60    60    ✓    telemetry    10:15        50    10 / 10
10:10–10:20   58    45    ✓    prediction   10:30        50     8 / 0   ← p95 下会受损
10:20–10:30   55    35    ✓    prediction   10:30        50     5 / 0
10:30–10:40    0     0    ✗    maintenance  12:00        50     0 / 0   ← 确定，立即修复
10:40–10:50   40    40    ✓    sense        12:00        50     0 / 0   ← 确定，立即修复
10:50–11:00   70    50    ✓    prediction   11:00        50    20 / 0
```

说明几点：

- **p95 指悲观的情况**：背景流量偏大时我们能拿到多少，所以 p95 那一列的数值 ≤ p50。
- **已登记的行**（sense、maintenance）p50 = p95，没有不确定性。
- **测量值的行**（telemetry）是当前测量值，只对当前时段有效。
- 第 ① 步的确定性分级靠 `source` 映射出的依据类型：已登记的立即处理；预测的按 p95 判断，并且只在提前量以内才动手。
- 前提是每个 source 只产出一种依据类型。若某个来源将来产出多种（如 telemetry 既发测量值又发预测值），就把来源拆细（`telemetry` / `telemetry_forecast`），不加栏。
- 现有的 `expected_gbps` 和 forecast 用 p50/p95 两套 observed 各算一遍，就能接进现有的 p50/p95 框架。

名称（`registered`、`predicted`、`measured`、`prediction`）是临时起的，可以再定。

---

### 总逻辑

#### 两种触发检测的手段

核心想法：**link 告警不直接触发检测，而是先进预报模块**。预报模块更新账本后，再通知检测去看哪些链路变了。这样检测永远只读账本、不做计算，link 告警也就自然成了预报模块的一个输入。

#### 检测模块

```
检测
├─ 触发
│   ├─ self-check：所有 commitment，flow 分支的 a,b 和 link 分支都跑
│   ├─ telemetry 的告警
│   │    ├─ flow 告警：只走 flow 分支的 a
│   │    ├─ link 告警 → 预报模块 → 更新账本 → 有实质变化 → link分支
│
├─ flow 分支（已在跑的传输，看当前）
│   ├─ a. 吞吐 < 预约 → 查 link 的当前时段
│   │    ├─ 某一跳 down                       → reroute / extend
│   │    ├─ 某一跳被挤占，我们只有一条电路    → reroute / extend
│   │    ├─ 某一跳被挤占，我们有多条电路      → reroute / extend / borrow
│   │    └─ 路径正常（利用率低：端系统/软故障）→ extend
│   ├─ b. 吞吐 ≈ 预约，但剩余量 > 剩余预约能运的量（实际数据量多于预估数据量 / 开始晚了）
│   │    └─ 上限问题 → extend / increase / reroute / borrow
│
├─ link 分支（未来时段 + 还没开始的传输）
│   ├─ 某一跳 down                  → reroute / increase / extend
│   ├─ 某一跳被挤占，我们只有一条电路 → reroute / increase / extend
│   └─ 某一跳被挤占，我们有多条电路   → reroute / increase / extend / borrow
│
└─ 输出 → 修复模块（先判断会不会来不及，再按代价从小到大尝试）
```

两个分支的唯一区别是 increase。link 分支里，increase 的意思是赶在受损时段之前多传一些，这是可行的。flow a 里受损就发生在当前时段，已经没有“之前”可以多传了，所以没有 increase。

#### 预报模块

```
预报模块（只负责未来时段；两个子模块共用“链路 × 时段”结构和“过期即重算”机制）
│
├─ A. 非 SciNet 流量预报 → 写 observed → 服务于检测
│   ├─ 触发
│   │    ├─ observed 的预报值过期 → 立即重算
│   │    └─ link 告警 → 该链路的值提前过期 → 立即重算（不等时段到来）
│   ├─ 输入
│   │    ├─ telemetry 当前测量值（作为预测起点）
│   │    ├─ 停机日历
│   │    ├─ 非 SciNet 的已登记预约（SENSE 预约表，可选）
│   │    └─ 链路历史流量序列（扣掉 SciNet 自己的流量，作为统计基线）
│   ├─ 计算（每条链路 × 每个未来时段）
│   │    ├─ observed = 标称容量 − 非 SciNet 已登记预约（可选，p50 = p95） − 非 SciNet 未登记流量预测（p50 / p95）
│   │    ├─ 非 SciNet 未登记流量预测
│   │    │    ├─ 起点：当前测量值（telemetry，或 link_capacity_below 告警带来的值）
│   │    │    ├─ 预测值 = w × 起点 + (1 − w) × 统计基线；w 从 1 随时间降到 0
│   │    │    └─ 越远，p50 / p95 差距越大，最终稳定在历史波动幅度
│   │    ├─ 停机
│   │    │    ├─ 计划停机（日历）：该时段 up = false，p50 = p95 = 0
│   │    │    ├─ link_down（计划外）：按修复时长的一般情况（p50，如 1 小时）和坏情况（p95，如 3 小时）
│   │    │    │    ├─ 断开后 1 小时内：p50、p95 都是 down
│   │    │    │    ├─ 断开后 1–3 小时：p50 是 up，p95 是 down
│   │    │    │    └─ 断开 3 小时以后：p50、p95 都是 up
│   │    │    └─ link_up：撤销计划外停机的标记，重算
│   │    └─ 结果限制在 [0, 标称容量] 之内
│   └─ 输出
│        ├─ 写入账本的 observed
│        └─ 按 p95 对比重算前后：我们有预约的时段里，哪些从“够用”变成“不够用”
│             → 立即通知检测 → link 分支 → 修复
│
├─ B. SciNet 流量预报 → 写 SciNet 未来流量预测 → 服务于规划/准入（暂时留空，scheduling agent 尚不存在）
│   ├─ 触发
│   │    ├─ 预测值过期 → 向 scheduling agent 拉取
│   │    └─ scheduling agent 的 workflow 计划变更 → 相关值提前过期 → 拉取
│   ├─ 输入
│   │    └─ scheduling agent：根据 workflow 依赖推算的未来 SciNet 流量
│   ├─ 计算
│   │    └─ 把未来流量摊到链路 × 时段上（但是路径无法确定，需要估计）
│   └─ 输出
│        ├─ 写入账本的 SciNet 未来流量预测（不并入 observed）
│        └─ 放不下时（observed − own < 预测需求）→ 反馈给 scheduling agent（协商的起点）
│
└─ 账本读取时的可用容量
     └─ 可用容量 = observed（A） − own（SciNet 已订） − SciNet 未来流量预测（B）
```

- 账本里的实值有两种来源，telemetry和prediction。telemetry的值会逐渐覆盖prediction。prediction主要用来对一些未来的预约提供信息。这俩都有自己的有效期。telemtry到期后不会立刻重算，而是需要的时候重算；prediction到期后会立刻触发重算。
- “链路历史流量序列（先扣掉当时已登记的流量，再做统计基线）”，之所以要扣点已登记流量，是因为预测的目标其实是背景流量。之所以不预测scinet下未来的workflow的流量，是因为这部分预测不应该和背景流量放一块，而是应该单独拿出来，根据scheduling agent的workflow-aware的能力去预测。这两种预测用途不一样：
  - **非 SciNet 流量预测**：回答“我们已经订的预约会不会受损”，服务于检测；
  - **SciNet 未来需求预测**：回答“接下来会有哪些请求进来”，服务于规划和准入。比如要不要给即将到来的高优先级 workflow 预留余量，现在要不要接一个低优先级的请求。它的信息来自 scheduling agent 对 workflow 的了解，应该接到规划（graph A），不进账本的 `observed`。
- “远的时段过渡到统计基线”，意思是：**离现在越远，越不信当前测量值，越相信“平时这个时候的样子”。**现在 10:00，L 测到只剩 30；按历史，L 平时这个时间段大约有 80 可用（这就是统计基线）。
  - **15 分钟后**：拥塞一般不会马上消失，最好的猜测接近 30；
  - **明天同一时间**：今天这次拥塞几乎说明不了什么，最好的猜测是平时的 80；
  - **中间的时段**：介于两者之间，越远越接近 80。
  ```
  预测值 = w × 当前测量值 + (1 − w) × 统计基线
  w：现在 = 1，随时间推移逐渐降到 0
  ```
  | 时段    | w   | 预测值 |
  | ----- | --- | --- |
  | 10:15 | 0.9 | 35  |
  | 10:30 | 0.7 | 45  |
  | 11:00 | 0.4 | 60  |
  | 12:00 | 0.1 | 75  |

  w 下降得多快，就是上一轮说的“过渡速度”。
- 可用容量 = observed − own − SciNet 未来流量预测（将来接入时，用于规划/准入时预留余量）
  - own: SciNet 已订的预约（账本里已有）
  - SciNet 未来流量预测: 还没订的（来自 scheduling agent，暂时留空）
- “可用容量”不由预报模块计算，是账本在读的时候算出来的：现在代码里的 `available = observed − own`。预报模块只负责写 `observed`.

---

### Runtime design (English version)

The network agent's runtime consists of three modules: **Forecast → Detection → Repair**. Detection only reads the capacity ledger and never computes forecasts. Link alerts from the telemetry agent do not trigger detection directly; they go to the Forecast module, which updates the ledger and then tells Detection which links/time slots changed. A link alert is therefore just one more input to Forecast.

#### Detection

```
Detection
├─ Triggers
│   ├─ Periodic self-check: all commitments; runs flow branch (a, b) and link branch
│   └─ Telemetry alerts
│        ├─ Flow alert → flow branch (a) only
│        └─ Link alert → Forecast → ledger updated → material change → link branch
│
├─ Flow branch (transfers already running; looks at the current slot)
│   ├─ a. Throughput < reserved rate → check the path's links in the current slot
│   │    ├─ A hop is down                                       → reroute / extend
│   │    ├─ A hop is squeezed, we have one circuit on it         → reroute / extend
│   │    ├─ A hop is squeezed, we have several circuits on it    → reroute / extend / borrow
│   │    └─ Path looks healthy (low utilization: end host / soft failure) → extend
│   └─ b. Throughput ≈ reserved rate, but remaining bytes > what the rest of the reservation can carry
│        (actual volume larger than declared / late start)
│        └─ Capacity-limit problem → extend / increase / reroute / borrow
│
├─ Link branch (future slots + transfers not started yet)
│   ├─ A hop is down                                    → reroute / increase / extend
│   ├─ A hop is squeezed, we have one circuit on it      → reroute / increase / extend
│   └─ A hop is squeezed, we have several circuits on it → reroute / increase / extend / borrow
│
└─ Output → Repair (first decide whether the transfer would actually miss its deadline,
             then try the candidate repairs from cheapest to most expensive)
```

Repair options: **extend** = push the reservation's end later; **increase** = raise the rate on the same path; **reroute** = move to another path; **borrow** = take rate from our own lower-priority circuits on the same hop. "Squeezed" means the hop's capacity left by non-SciNet traffic is below what we booked on it.

The two branches differ only in *increase*. In the link branch the damage is in the future, so increase means sending more before the damaged slot. In flow branch (a) the damage is already in the current slot, so there is no "before" to send more in.

#### Forecast

```
Forecast (future slots only; both sub-modules share the "link × time slot" layout and
          the "recompute on expiry" mechanism)
│
├─ A. Non-SciNet traffic forecast → writes `observed` → serves Detection
│   ├─ Triggers
│   │    ├─ A forecast value in `observed` expires → recompute immediately
│   │    └─ Link alert → that link's values expire early → recompute immediately
│   │       (without waiting for the affected slot to arrive)
│   ├─ Inputs
│   │    ├─ Current telemetry measurement (starting point of the forecast)
│   │    ├─ Maintenance calendar (planned outages)
│   │    ├─ Registered non-SciNet reservations (SENSE reservation table; optional)
│   │    └─ Historical link traffic, with SciNet's own traffic removed (statistical baseline)
│   ├─ Computation (per link × future slot)
│   │    ├─ observed = nominal capacity
│   │    │             − registered non-SciNet reservations (optional; p50 = p95)
│   │    │             − forecast of unregistered non-SciNet traffic (p50 / p95)
│   │    ├─ Unregistered non-SciNet traffic forecast
│   │    │    ├─ Starting point: latest measurement (telemetry, or the value carried by a
│   │    │    │   link_capacity_below alert)
│   │    │    ├─ forecast = w × starting point + (1 − w) × statistical baseline;
│   │    │    │   w decays from 1 (now) to 0 (far future)
│   │    │    └─ The p50–p95 gap widens with lead time, then levels off at the historical variability
│   │    ├─ Outages
│   │    │    ├─ Planned (calendar): link down in that slot, p50 = p95 = 0
│   │    │    ├─ Unplanned link_down: use a typical repair time (p50, e.g. 1 h) and a bad-case
│   │    │    │   repair time (p95, e.g. 3 h)
│   │    │    │    ├─ 0–1 h after the failure: down under both p50 and p95
│   │    │    │    ├─ 1–3 h after the failure: up under p50, down under p95
│   │    │    │    └─ More than 3 h after:     up under both
│   │    │    └─ link_up: clear the unplanned-outage marks and recompute
│   │    └─ Clamp results to [0, nominal capacity]
│   └─ Outputs
│        ├─ Write `observed` into the ledger
│        └─ Compare before/after under p95: which slots holding our bookings went from
│           "enough" to "not enough" → notify Detection immediately → link branch → Repair
│
├─ B. SciNet traffic forecast → writes the SciNet future-demand forecast → serves planning /
│     admission (placeholder for now; the scheduling agent does not exist yet)
│   ├─ Triggers
│   │    ├─ A forecast value expires → pull from the scheduling agent
│   │    └─ The scheduling agent's workflow plan changes → related values expire early → pull
│   ├─ Inputs
│   │    └─ Scheduling agent: future SciNet traffic inferred from workflow dependencies
│   ├─ Computation
│   │    └─ Map future traffic onto links × slots (paths are not known yet, so they must be estimated)
│   └─ Outputs
│        ├─ Write the SciNet future-demand forecast into the ledger (kept separate from `observed`)
│        └─ If it does not fit (observed − own < forecast demand) → report back to the
│           scheduling agent (the starting point of a negotiation)
│
└─ Available capacity, as the ledger computes it when read
     └─ available = observed (A) − own (SciNet's booked reservations) − SciNet future-demand forecast (B)
```

Notes:

- **Two kinds of values in the ledger.** The current slot holds telemetry measurements; future slots hold forecasts. As time passes, measurements replace forecasts. Both carry an expiry time. An expired telemetry value is refreshed only when someone needs it (localization, or as the starting point of a forecast). An expired forecast value is recomputed immediately, so that changes are detected and pushed to Detection without anyone having to read them first.
- **Why the two forecasts are kept apart.** `observed` is defined as the capacity left when our own bookings are not counted, so A forecasts only non-SciNet traffic. If B's forecast of SciNet demand were also subtracted into `observed`, that demand would be counted twice once it is actually booked (it then appears in `own`). The two forecasts also answer different questions:
  - **Non-SciNet forecast (A):** will the reservations we already hold be damaged? It serves Detection.
  - **SciNet demand forecast (B):** which requests are likely to arrive next? It serves planning and admission, e.g. whether to keep headroom for an upcoming workflow. Its information comes from the scheduling agent's knowledge of workflow dependencies.
- **What "the forecast moves toward the statistical baseline" means.** The further ahead a slot is, the less we trust the current measurement and the more we trust "what this link usually looks like at this time". Example: at 10:00 link L has only 30 Gbps left, while history says it usually has about 80 Gbps at this time of day. Fifteen minutes ahead, congestion rarely clears, so the best guess is close to 30. At the same time tomorrow, today's congestion says almost nothing, so the best guess is the usual 80. In between, the forecast moves from 30 toward 80:
  | Slot  | w   | Forecast (Gbps) |
  | ----- | --- | --------------- |
  | 10:15 | 0.9 | 35              |
  | 10:30 | 0.7 | 45              |
  | 11:00 | 0.4 | 60              |
  | 12:00 | 0.1 | 75              |

  How fast w decays (how far ahead a current change should matter) should be estimated from historical data.
- **Available capacity is not computed by Forecast.** The ledger computes it when read; the current code already does `available = observed − own`. Forecast only writes `observed` (A) and, later, the SciNet demand forecast (B).

---

## 需要从 telemetry agent 拿到的信息

| #   | 信息                                                                      | 用途                            | 现在的状态                                |
| --- | ----------------------------------------------------------------------- | ----------------------------- | ------------------------------------ |
| 1   | **链路当前测量值**：每条有方向链路的可用容量和 up/down                                       | 当前时段写入账本；也是预报的起点              | ⚠️ 已有，但有两处和我们的约定不符（见下文）              |
| 2   | **链路历史流量序列**：按时间查询某条链路过去的流量                                             | 预报模块计算统计基线（我们自己扣掉 SciNet 的流量） | ⚠️ 数据已经存在 InfluxDB 里并长期保留，但没有对外的查询接口 |
| 3   | **link 告警**（推送）：`link_down`、`link_up`、`link_capacity_below`             | 立即重算预报，提前处理未来的预约              | ❌ 没有                                 |
| 4   | **flow 进度**：我们每条传输的开始时间和已发字节数                                           | flow 分支 a、b 的判断依据             | ❌ 没有                                 |
| 5   | **flow 告警**（推送）：`flow_below_rate`（带测量速率）、`flow_stalled`、`flow_finished` | 触发 flow 分支 a                  | ❌ 没有                                 |

**不需要**从 telemetry agent 拿的：停机日历（来自运维）、非 SciNet 的已登记预约（来自 SENSE）。

第 1 项现有实现的两处不符：

- **测量值包含了我们自己的流量。** 我们约定的 `observed` 是“不算我们时的可用容量”，他们的 README 也写了这一点还没解决。
- `up` **固定为 true。** 他们还没有采集链路状态，所以链路断了也看不出来。

还有一个待定的问题：第 4、5 项里 `flow_id` 怎么和我们的传输对应。现在我们暂时用 SENSE instance id。

---
