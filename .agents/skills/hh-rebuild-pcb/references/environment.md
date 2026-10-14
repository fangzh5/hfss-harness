# 环境依赖

准备从 Gerber、Drill 或 PCB 加工数据反向重建 HFSS/AEDT 校验模型时使用本文件。

## 必需

- 能运行仓库脚本的 Python 环境。
- 几何/解析脚本需要的仓库依赖。
- 加工输入：Gerber 铜层、Excellon Drill、板框和叠层说明。
- 需要通过 PyAEDT 创建或对比 `.aedt` 时，必须有可用授权的 Ansys Electronics Desktop / HFSS。

## 推荐

- AEDT 自带 Python，或与当前 AEDT 版本兼容的 Python。
- 与仓库脚本匹配的 `pyaedt` / `ansys-aedt-core`。
- Windows 上连接已打开 AEDT COM 会话时需要 `pythonnet`。
- KiCad Gerber Viewer 或其他可信 CAM Viewer，用于反向建模前检查源 Gerber。

## 可选

- KiCad PCB Editor，用于查看生成的 PCB review source。
- Altium Designer，用于用户已有 AD 流程时的 CAM 检查。
- 结构对比脚本，用于从原始和反向 HFSS 模型中抽取对象摘要。

## 设置注意

- 不要把 Altium 作为硬依赖；源 CAM 检查通常用 Gerber Viewer 就够。
- 不要假设 AEDT 非图形启动一定可用；某些机器上 PyAEDT gRPC 非图形模式不稳定。
- 如果 PyAEDT 无法连接可见 AEDT 会话，检查 `pythonnet` 和 COM 支持。
- 如果用户在打开的 AEDT 中手工修改了模型，要么连接该会话读取，要么让用户保存后再读取 `.aedt` 文件。

## 验证命令

修改脚本后运行相关测试：

```powershell
python -m pytest tests\test_rebuild_hfss_from_fabrication.py -p no:cacheprovider --basetemp .pytest_tmp
```

如果生成真实模型，检查：

- `.aedt` 文件存在且不是空工程。
- AEDT 打开工程时没有重复实例警告。
- 用于 S 参数对比时，铜对象有非零厚度。
- 介质材料属性包含用户确认的 `Dk` 和 `tanD`。
