# Agent Reference

按需展开文档。根目录 `AGENT.md` 只放最小入口说明；这里放细节。

## 项目一句话

基于 HFSS / AEDT 的参数优化、扫参和验证工具，包含过孔建模、PCB 导出与几何重建，运行状态通过 snapshot 驱动 dashboard 展示。

## 当前入口结构

- `optimizer/cli.py`
  - 唯一任务入口
  - 源码与安装包都可使用 `python -m optimizer.cli <config>`；源码也支持原文件形式
  - 负责：配置解析、输出目录、日志、dashboard 服务、浏览器打开、调用任务执行器
- `optimizer/task_runner.py`
  - 内部执行器
  - 负责：读取配置、创建 adapter / algorithm、执行 `opt` / `sweep` / `val`、写运行产物
- `optimizer/dashboard/serve_dashboard.py`
  - 独立 dashboard 服务

Dashboard runtime modes:

- `opt`: full dashboard view
- `sweep`: simplified dashboard view
- `val`: simplified dashboard view
- live state files: `opt_dashboard_state.json`, `sweep_dashboard_state.json`, `val_dashboard_state.json`

兼容层：

- `optimizer/main.py`
- `optimizer/run_optimizer.py`

它们只用于兼容旧导入，不应再当成新任务入口。

## 目录语义

- `configs/`：任务配置
- `hfss/`：源工程
- `runs/<task>/<stamp>/`：运行产物
- `temp/<task>/<stamp>/`：临时 HFSS 工作副本
- `optimizer/`：执行逻辑
- `docs/`：补充文档

## 模块边界

- `adapter` 只负责和 HFSS/AEDT 交互
- `fitness` 只负责把结构化指标映射成标量 cost 或 objective 向量
- `algorithm` 只负责搜索，不直接知道 HFSS 细节
- `dashboard` 只消费 snapshot / 输出文件
- `sweep` 按 OAT/grid/explicit 生成案例，共用案例执行器并恢复基线

不要轻易打破这些边界。

## 配置约定

### 起手模板

- 优化、扫参和验证分别复制 `configs/template_opt.json`、`configs/template_sweep.json` 和 `configs/template_val.json`
- 优先改：
  - `name`
  - `task_type`
  - `parameters`、`study.variables/study.cases` 或 `cases`
  - 优化/验证的 `target`，或扫参的 `study` 内评价字段
  - 仅优化需要的 `algorithm`
  - `simulator.hfss.project_path`

JSON中的相对工程路径按配置文件所在目录解析；相对 `optimization.work_dir` 和 `output.output_dir` 按源工程所在目录解析。标准模板中的 `../hfss/patch.aedt`、`../temp`、`../runs` 对应工作目录内的 hfss、temp、runs。通过Python字典直接调用内部执行器时，应提供明确的绝对工程路径。

模板使用标准模型的 `patch_x/patch_y`、Setup1/Sweep及59–61GHz评价频带，原扫频覆盖55–65GHz。它们是起点，换模型后仍需核对实际变量和求解设置；预检见 `python -m optimizer.inspect_aedt --help`。

### opt

- `task_type = "opt"`
- 必需字段：
  - `parameters`
  - `target`
  - `algorithm`
- 推荐参数定义：
  - `name`
  - `min`
  - `max`
  - `resolution`
  - 常用可选：`unit`
  - 约束可选：`constraint`
- 新优化任务不要再依赖 `count` / `step`

#### opt 字段补充

- `target.freq_band`
  - 优化频段
- `target.s11_threshold`
  - 默认最常用门限
- `target.bandwidth_target`
  - 需要显式保带宽时再填
- `target.gain_min`
  - 需要增益约束时再填
- `algorithm.method`
  - `de` / `nsga2` / `pso` / `bo` / `cmaes`
- `algorithm.strategy`
  - `de` 时常用 `jade`
- `optimization.initial_point`
  - 要从已知好点继续精修时填写

#### opt 规则

- `DE/NSGA-II` 内部连续搜索，但实际仿真点按 `resolution` 量化
- 量化后重复点直接复用结果，不重复仿真
- 单参数依赖约束优先做单参数 repair，不默认整点丢弃

### sweep

- `task_type = "sweep"`
- `study.mode` 为 `oat`（默认）、`grid` 或 `explicit`
- OAT/grid 使用 `study.variables`，每个变量包含 `name/start/stop/step`
- explicit 使用 `study.cases`，每项为 `{"name": "case_001", "params": {"var_a": "1mm"}}`
- 评价频带和门限放在 `study.freq_band/s11_threshold` 等字段，不混入顶层 `target/parameters/algorithm`

#### sweep 规则

- OAT一次扫描一个变量；grid扫描变量取值的笛卡尔积；explicit按给定组合执行
- `study.max_cases` 限制点数；OAT点数为各变量点数之和，grid为乘积，explicit为条目数
- 每个案例从同一份完整基线开始，结束后恢复参数及已配置的CAD观测
- 当前主链会输出 `summary.json` 和 `sweep_summary.png`

例如两变量各3点，OAT为6例、grid为9例。设置 `study.mode="grid"` 即使用同一份变量表生成组合；explicit可省略变量表，直接提供 `study.cases`。

### val

- `task_type = "val"`
- 必需字段：
  - `cases`
  - `target`
- `cases[*]`
  - 推荐写法：`{"name": "...", "params": {...}}`
- `target`
  - 至少要能驱动同一套 fitness / 判定逻辑，通常先给 `freq_band` 和 `s11_threshold`
- `evaluation_mode` 默认 `solve`；`existing_results` 不赋值、不求解、不保存，只接受与现有参数一致的已有结果，需要相邻求解缓存
- `valid=false` 表示数据或评价无效；有效但未达目标可以是 `valid=true, target_met=false`

## 输出物

### 可选 CAD 观测（opt / sweep / val）

`output.geometry_snapshot` 可设为 `{"objects": ["patch", "probe"], "absolute_tolerance": 1e-8}`。
对象名必须实际存在、唯一且非空；容差为正有限数，单位采用工程 model units。
启用后，`cases.jsonl` 记录 `geometry_baseline`，每个求解案例的 `extra_metrics.geometry_snapshot`
保存 live bounding box、尺寸、单位和参数；正常恢复的案例还记录 `restored_geometry`。
恢复时实际包围盒须与初始基线一致，不能仅靠表达式一致放行。缺对象、无效几何或恢复失败会使任务失败。
用于核对尺寸/位置的对象应与验收意图一致；包围盒核验不代表完整拓扑、材料或导体连通验收。
最终制造点复验为保存而保留其状态，不标记为已经恢复的案例。

最优模型导出先持久化已验证的工作工程，再创建独立 AEDT 文件快照并核对
SHA256；不切换活动工程，不复制求解缓存。最终 best 导出成功后保留当前最佳点，
结束与 disconnect 不再恢复参数、fit_all 或保存工作副本；按关闭结果清理或保留 temp。
原工程及已导出的快照不被回写。搜索中的案例隔离、周期导出后继续搜索及失败恢复仍恢复基线。
`optimization_summary.json` 的 `export_verified=true`
记录最终内存模型求解及文件导出成功；独立重开验收仍需在任何案例赋值前检查
磁盘模型的初始变量/CAD，随后用新副本求解并核对曲线。搜索求解、缓存复用、
最终验证与独立重开求解分别计数。

### 按仿真间隔保存 best

- `optimization.save_interval` 为非负整数，默认 10；N > 0 按搜索 sim 计数每 N 次触发，0 关闭周期导出。
- cache 命中与导出复验不增加搜索 sim 计数；未获得曲线的求解失败也不增加该计数。
- 保存截至该时刻的 best：回到其制造参数点做独立复验，写入 `runs/<任务>/<批次>/best_after_<sim>_sim.aedt`；随后恢复搜索基线继续运行。
- 多目标 best 代表点由完整种群更新选出；间隔若在种群内部跨过，合并延迟到该批更新后导出一次。
- 每次周期快照增加一次复验求解。`algorithm.max_simulations` 限制搜索求解；summary 的
  `export_verification_solve_attempts` 单独计入周期和最终复验，`total_solve_attempts` 为两者总和。
- 有 end_at 时为下一次导出及最终保存预留时间；不足时记录 `best_model_export_skipped`，不伪报已有文件。
- `save_best_on_exit=true` 独立控制退出时最终 `*_best.aedt`，不受 save_interval=0 影响。
- 快照路径必须全新，不覆盖旧 best；周期保存失败使任务失败并保留已有 journal。
  历史日志的 checkpoint 字段只是间隔标记，实际导出以 `best_model_exported` 事件与文件为准。

### 优化失败批次与停止

- 完整批次中每个失败候选都有 `valid=false` 的结果槽位，包含索引、参数和原因；约束拒绝、无效缓存评价及求解失败均适用。DE/PSO 跳过失败分数但生成下一批；BO/代理模型不将失败点加入训练数据。NSGA-II 的失败成员不进入 Pareto 前沿或代表最优，跨代保留其无效标记。
- CMA-ES 需要完整批次和有限分数；失败点的处罚严格大于同批有效分数，无法表示时明确失败，禁止失败点成为 best。
- 全失败的完整批次也计一代，并可推进算法生成新候选；它同时受最大迭代数、连续失败、候选尝试、求解次数与时间预算限制，全部失败不能标记成功。未完成批次不提交为完整一代；`cases.jsonl` 的 `batch_finished` 记录计划/已评估/有效数量以及是否更新算法。
- 0.2.0 不提供断点续跑或中断恢复入口。停止后保留已有结果和导出快照；重新启动使用新的任务目录和工作副本。案例内参数回滚与源工程保护继续生效。
- NSGA-II 在目标达到、求解预算或停机导致半批停止时，仅从已获得的有效结果和此前有效种群中选最终代表点；不补造未评估成员、不提交完整一代、不推进下一代。`partial_batch_best_selected` 记录来源；最终导出仍独立求解验证。跨代保留完整评价记录，包括 target、指标和原仿真编号。

`simulator.hfss.close_desktop` 对 sweep 同样生效。只有确认工程/桌面已关闭才自动清理工作副本；
关闭失败或保留会话时，副本保留供检查，原工程始终受复制保护。
`optimization.keep_working_copy=true` 会保留已关闭的temp工程及缓存，便于后续只读；使用/归档后应清理。标准模板关闭自己拥有的会话，默认不保留副本。

### opt

- `config.json`
- `opt_history.csv`
- `opt_data.jsonl`
- `opt_dashboard_state.json`
- `*_best.aedt`
- `logs/`

多目标模式额外可能有：

- `opt_pareto_front.json`
- `opt_pareto_front.png`

### sweep

- `config.json`
- `sweep_data.jsonl`
- `sweep_summary.csv`
- `summary.json`
- `sweep_summary.png`
- `sweep_dashboard_state.json`

### val

- `config.json`
- `val_data.jsonl`
- `val_results.csv`
- `val_report.md`
- `val_overview.png`
- `val_dashboard_state.json`

## 当前实现要点

- `DE` 默认为 `JADE`
- 多目标主路径使用 `NSGA-II`
- `PSO` 保留，但不是默认主力
- dashboard 只读运行产物，不参与优化逻辑
- `cli.py` 会为 `opt / sweep / val` 都拉起 dashboard；其中 `sweep / val` 使用简化视图
- 这里的默认行为属于 `cli.py`，不是 `AGENT.md` 的模板分流语义

## 需要继续展开时看哪里

- 任务入口与日志：`optimizer/cli.py`
- 执行主流程：`optimizer/task_runner.py`
- 配置校验：`optimizer/task_config.py`
- 约束、量化、参数处理：`optimizer/core/parameter.py`
- fitness：`optimizer/core/fitness.py`
- 单目标算法：`optimizer/algorithms/de.py`
- 多目标算法：`optimizer/algorithms/nsga2.py`
- HFSS 适配器：`optimizer/adapters/hfss_adapter.py`
- OAT/grid/explicit案例生成：`optimizer/core/study.py`；扫参执行：`optimizer/sweep.py`
- 显式验证：`optimizer/validation.py`
- dashboard 数据桥：`optimizer/dashboard/state_bridge.py`
- 过孔工作流：[规划](via-planning.md)、[建模](via-creation.md)
- PCB导出、叠层与重建：[PCB工作流](pcb-stackup.md)
- 版本迁移及兼容边界：[0.2.0迁移](migration-0.2.0.md)

## 编码

- 涉及中文的新增或修改文件统一使用 UTF-8。
