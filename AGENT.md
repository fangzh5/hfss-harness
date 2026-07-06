# AGENT

这是 `hfss-harness` 的任务入口说明。这里只保留模板分流和启动要求，字段细节写在各自模板里。

## 启动入口

- 唯一允许的任务入口：`python optimizer\cli.py <config>`
- 默认启动命令：`python optimizer\cli.py <config> --dashboard --dashboard-browser`
- 静默启动命令：`python optimizer\cli.py <config> --silent --no-dashboard --no-dashboard-browser`
- 不要使用 `optimizer/main.py` 或 `optimizer/run_optimizer.py` 作为启动入口。
- 仅看板入口：`python optimizer\dashboard\serve_dashboard.py --task-dir <run_dir>`

## 模板分流

- `opt` / 优化：`configs/template_opt.json`
- `sweep` / 扫参：`configs/template_sweep.json`
- `val` / 验证：`configs/template_val.json`
- `BO` 仍按 `opt` 入口处理，必要时继续从 `configs/template_bo.json` 读取。

## 约定

- 任务字段细节放到对应模板里
- 路径、命令、配置键名保持英文原样
- 说明性文字使用中文

## 按需阅读

- `README.md`
  - 需要查看环境安装、快速开始、默认启动方式、单目标默认行为时再读
- `docs/agent-reference.md`
  - 需要查看更细的任务字段、任务类型差异、输出文件、实现要点时再读

