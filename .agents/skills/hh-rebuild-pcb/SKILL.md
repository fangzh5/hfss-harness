---
name: hh-rebuild-pcb
description: Use when reconstructing or auditing an HFSS/AEDT verification model from Gerber, Excellon drill, PCB fabrication packages, stackup notes, or KiCad/Altium review files.
---

# HFSS Harness Rebuild PCB

当 Gerber/Drill/叠层说明已经是加工依据，而用户希望反向重建一个 HFSS/AEDT 模型用于结构核对或 S 参数对比时，使用这个 skill。这个流程是反向校验，不是 PCB 设计源建模，也不是替代加工文件。

## 核心原则

复用同一任务已经确认的输入和授权；只询问仍缺少、冲突或无法从权威输入可靠读取的字段。用户已经授权按当前基线测试，不再次索取相同计划的确认。

本项目已确认的默认规则：过孔对象的模型直径作为钻孔直径，copper/PEC过孔默认金属化，特别标注优先。仅按此规则输出/结构验证时不额外要求镀层厚度，不捏造厚度。没有镀层尺寸的几何测试可明确使用零厚度PEC金属化孔壁；不要把钻孔填成实心铜柱后称其为真实PTH。有限镀层厚度/损耗或S参数对比属于需要完整EM recipe的另一验收范围。

原始AEDT、既有加工文件默认保留；重建在唯一temp工作工程创建，核验保存重开后字节快照和证据进入runs。只关闭本次工程，保留借用的会话和其他工程；源标准模型更新遵循用户明确授权及备份/Git保护。

保存重开验收优先使用独立拥有的AEDT会话，不在其中加载其他用户工程。核对目标环境/API版本，不将一个环境的通过扩展到其他版本。若会话失效，记录应用错误和其他工程影响，不对失效项目代理调用Save，不把失败清单留成started或声称其他窗口已保留。

建模前须有完整、可靠的叠层、材料参数、铜厚、介质厚度和过孔层对。可以来自用户已确认输入或当前授权基线的原生核验记录；仅缺失或冲突字段需要询问。Gerber只描述二维铜图形，不能单凭层名猜出三维叠层。

## 建模前输入完整性检查

运行PyAEDT或创建几何前，核对以下字段及来源；复用已确认内容，不重复要求逐项确认：

- 权威输入：Gerber、Drill、板框、叠层说明、`fabrication.json`、KiCad/Altium 工程等。
- 铜层数量和自顶向下顺序。
- 每一层铜厚，说明是基铜还是成品铜。
- 每个介质层的材料、厚度、`Dk`、`tanD/Df`。
- 介质建模方式：只建相邻铜层之间的 slab，还是完整板体填充。
- 过孔定义：钻孔直径、焊盘是否由 Gerber 定义、每组过孔的起止铜层。
- 需要忽略的对象：端口、空气盒、辐射边界、标注、辅助线、测量图形等。
- 反向模型用途：仅结构可视化，还是要和原始 HFSS 做 S 参数对比。

如果缺少关键信息且不能安全推断，停下来问用户。不要默认四层板、固定铜厚、某个介电常数或 L1-LN 通孔。

## 流程

1. 环境或机器不确定时，先读 `references/environment.md`。
2. 需要收集叠层信息时，读 `references/intake-checklist.md`。
3. 检查加工输入。
   - 板框从实际GKO/Profile解析闭合中心线；缺失时不能自动用铜包围盒补成板体。当前profile_io支持闭合直线轮廓，曲线板框仍需后续支持或明确拒绝。
   - 读取`stackup.json`及叠层说明，核对逐层材料、厚度、绝对Z、Dk/Df及来源；结构化数据与说明或已确认输入冲突时，先解决冲突。旧`fabrication.json`只有几何叠层并不代表材料输入完整。读取细节和缺失信息提问见`references/intake-checklist.md`。
   - 如果只有 Gerber/Drill，用可靠解析器或 CAM 工具结果解析，避免临时字符串解析几何。
4. 先生成重建计划，不直接建模。
   - 铜层表：层名、`z_bottom`、`z_top`、铜厚、材料。
   - 介质表：材料、厚度、`Dk`、`tanD`、z 区间。
   - 过孔表：层对、钻孔半径/直径、z 起止、数量。
   - 每层 dark/clear 极性处理方式。
   - 排除对象和已知简化项。
5. 展示计划与已知简化项；复用已有明确授权，仅新增未确认的关键字段需要用户补充。
6. 在输入完整且已有建模授权时运行PyAEDT。
   - 做S参数对比时按完整EM recipe选择有限厚铜或明确的理想导体近似，并保留材料、损耗和端口定义。
   - 仅结构测试可使用理想PEC孔壁，必须说明其不包含有限镀层厚度和损耗。
   - 介质材料必须写入确认过的 `Dk` 和 `tanD`。
   - 默认不重建端口，除非用户明确要求重新创建激励端口。
   - 结构检查按来源文件分配可区分颜色：每层铜Gerber、GKO对应介质体、Drill孔壁分别着色，同一来源保持一致。默认透明度0.7，用户指定值优先；核验实际Color/Transparent并关闭会覆盖颜色的材料外观。显示调整不得改变Model、材料、Solve Inside、几何或边界。
7. 重建后验证。
   - 同一个 `.aedt` 只打开一个实例。
   - 检查对象数量、z 位置、材料、板框、铜厚和过孔层对。
   - 有原始 HFSS 时做结构摘要对比，并区分“有意简化”和“真实几何不一致”。

用户提供文件包后，先自动读取已有字段再询问缺项，不要求重新填整份清单。Gerber已经定义焊盘、普通板体形状已明确或排除对象已有规则时直接复用，仅有歧义才提问。结束时给出保存模型/预览路径、层与孔数量、材料核验结果和已知简化项，明确区分已验证完成、缺输入、不支持和执行失败。仅结构重建完成不能报告为可直接仿真；端口/边界/求解配置需另行补齐。按用户要求打开或关闭本次工程。

## 对比规则

对比反向模型和原始 HFSS 时：

- 先比几何摘要：对象名、材料、bbox、z span、顶点 z 值、过孔数量、层分组。
- 原始 HFSS 对象可能跨多个铜层；不要自动判定为错误。
- 不要假设“一个对象 = 一个铜层”。HFSS 里一个对象可能包含多个 z slab。
- 端口、空气盒、辐射边界、辅助对象不参与铜图形对比。
- 如果用户在打开的 AEDT 中手工改过模型，优先读取当前会话；否则先让用户保存再读取文件。

## 常用命令

当前公共 `optimizer.fabrication.cam_io` 可直接读取真实Gerber多边形region、整圆flash及圆形Drill，并明确拒绝未支持特征；需要层映射/叠层/材料输入。当前旧 `rebuild_hfss_from_fabrication.py` 仍以自有fabrication.json为输入，不得把该JSON重放称为外部Gerber解析。新的实际CAM规划与隔离结构执行入口见下段；更多特征支持仍在开发，下面旧命令只适用于检查过的兼容中间模型。

规划入口`python -m optimizer.fabrication.cam_import <package-dir> --output <new-plan.json>`读取`hfss-stackup-2`和实际Gerber/GKO/Drill，保留逐层材料及孔层对；缺项返回needs_input报告，不启动CAD。数据契约与范围见[叠层与CAM入口](../../../docs/pcb-stackup.md)。此入口只生成规划，不能将planned报告为已重建。输入齐全且已有建模授权时，用`python -m optimizer.fabrication.cam_rebuild <package-dir> --temp-root <temp-dir> --runs-root <runs-dir> --aedt-version <version>`默认启动独立拥有的non-GUI COM会话（仅需要用户视觉确认时加--gui，并核对实际模式）；只在唯一temp工程建模，原生核验、保存重开后归档runs并关闭拥有的会话。当前支持范围/前置拒绝及容差见同一文档，不绕过检查运行未支持拓扑。completed_geometry只代表结构/材料链路，缺项/错误分别为needs_input/failed，不能称为EM等效。已有确认记录需明确整理成该叠层，不静默把旧版或测试专用schema当成当前schema。

旧脚本读取Markdown/JSON中的层高和厚度，但不读取结构化Dk/Df，且仅支持统一介质材料；实际建模必须显式传入已确认的材料名、Dk、Df，缺失或与叠层材料冲突时在CAD连接前拒绝，多材料叠层拒绝使用该入口。新实际CAM入口按hfss-stackup-2逐层建材，旧入口不具备此能力。

旧入口的create_vias是实心铜柱，仅为历史几何预览实现，不是当前钻孔/金属化孔壁重建；现在含过孔输入只允许dry-run，实际建模在CAD连接前拒绝。有过孔的加工包须使用已验证的钻孔/孔壁路径，不可为了运行旧命令将孔转换为铜柱。

保留绝对Z及每层材料参数。无文档时不能丢弃JSON中的介质或压扁铜层；有Z列必须读取。未知层、介质孔终层、缺失特征、非法单位/尺寸必须在连接CAD前拒绝，不能静默跳过。生成新HFSS设计做纯结构核验时，显式决定自动开放区域；RadiatingSurface是边界管理对象，不能按普通铜实体查询/计数。

真实验收须回读铜层/孔/介质的z、材质和几何，孔壁与实际Drill对齐；保存重开后在任何赋值前复验。钻孔穿过介质和铜的结构变化、PEC理想孔壁、仿真馈电/端口/空气区域排除需列入差异记录；结构通过不能据此宣称EM等效。

已经在Drill中定义的馈电过孔必须重建；用户明确标为加工过孔时，不能因仿真馈电名称而排除。原有铜净空保持不变：若该孔位处于铜层已有clear窗口中，不重复扣除孔面积或假设它连接该层铜。

跨板钻孔的布尔工具须充分伸出板面，避免端面几乎重合；板厚跨度内的实体才是最终孔范围。不能通过放宽核验阈值掩盖失真的孔轮廓，须回读实际圆孔和体积并记录容差。

先检查当前仓库脚本再运行。常见命令：

```powershell
python scripts\rebuild_hfss_from_fabrication.py <package-dir> --dry-run
python scripts\rebuild_hfss_from_fabrication.py <package-dir> --output-aedt <out.aedt> --aedt-version <version> --dielectric-material <confirmed-name> --dielectric-permittivity <confirmed-Dk> --dielectric-loss-tangent <confirmed-Df>
python scripts\compare_hfss_structures.py --source-project <source.aedt> --source-design <design> --rebuilt-project <rebuilt.aedt> --rebuilt-design <design> --output-json <compare.json>
python -m pytest tests\test_rebuild_hfss_from_fabrication.py -p no:cacheprovider --basetemp .pytest_tmp
```

某些机器上AEDT非图形启动可能失败。保留失败诊断，先核对版本、传输与兼容Python环境；不要自动切换GUI绕过用户的无界面调试要求。需要用户视觉确认时才使用显式--gui。

## References

- `references/environment.md`：环境依赖和排障。
- `references/intake-checklist.md`：建模前问题清单和建模后检查项。
