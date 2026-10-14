# PCB导出、叠层与CAM重建

0.2.0的公共入口包括原生AEDT提取/实际CAM导出、CAM读取/叠层检查，以及隔离AEDT几何重建。以下 `cam_import` 入口只读取文件和生成计划，不连接AEDT、不创建几何或求解；实际导出和重建分别见后文对应入口。计划完成或几何通过不等同电磁等效或加工验收。

```powershell
python -m optimizer.fabrication.cam_import <package-dir> --output <new-plan.json>
```

默认读取包根目录`stackup.json`；可用`--stackup`选择单独的已解析叠层。返回0表示实际CAM解析完成且计划写出；2表示缺少用户输入，报告列出missing字段；1表示非法输入/解析失败。已有输出文件拒绝覆盖。缺项报告不会启动CAM解析或CAD。旧版/测试专用schema和旧fabrication.json不会静默转换；根据已有确认记录显式整理成下述结构。

## 最小数据结构

`optimizer.fabrication.stackup`只定义LayerStack、LayerSpec、MaterialSpec和DrillSpec。几何继续使用cam_io已有的有序polygon/circle操作，不额外复制另一套几何模型或迁移框架。

`stackup.json`要求显式`schema_version="hfss-stackup-2"`、`unit="mm"`，包含：

- `coordinate_datum`：坐标与Z基准说明，绝对Z原样保留。
- `layers`：按顶到底排序；各层name、kind（copper/dielectric）、material_id、z_bottom_mm/z_top_mm、source。铜层另有copper_file和thickness_basis（modeled/base/finished）；厚度从Z区间计算，避免两份数值矛盾。
- `materials`：id、kind（metal/dielectric）、name、source，以及已知permittivity/loss_tangent/conductivity_s_per_m。不同介质引用各自材料，不按全局默认值覆盖。
- `drill_operations`：id、start_layer、end_layer、file、metallized、source。层对只能是两个不同铜层；孔尺寸和坐标从实际Drill读取。
- `profile_file`：实际闭合GKO的相对路径；文件路径必须留在选定包内，不能共用同一路径代表不同层或作业。
- `notes`：已确认简化或适用范围。

未知Z/材料名/Dk/Df/金属化/映射可以明确为null，`check()`区分missing与errors。非法数值、非布尔金属化、未知材料引用、重复层/文件、叠层重叠/间隙或顺序错误属于errors。当前仅支持连续、显式厚度的层叠；空腔或局部不同叠层需要后续扩展，不用猜测填充。

加工完整性不要求未知的Dk/Df；材料忠实重建计划要求每个介质的Dk/Df及材料来源。用户确认或原生读取的值直接复用，缺失/冲突时由skill汇总询问，不重复填整张表。未知频散、镀层厚度、端口、边界和求解设置不会自动补造；这些属于后续EM recipe。

`write_stackup_bundle(new_directory, stack)`从同一结构生成stackup.json与docs/stackup.md，回读确认一致。目录必须是新目录；允许保存明确标注缺项的草案，返回两种用途的完整性检查结果。

## 实际文件读取范围

铜层polygon regions及完整circle flashes按dark/clear实际顺序保存；板框为闭合直线轮廓，支持一个板体及互不相交的内部cutout；Drill为圆孔。未支持弧region、非圆aperture/macro、槽孔、多板体及嵌套cutout明确拒绝。孔不得重复出现在同一作业同一坐标，或伸出板框/进入cutout；显式Drill金属化注释与叠层冲突时拒绝。不同作业仍保留各自层对，不按孔径合并。

计划包含逐层材料、实际CAM操作、板框、孔位/直径/层对/Z范围、输入文件SHA256、来源及无CAD/无求解状态。文件和叠层在读取过程中变化会拒绝，不输出看似有效的计划。当前计划不验证铜层间电连接、有限镀层损耗或EM等效。

## 隔离AEDT结构执行

已有建模授权且规划/输入检查完成后：

```powershell
python -m optimizer.fabrication.cam_rebuild <package-dir> --temp-root <temp-dir> --runs-root <runs-dir> --aedt-version <version>
```

默认打开全新拥有的non-GUI COM会话，只有需要用户视觉确认时显式加`--gui`；实际会话模式必须与请求一致。不打开原始AEDT。工作工程放在唯一temp子目录，保存重开并核验后字节副本进入唯一runs子目录；已有输出不覆盖，退出只关闭拥有的会话。明确关闭自动开放区域，不创建端口、求解设置或运行求解。

逐层按其材料创建实体；铜/介质均按Drill实际钻空，金属化孔采用明确的零厚度理想PEC孔壁，NPTH不创建金属壁。盲/埋孔只处理指定层对范围内的层，不让伸出的布尔工具切到其他层。每层铜按来源着色，介质浅青、孔壁蓝，透明度0.7。核验原生体积、实际圆孔边、Z、材料Dk/Df、孔壁范围与PerfectE、显示以及保存重开前后观测；CAM输入哈希始终核对。

当前原生执行范围比CAM规划更窄：重叠dark铜操作、互相接触/重叠的钻孔、部分铜/圆孔交叠、空铜层和板框之外的铜在启动CAD前拒绝。不同叠层/材料可保留，复杂拓扑不做隐式简化。原生圆形保持精确；比较参照使用4096边圆近似，体积核验相对4e-7/绝对1e-7mm³，孔边/Z为1e-8mm。保存重开比较复用已有CAD数值容差，不要求浮点逐位相同。

返回0及completed_geometry只代表本结构/材料链路通过；缺项返回2/needs_input，错误返回1/failed。失败案例及清理异常在manifest中保留，不能报告为完整EM模型或可直接仿真。支持更多CAM特征及版本矩阵仍需分别验收。

## 原生对象提取与实际CAM导出

```powershell
python -m optimizer.fabrication.native_export <source.aedt> --design <design-name> --mapping <role-map.json> --temp-root <temp-dir> --runs-root <runs-dir> --aedt-version <version>
```

默认non-GUI；仅用户需要视觉确认时加`--gui`。拥有的新COM会话只打开源文件的唯一temp字节副本，不保存工程、不写模型、不求解。来源/副本/映射文件全程核对SHA256；退出关闭拥有会话。省略`--mapping`时仅生成对象清单、可读取的包围盒/材料/Model状态及needs_input报告，不输出加工包。无法读取普通属性的边界管理对象仍列在清单中，保留具体读取错误。

映射使用`schema_version="hfss-native-pcb-map-1"`，字段如下。这里保存的是当前任务的加工意图，源码和skill不按对象名称猜角色。

- `coordinate_datum`：原生全局坐标基准说明；不自动平移。
- `layers`：各层`name`、`kind`、`objects`名称列表；铜层`thickness_basis="modeled"`表示按实体Z跨度读取厚度。`fabrication_material`可显式将铜层原生材料映射为copper或pec；不同原生材料合并到一层必须明确映射。否则保留实际材料及已知电导率。
- `profile_layer`：提供物理板框的介质层名。当前要求每个介质层为一个实体且板框相同；保存真实内部开口，不用包围盒替代。
- `drill_operations`：各作业`id`、`start_layer`、`end_layer`、`objects`；可选布尔`metallized`覆盖默认。只有已分类的铜/PEC圆柱才默认金属化，真空/其他材料须明确标注；不将任意金属实体转换为孔。
- `excluded_objects`：对象名称到排除原因的映射。全部原生对象必须恰好归属一层、一次钻孔作业或排除项；遗漏返回needs_input，重复/不存在对象/未知字段/非法层对拒绝。

真实尺寸来自最终原生面边：同时检查上/下截面、面面积、体积及侧面积，支持Z方向等截面Model实体、闭合直线环、整圆边；按包含深度处理clear窗口与dark岛。独立铜实体不允许材料体积重叠，组合后再次验证原生区域并集。钻孔必须是完整圆柱实体，实际直径来自圆边而非公共假定值或包围盒；其加工Z跨度按显式铜层对记录，仿真圆柱的原始跨度也保留。孔不得超出板框、进入物理开口或在同作业同位置重复。

当前不支持零厚度sheet层、锥形/台阶/非等截面体、部分圆弧/样条、圆形板框或介质内圆孔的自动Drill归属。未支持拓扑直接拒绝，不使用凸包、直线弦或默认厚度代替。材料常数读取原生scalar；未知表达式/张量/频散值保持null，不把未知损耗写成0。加工包可以明确保留未知Dk/Df，manifest和叠层说明列出重建缺项；这不代表材料忠实重建已就绪。

成功输出在唯一runs目录：`package/gerber`、`package/drill`、`stackup.json`、`docs/stackup.md`、`docs/fab_notes.md`，以及包外的提取/排除/输入哈希记录与`cam_readback.png`。文件名采用安全层索引，Drill文件同时编码层对索引、作业索引及PTH/NPTH，stackup明确索引到实际层名的关系。实际Gerber/GKO/Drill由现有解析器独立回读，铜区域、板框边界、孔数量/孔心/孔径与提取结果比较；预览仅使用实际解析的CAM。坐标核验1e-6mm，原生读取1e-8mm；圆形比较采用4096边参照，原生圆保持精确。

返回0及`verified_cam_export`表示此支持范围内文件与读回核验通过；2/needs_input表示需要当前任务的角色/材料/层对等缺项，1/failed表示非法输入、不支持或执行/清理失败。失败/部分目录不是可交付加工包；必须检查manifest状态。该入口不提供外部CAM全特征或电磁等效承诺。
