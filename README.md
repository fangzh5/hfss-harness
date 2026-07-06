# hfss-harness

`hfss-harness` 是一套基于 PyAEDT 实现、面向 Ansys HFSS/AEDT 的 Python workflow harness，用于把参数优化、单变量扫参、固定参数验证、运行输出和 dashboard 观察串成统一流程。

本仓库不包含 Ansys 软件、许可证、仿真结果或加工输出。真实运行时需要你在本机准备可用的 AEDT/HFSS 环境和授权。仓库只保留一个最小示例工程：`hfss/patch.aedt`。


## 版本说明

- 当前公开版本：`0.1.0`。
- 当前阶段：Alpha / first public snapshot。接口、配置字段和 workflow 仍可能调整。
- 版本号以 `pyproject.toml` 中的 `[project].version` 为准；发布到 GitHub 后建议使用 Git tag 标记正式快照。

## AI 辅助生成说明

本项目的部分代码、文档、配置模板、Codex skills 和示例整理过程使用了 AI 辅助生成。发布前已进行人工筛选、脱敏、清理和基础验证；真实 HFSS/AEDT 仿真结果、工程参数和工程决策仍应由使用者结合 Ansys 环境独立核验。
## 核心功能

- `opt`：参数优化。
- `sweep`：单变量逐个扫参。
- `val`：固定参数组合验证。
- Dashboard：查看运行状态、进度和结果 snapshot。
- 支持算法：DE/JADE、CMA-ES、NSGA-II、Bayesian Optimization、PSO。
- Skills：提供 Codex 中的人机交互 workflow。

## 安装与依赖

基础要求：

- Python `>=3.11,<3.14`。
- 推荐使用 `uv` 管理环境。
- 真实 HFSS/AEDT 自动化运行需要本机安装并授权 Ansys Electronics Desktop / HFSS。
- Ansys AEDT/HFSS 版本建议高于 `2023.2`，推荐 `2024 R1` 或更新版本。
- HFSS/AEDT 自动化通过 PyAEDT 接入，对应依赖在 `hfss` extra 中安装。PyAEDT 官方 GitHub：[ansys/pyaedt](https://github.com/ansys/pyaedt)。

安装 HFSS/AEDT 自动化环境：

```bash
uv sync --extra hfss --extra dev
```

安装可选优化后端：

```bash
uv sync --extra bo --extra dev
uv sync --extra cmaes --extra dev
uv sync --extra bo --extra cmaes --extra hfss --extra dev
```

Extras 说明：

- `dev`：开发辅助依赖。
- `hfss`：PyAEDT / AEDT 自动化依赖。
- `bo`：BoTorch Bayesian Optimization 依赖。
- `cmaes`：CMA-ES 局部精修依赖。

## Quick Start

### 方式 A：用 Codex 发起一次任务

如果你是从 GitHub clone 本仓库后在 Codex 中使用，最简单的方式是直接用自然语言提出任务。仓库自带一个最小示例工程 `hfss/patch.aedt` 和配套 config `configs/example_patch_opt.json`，可以先这样说：

```text
我要对 hfss/patch.aedt 执行一次 opt 任务。
```

也可以换成自己的工程路径，或指定其他任务类型：

```text
我要对 <你的 .aedt 文件路径> 执行一次 sweep 任务。
我要对 <你的 .aedt 文件路径> 执行一次 val 任务。
```

如果 Codex 没有自动匹配 skill，可以显式使用 `hh-sim`：

```text
$hh-sim，我要对 hfss/patch.aedt 执行一次 opt 任务。
```

`hh-sim` 会读取仓库规则和工程 metadata，然后追问缺失信息，例如 design、setup、sweep、优化变量、参数范围、目标、算法和时间预算。真正启动前，它应该停下来让你确认参数范围、目标、算法和预计结束时间。任务启动后，可以在 dashboard 中观察仿真进度、当前参数、fitness 变化、S 参数曲线和最佳结果。

示例 dashboard（Codex 发起优化任务后的已达目标状态）：

![example_patch_opt dashboard target reached snapshot](docs/assets/example_patch_opt_dashboard_target_reached.png)

### 方式 B：手动复制模板运行

1. 复制配置模板：

```bash
copy configs\template_opt.json configs\my_task.json
```

2. 修改 `configs\my_task.json`：

- `name`：任务名。
- `task_type`：`opt`、`sweep` 或 `val`。
- `parameters` / `study.variables` / `cases`：参数范围、扫参变量或验证 case。
- `target`：优化或验证目标。
- `algorithm`：算法配置。
- `simulator.hfss.project_path`：你的本机 `.aedt` 工程路径。
- `simulator.hfss.design_name`、`setup_name`、`sweep_name`：HFSS 设计和求解设置。

3. 启动任务：

```bash
python optimizer\cli.py configs\my_task.json
```

4. 查看输出：

```text
runs/<task>/<timestamp>/
```

## 命令入口

推荐入口：

```bash
python optimizer\cli.py <config>
```

安装为 console script 后也可以使用：

```bash
hfss-harness <config>
```

Dashboard 相关参数：

```bash
python optimizer\cli.py <config> --dashboard --dashboard-browser
python optimizer\cli.py <config> --no-dashboard
python optimizer\cli.py <config> --no-dashboard-browser
```

`optimizer/main.py` 和 `optimizer/run_optimizer.py` 只保留兼容用途，不建议作为新任务入口。

## 配置文件关键字段

- `name`：任务名称。
- `task_type`：任务类型，支持 `opt` / `sweep` / `val`。
- `parameters`：优化参数定义，用于 `opt`。
- `study.variables`：扫参变量定义，用于 `sweep`。
- `cases`：固定参数组合，用于 `val`。
- `target`：频段、门限、约束或目标定义。
- `algorithm`：优化算法和预算。
- `simulator.hfss`：HFSS/AEDT 工程路径、design、setup、sweep 和结果表达式。
- `output`：输出目录和结果保存选项。

`opt` 参数建议使用连续范围加量化精度：

```json
{
  "name": "var_a",
  "min": 0.5,
  "max": 1.5,
  "unit": "mm",
  "resolution": 0.01
}
```

## 任务类型

### opt

用于参数优化。新任务建议从 `configs/template_opt.json`、`configs/template_bo.json`、`configs/template_cmaes.json` 或 `configs/example_patch_opt.json` 复制配置。

### sweep

用于单变量逐个扫参。多个变量会按顺序分别扫描，不做笛卡尔积组合。

### val

用于验证若干组固定参数，不执行搜索。推荐 case 形式：

```json
{
  "name": "case_001",
  "params": {
    "var_a": "1.0mm"
  }
}
```

## 输出与 Dashboard

任务默认输出到：

```text
runs/<task>/<timestamp>/
```

常见输出包括：

- `config.json`
- `logs/`
- `*_data.jsonl`
- `*_dashboard_state.json`
- CSV / Markdown 汇总文件
- 可选图像输出
- 可选 AEDT 工作副本或 best project

手动查看已有 run：

```bash
python optimizer\dashboard\serve_dashboard.py --task-dir <run_dir>
```

然后打开：

```text
http://127.0.0.1:8765/?task_dir=<run_dir>
```

## 目录结构

- `optimizer/`：任务入口、执行器、算法、HFSS adapter、metrics、dashboard。
- `configs/`：公开配置模板和示例 config。
- `hfss/patch.aedt`：公开最小示例工程。
- `docs/`：补充文档和示例截图。
- `.codex/skills/`：仅保留 `hh-sim` 和 `hh-iter` 两个公开 workflow skills。

本地目录通常不进入公开仓库：

- `hfss/` 下除 `patch.aedt` 外的其他 `.aedt` 工程。
- `runs/`：任务输出。
- `temp/`：临时工作副本。
- `data/`：本地数据、报告和导出。

## Skills

`.codex/skills/` 中保留第一版公开 workflow 文档，不是运行时依赖：

- `hh-sim`：创建并确认 `opt` / `sweep` / `val` 配置。
- `hh-iter`：分析已完成优化轮次并草拟下一轮配置。

## License

MIT. See [LICENSE](LICENSE).
