# Agent Reference

按需展开文档。根目录 `AGENT.md` 只放最小入口说明；这里放细节。

## 项目一句话

基于 HFSS / AEDT 的参数优化、扫参与验证工具，运行状态通过 snapshot 驱动 dashboard 展示。

## 当前入口结构

- `optimizer/cli.py`
  - 唯一任务入口
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
- `sweep` 只做单变量逐个扫描，并恢复基线

不要轻易打破这些边界。

## 配置约定

### 起手模板

- 新任务先复制 `configs/template_opt.json`，扫参和验证分别使用 `configs/template_sweep.json` 和 `configs/template_val.json`
- 优先改：
  - `name`
  - `task_type`
  - `parameters` 或 `study.variables` 或 `cases`
  - `target`
  - `algorithm`
  - `simulator.hfss.project_path`

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
  - `de` / `nsga2` / `pso`
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
- 必需字段：
  - `study.variables`
- 每个变量必须有：
  - `name`
  - `start`
  - `stop`
  - `step`

#### sweep 规则

- 一次只扫一个变量
- 多个变量时逐个执行，不做笛卡尔积
- 每个变量都从项目基线开始
- 每轮扫完恢复到同一份基线
- 当前主链会输出 `summary.json` 和 `sweep_summary.png`

### val

- `task_type = "val"`
- 必需字段：
  - `cases`
  - `target`
- `cases[*]`
  - 推荐写法：`{"name": "...", "params": {...}}`
- `target`
  - 至少要能驱动同一套 fitness / 判定逻辑，通常先给 `freq_band` 和 `s11_threshold`

## 输出物

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
- 单变量扫参：`optimizer/sweep.py`
- 显式验证：`optimizer/validation.py`
- dashboard 数据桥：`optimizer/dashboard/state_bridge.py`

## 编码

- 涉及中文的新增或修改文件统一使用 UTF-8。
