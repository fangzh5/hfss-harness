---
name: hh-via
description: Use when creating, updating, or testing HFSS/AEDT via arrays along named modeler paths, with parameterized dimensions, explicit spacing rules, verified ownership, and isolated working models.
---

# HFSS Harness Via

沿命名路径规划、创建、核验过孔。产物和CAD证据写入 runs/autovia，工作工程放在唯一temp目录。本skill不启动电磁求解，也不从实心铜柱推断加工孔径。

## 输入与授权

- 确定工程、设计、路径、半径、底面Z和高度或起止Z、间距及max/min规则。表达式原样保留；数值不自动绑定旧变量。缺少间距必须询问。
- 前缀默认 <path>_via，颜色默认蓝色(0,0,255)，方向Z，默认最大间距、逐边采样；用户指定值优先，默认值在执行摘要说明。
- 逐边采样强制端点/转角，共享端点和闭合终点去重；max用ceil分段，min用floor分段，不满足的短段拒绝。孔间净距按真实XY圆柱位置检查，不能只看路径弧长。
- 已确认的尺寸、范围、策略与同一任务授权持续有效，不重复要求确认。用户要求重新收集输入时，不复用前一案例配置。只询问仍缺少或冲突的信息。
- 默认保护源文件。用户明确要求更新标准源模型时，先保存可回退字节备份、核对工程身份并保留Git回滚点，再限于授权修改；常规CLI不提供源文件覆盖选项。

## 检查与规划

1. 检查当前版本/API、工程绝对路径、设计、模型单位、局部/工程变量。当前原生入口只接受mm。连接已有会话必须明确PID并核验实际PID，不能仅信当前活动窗口。
2. 原生读取最终路径边、端点、中点、长度；匹配文件历史表达式后才能保留参数坐标。最终几何与历史不一致时拒绝，不能以旧文件或凸包/弦替代实时路径。
3. 使用 optimizer.modeling.vias.build_via_plan 纯规划，检查有限尺寸、连接性、分支、闭合状态、间距、数量上限、孔间距和声明的圆形keepout；失败不写CAD。
4. 记录来源、变量快照、表达式、尺寸、数量、实际间距/净距和摘要。原生入口支持Line与明确XY/YZ/ZX平面的固定角度AngularArc，逐边核对实时端点、弧长及1/4、1/2、3/4采样点后才能采用历史表达式；不能将曲线转成弦。XY圆弧+直线的创建、参数再生、所有权替换/回滚和保存重开已真实验收；YZ/ZX仍只做了离线表达式核验，闭合圆弧及其他版本真实覆盖待补。Spline、任意空间弧、变量弧角、单边整圆及未支持表达式明确拒绝；整圆须拆分为有两个原生顶点的多段弧。

## 安全创建与更新

- 新建使用 [安全入口](../../../scripts/create_vias_safely.py)：源文件复制到唯一temp，源快照、计划、CSV、journal和模型输出进入唯一runs目录。
- 已有匹配前缀对象不能仅凭名字认定归属。更新需要成功记录中的完整观测与当前阵列逐项匹配，由 create_checked_vias(..., owned_existing=...) 执行核验后事务切换；没有完整归属记录或阵列已被手工改变时停止并说明。
- 完整候选阵列逐孔核验之后才切换最终名称；事务失败恢复旧状态并复查。回滚未通过时必须报需要检查，不得继续求解或宣称成功。
- 当前可恢复范围为全局坐标、Z方向、无多边形分段的Model铜圆柱，Solve Inside=false。非模型铜柱隐藏材质属性，不符合该替换范围；其他非模型保护物体允许缺失隐藏属性，仍保护几何/状态。
- 核验原生包围盒、解析体积、Model、铜、Solve Inside、颜色、中心/半径/高度表达式和范围外对象；记录并恢复透明度、坐标系、组、线框和材质显示等实际暴露属性。
- 原生CreateCylinder显式设SolveInside:=False。不要假设已安装PyAEDT的create_cylinder接受solve_inside参数，也不要吞掉普通模型材质查询错误。
- 参数变化后回读真实CAD再生结果；路径尺寸变化可能使固定数量阵列违反间距，需重新规划/校验。表达式保留不等于布孔约束永久成立。
- 固定弧角的旋转系数保留圆心及起点/半径表达式。改变弧角需重新规划，不自动假设现有阵列跟随；实际Z方向孔底仍由z_start决定，原路径Z保留在记录中。

## 入口与证据

使用 scripts/create_vias_safely.py，必需参数：--project、--design、--path-name、--prefix、--spacing-mm、--radius、--z-start、--height。

- 已有会话：--aedt-process-id <PID>。不指定时新建会话；新会话/gRPC在目标环境仍需实际验收，不能静默连到另一个窗口。
- 安全替换：--ownership-manifest <successful-manifest.json>；完整归属与实时观测不一致会拒绝。
- 工作副本赋值：--variable name=value；再生验证：--check-variable name=value。CLI赋值目前只支持局部变量；原生尺寸校验可读取工程变量。
- --close-project只关闭工作工程，不追加保存，不退出借用的AEDT或其他工程。默认保留工作工程供检查；用户要求保存/关闭/不保存时遵循已有指令。
- 只做规划时使用 `build_via_plan`，不启动创建命令；公开CLI没有 `--no-save` 选项。已有阵列更新使用安全入口及完整归属记录。
- 一次性案例脚本存入runs/autovia/scripts，调试脚本存入runs/autovia/debug；通用逻辑留在optimizer/modeling和长期scripts。
- CSV独占创建，记录路径长度、标称/实际沿段间距、真实XYZ、路径Z和孔心距；保留来源快照、计划摘要、journal、属性/几何观测和保存模型hash。

## 完成判断

保存工作模型后重开，在任何赋值前核验对象、参数、尺寸和保护物体；核对源文件hash未变，再保留runs模型。用户只要求规划或不保存时准确描述范围，不自动升级为保存/求解。

汇报来源和工作模型、设计/路径、数量、尺寸表达式、实际间距/净距、CSV/模型/证据位置和工程是否打开。区分离线规划、实时创建、保存重开、目视核验与电磁结果。保存前返回False的故障注入只证明该范围，不能宣称覆盖部分写盘、进程崩溃或断电恢复。

Gerber/Drill/GKO交给$hh-export-pcb，外部CAM重建交给$hh-rebuild-pcb。按本项目确认规则，copper/PEC过孔的模型直径作为金属化钻孔直径，特别标注优先；不额外要求镀层厚度或添加未指定焊盘。层对须明确，不能把实心仿真柱称为真实镀层工艺模型。仿真任务交给$hh-sim。

AEDT/PyAEDT连接与建模在sandbox外运行；工具升级权限审核不等于再次索取已给出的任务授权。
