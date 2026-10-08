# VisionInspect ImGui 版

默认使用 Dear ImGui，按原版 PySide6 的布局和浅色样式呈现，不需要安装或加载 PySide6。

在项目根目录执行：

```powershell
.\.venv\Scripts\python.exe -m pip install -r VisionInspect\requirements.txt
.\.venv\Scripts\python.exe VisionInspect\main.py
```

界面包含顶部菜单、左侧搜索和零件树、中央图片与检测框、右侧标注/缺陷实例表格页签、底部真实缩略图和状态栏。拖动分隔条可以调整面板大小。

右侧“标注结果”的“系统识别结果”列显示模型原始识别类别（包括正常类别），与审核结论分开。人工新增的框显示“—”；修改类别后，原始识别结果仍会保存在 JSON 的 `model_label` 字段中。旧 JSON 未记录该字段时，以未修改的模型标注类别作为兼容值。

使用 `Ctrl+O` 打开应用内目录浏览器，选择项目目录；可逐级浏览或直接输入路径，Windows、macOS 和 Linux 均无需额外安装系统文件选择器。点击检测框或结果表格选中标注，通过右键菜单、审核按钮或 `1`～`5` / `0` 保存审核结果。滚轮缩放，中键或空格加左键平移，`Ctrl+0` 适应图片。

左键拖动可新增人工漏报框，支持直接在已有框内部画框；单击仍然选框，`Esc` 取消绘制。`Ctrl+Z` 或“编辑 → 撤销”恢复上一步标注操作及已保存的 JSON。保留当前项目会话最近 50 次成功操作；重新打开项目或完成模型识别后清空历史。

模型识别通过“工具 → 模型识别”打开，后台加载模型并执行推理。相关依赖见 `VisionInspect/requirements-ml.txt`。更多说明和目前移植范围见根目录 `README.md`。
