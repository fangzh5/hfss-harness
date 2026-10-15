# 0.2.0 迁移与能力边界

0.2.0 将优化（opt）、扫参（sweep）和单点验证（val）接入同一案例执行流程，并提供沿线条自动布置过孔、从 AEDT 工程导出 Gerber，以及根据加工包重建几何与材料的 skills。旧版本及其运行目录应独立保留；不要复用已有 journal 或覆盖旧 best。本版不实现断点续跑，也不新增模型组装能力。

## 安装后建立工作目录

```powershell
python -m optimizer.scaffold <新工作目录>
```

该命令复制模板、AEDT 2023 R2（2023.2）的带过孔示例工程、文档及五项公开 skills 到目标目录，遇到同名文件拒绝覆盖。包内不含私有运行日志、求解缓存或用户工程。进入新目录后，用 `python -m optimizer.cli configs/<任务>.json` 或 `hfss-harness configs/<任务>.json` 运行；源码也支持同一模块入口，原文件形式 `python optimizer/cli.py <config>` 保留。

## 配置与数据

- 优化使用`parameters/target/algorithm`；扫参使用`study`（oat/grid/explicit），不要在扫参混入顶层优化字段；验证使用明确`cases[*].params`。
- 未知变量、单位/variation不匹配、缺频带、NaN/Inf、缺少必需指标会失败，不再填零或切换到其他setup/sweep。旧的仅cost日志不能直接作为可信BO训练数据；需匹配工程/求解来源及原始曲线。
- JSON配置中的相对工程路径从配置文件所在目录解析，并在加载时固定为绝对路径，保证源码和wheel工作目录一致。相对work_dir/output_dir仍从源工程所在目录解析。外部调用内部执行器并直接传字典时，应提供绝对工程路径；搬动旧配置后先核对路径，不沿用对安装包目录的隐式依赖。
- 公开模板已统一使用标准模型的patch_x/patch_y、59–61GHz评价频带和55–65GHz结果覆盖；默认关闭拥有的会话并清理副本。旧模板的patch_w、到66GHz的评价范围和保留会话设置不应直接用于当前标准模型。
- 验证任务的顶层`evaluation_mode="existing_results"`：不求解、不赋值、不保存源文件，案例参数必须与现有结果匹配。需要已有求解缓存；model-only best不包含缓存，须先独立求解。
- `optimization.end_at`必须带时区，是案例之间的软预算；不能强制中断活跃求解。失败和复验的分析调用与缓存命中分别记录。
- `optimization.keep_working_copy=true`显式保留已关闭的temp工作工程及缓存，便于后续已有结果读取；默认仍在确认关闭后清理。它不保持AEDT会话运行。
- `optimization.save_interval`默认10，0关闭周期best快照。周期保存独立复验当前best，之后恢复搜索；最终导出后不再恢复/保存工作模型。runs中的快照不覆盖，最终best需独立重开检查赋值前参数/几何再求解。
- Pareto文件与看板中的无穷拥挤距离写作`crowding_distance=null, crowding_unbounded=true`，避免非标准JSON的Infinity；内部NSGA排序仍保留原数学含义。目标值/参数等其他非有限数据不因此被允许。

## 预检与远场

```powershell
python -m optimizer.inspect_aedt <工程.aedt> --design <设计> --setup <设置> --sweep <扫频> --temp-root temp --runs-root runs/inspection
```

预检始终在拥有的non-GUI COM会话及唯一temp副本中只读，返回设计、原始变量表达式/单位、对象、setup/sweep、馈电和报告量。缺选择返回needs_input/退出2，错误显式选择或完整性/关闭失败退出1；完整读取退出0。可用quantity不等于已有求解结果。

远场需已定义采样球及保存场的solution。可用`target.far_field.setup_sweep_name`单独指定场结果，不必与S参数扫频相同。`freqs`明确取值；四个主截面只报告截面峰值，不作为全局峰值目标。显式`phi_samples_deg`至少8个不同方位角；CSV fallback检查Theta覆盖0–180度、Phi周向及完整笛卡尔网格后才标记sampled_sphere。采样峰值不等同连续角度全局最大值。

扫参`study.tracking_port`保留原显式Start/End积分线偏置；原生OnEdge附着线由AEDT几何再生，直接读取实际边坐标而不解除附着。附着线不能用gap强行覆盖；其他附着类型明确拒绝。

## PCB工作流与验证范围

`hh-pcb`更名为`hh-export-pcb`，`hh-rebuild`更名为`hh-rebuild-pcb`。公开入口为`optimizer.fabrication.native_export`、`cam_import`及`cam_rebuild`，配置/层角色/孔层对必须明确。导出包含实际铜、介质外框GKO、钻孔和逐层叠层；copper/PEC孔默认金属化，明确标注优先。未知材料或工艺字段询问缺项，不静默补物理默认值。

当前原生提取支持mm、Z向等截面实体、闭合直线轮廓及整圆；CAM支持的region/整圆flash/圆钻孔和显式层对按实际解析器范围处理。不支持特征明确拒绝，不遗漏几何后报告成功。重建完成几何和材料，不自动恢复端口、边界、netlist或求解设置；复杂外部CAM及重建电磁等价尚未验证。具体范围见[PCB工作流](pcb-stackup.md)。

## 兼容性

Python 3.11–3.13 已完成干净安装检查；真实仿真环境为 Windows / AEDT 2023.2 / PyAEDT 0.18.1 / COM / non-GUI。其他版本、gRPC和共享桌面复用尚未验证。自动关闭仅限本次拥有的会话。首次在新环境使用时，先运行只读预检，再验证小任务。过孔入口的可视会话行为见[安全创建过孔](via-creation.md)。
