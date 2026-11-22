# Current Experiment Plan

> 一句话总览:Exp3 把真实 workflow trace(WfCommons 1000genome)放大后接到 network agent 上:两份 1000genome 同时运行,mock scheduling agent 按 DAG 逐条请求传输,经 graph A 预约、在模拟网络上执行,graph B 按正常节奏巡检;同时第一次落地预报模块 B(SciNetDemandSource:按 workflow 依赖预报 SciNet 自己的未来流量)。

## 目标

回答:**一个真实 workflow 经“站点分配 + 数据放大”后,network agent 能否端到端承接它(预约、执行、巡检),两个 workflow 争用时表现如何;按 DAG 推算的 SciNet 需求预报与实际预约有多接近。**

## 假设、预期观察与价值

- **假设 H1(承接)**:放大后的两份 1000genome 中,需要预约的传输全部能在各自截止时间前预约成功并完成;网络正常、不注入事件时,graph B 巡检不检出任何偏离。
- **假设 H2(争用)**:两份 workflow 的大输入走同一段路径,后到的 WF-B 会受 WF-A 已占容量限制(offer 的 limited_by = own_commitment,或开始更晚/速率更低),WF-B 的数据准备时间长于 WF-A。
- **假设 H3(需求预报)**:每个预约传输在被请求之前都已出现在需求预报里;字节量与实际一致(同一份站点分配推出,按构造一致);请求时间的预报误差来自参考速率与实际速率之差,首次预报误差量化报告,最后一次预报(请求前最近一次巡检)误差小于首次。
- **价值**:第一次用真实 workflow 而非手写场景驱动 network agent;验证 graph A/B 在多 workflow 下的行为;给预报模块 B 一个可量化的起点。

以上为实验前假设,不是结论。

## 关键要素

- **被测对象**:`src/lib/network_agent`(graph A 预约、graph B 巡检、预报模块 A/B)。
- **负载**:`external/SciNetGenesis/workflows/example_workflows/1000genome-chameleon-2ch-100k-001.json`(WfFormat 1.6;52 task、64 文件、2.58 GB,原为单机 pegasus-5 运行,makespan 776 s)。两份实例 WF-A、WF-B,WF-B 晚 10 分钟开始。
- **转换(全部由 config 决定)**:
  - 站点分配:原始数据在 `aps-beamline-8id`;`individuals`、`sifting` 在 `ornl-n01`;`individuals_merge`、`mutation_overlap`、`frequency` 在 `anl-n02`。输入数据从 APS 经 ESnet 进 ORNL,中间结果 ORNL → ANL。
  - 放大:文件字节 × `data_scale`,任务时长 × `compute_scale`。
  - 粒度:跨站点传输按 (文件, 目的站点) 去重;≥ `reserve_threshold_bytes` 的经 graph A 预约,较小的走尽力而为(按固定速率估时,不占账本)。
  - 截止时间:请求时刻 + 字节 / `reference_gbps`(scheduling agent 能接受的最低平均速率)。
- **网络**:与 demo 相同的拓扑(slide 3 + esnet-nash 绕行);L2 上 09:00–12:00 有 40 Gbps 已登记的非 SciNet 流量;不注入停机或拥塞。
- **测量指标**:每个 workflow 的 makespan、数据准备完成时间、预约传输数 / 尽力而为传输数 / 字节、截止时间满足数、query 中 limited_by 的分布、graph B 检出偏离数;需求预报:预报与实际的字节量差、请求时间差。
- **硬性约束**:参数只来自 config;复用代码进 `src/lib/`;runtime 不注入事件(用户 2026-11-22 指定)。

## 可行性与风险

- **量级**:原始 2.58 GB 在 100 Gbps 下不到 1 秒,必须放大;中间文件为 KB 级,放大后仍远小于输入,预约只会落在输入 staging 上(需求预报因此主要预报 WF-B 的输入)。
- **时间尺度**:传输为分钟级,账本时段需缩短(config 设 60 s)。
- **简化**:尽力而为的小传输不占网络容量;同一文件被多个任务读取时只传一次;一个 transfer 一个 query(避开第 12 步的 bundle 冲突)。
- **模拟器即真值**:mock SENSE / telemetry 读同一个模拟网络,结果只说明系统逻辑,不说明真实网络性能。

## 步骤与进度

- [x] **S0 对齐**:用户 2026-11-22 同意:放大数据量、由 agent 决定站点分配、两份 workflow 争用(agent 选两份 1000genome)、落地 SciNetDemandSource、runtime 不注入事件、走 run_experiment.py。
- [x] **S1 trace 转换库**:`src/lib/wftrace/trace.py`(读 WfFormat → 站点分配 → 跨站点传输,按 (文件, 目的站点) 去重);单元测试通过。
- [x] **S2 预报模块 B**:`forecast.forecast_scinet_demand`:把预期传输按最短路径、填满窗口的速率落到账本的 SciNet demand(与 observed、own 分开,暂不扣减),放不下的反馈给 scheduling agent;单元测试通过(network agent 351 个)。
- [x] **S3 协同仿真**:`src/lib/wftrace/cosim.py`:mock scheduling agent(同时是 SciNetDemandSource,按参考调度预报未来请求)+ WMS 时间步进;小 workflow 单元测试通过。
- [x] **S4 实验(第 1 次,`runs/20261122_133802_…_32b4bf0`)**:跑通,但有两处问题,不登记结论:① 运行时实验代码尚未提交,run 名中的 hash 不含该代码;② 未注入事件,graph B 却检出 5 次偏离。
  - [x] **S4a 修复**:定位为检测 bug:两次读数之间才开始的传输,“最近速率”按整个间隔算,被误判为 slow;改为只按实际运行的时间算,补回归测试;cosim 记录每条偏离与报告。
  - [x] **S4b 重跑**(`runs/20261122_133919_…_6485b7b`):巡检偏离 0;12 个预约传输 3 个超时(均为 1.34 TB 注释文件);H2、H3 成立,H1 因超时不成立。
- [x] **S5 复核**(`…_26a2997`):metrics 与报告逐字相同,结果确定。
- [x] **S6 汇报**:已对照 H1–H3 汇报(2026-11-22)。
- [x] **S7 分支:EDF 请求顺序**(用户 2026-11-22 要求继续推进到可做 demo):`exp_wftrace_1000genome_x2_edf`,与基线只差 `request_order: edf`。假设 H4:基线的超时来自请求顺序,EDF 下超时减少,巡检仍无偏离。跑两次确认。结果(`…_edf_bba2099`、`…_edf_1c09127`,两次 metrics 相同):超时 3 → 1(剩 WF-B 的 chr22 注释文件),巡检偏离 0,H4 成立;需求预报首次误差均值 154 s → 23 s。
- [ ] **S8 demo 视图**:每次运行生成 `timeline.html`(站点、各 workflow 的传输与任务时间线、两段中转链路的占用、graph B 与需求预报);实验代码按 §6 提炼进 `src/lib/wftrace/experiment.py`,两个 tag 共用。基线用新代码重跑一次生成视图。

## 待办与决策

- **TBD(待我决定)**:无(S0 已全部定下)。
- **TODO(待验证/执行)**:S1–S6。

## 当前状态

Exp3 S0–S6 完成(H1 因 3 次超时不成立,H2/H3 成立);正在做 S7 EDF 分支与 S8 demo 视图。Exp2 暂停(S4 进行中),计划与流水账已归档。

## 实验历史

- **Exp1(已结题,2026-07-28—2026-08-26)**:AI 驱动科学实验、autonomous experimentation、self-driving laboratory、digital twin、实验选择、设备控制、科学工作流、AI agent 与相关系统平台的背景调研;不运行实验。归档见 [`20260826_probe_landscape_exp1.md`](archive/20260826_probe_landscape_exp1.md)。
- **Exp2(暂停,2026-08-26—2026-11-22)**:调研 SENSE-O Intent API 2.0.4 对 virtual network link 条件的表达能力,并与本组 workflow/science-SLA 模型 harmonize;S0–S3 完成,S4 crosswalk 第一轮待审阅,无结论。归档见 [`20261122_probe_sense_intent_harmonize.md`](archive/20261122_probe_sense_intent_harmonize.md)。
- **Exp3(进行中,始于 2026-11-22)**:真实 workflow trace(两份 1000genome)端到端接入 network agent,并落地 SciNet 需求预报;tag `exp_wftrace_1000genome_x2`。
