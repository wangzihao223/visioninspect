# VisionInspect 模型评估

使用 Dear ImGui 实现原版 PySide6 的浅色桌面样式：左侧搜索和零件树、中央图片与检测框、右侧结果表格页签、底部真实缩略图、单行状态栏。左右分栏和缩略图高度可以拖动调整，退出时保存布局。

## 启动

桌面发行包：运行 `python desktop/build.py`，产物为 `desktop/dist/VisionInspect-<platform>-review.zip`。本次审核版不含模型推理依赖，构建与体积说明见 [desktop/README.md](desktop/README.md)。

推送 `v*` 标签会由 GitHub Actions 在 Linux、Windows 和 macOS runner 上构建桌面发行包并创建 GitHub Release；手动运行 workflow 只上传构建 artifacts。

在项目根目录执行：

```powershell
.\.venv\Scripts\python.exe -m pip install -r VisionInspect\requirements.txt
.\.venv\Scripts\python.exe VisionInspect\main.py
```

没有虚拟环境时，先执行 `python -m venv .venv`。

使用“文件 → 打开数据目录”选择数据根目录，也可以选择 `VisionInspect/examples` 查看内置示例。审核会写回图片同名 JSON。

快捷键：`Ctrl+O` 打开目录，`Ctrl+M` 模型识别，`Ctrl+E` 导出，`A` / `D` 切图，`E` 定位下一个框，`F` 跳转未审核图片，`1`～`5` / `0` 审核，`Del` 删除，`Ctrl+A` 全选，`Ctrl+0` 适应图片。滚轮缩放，中键或空格加左键平移。结果表格支持 Ctrl 多选、Shift 连选。

YOLO 推理为可选功能；需要时在兼容的 Python 环境中安装 `VisionInspect/requirements-ml.txt`。模型选择与推理位于“工具”菜单，报表导出位于“文件”菜单。已有 JSON 的图片会跳过。

界面样式参考 `E:\better-ai-scripts\模型评估系统\VisionInspect\ui`。`VisionInspect/main.py` 默认启动 ImGui，不加载 PySide6；本项目 `ui` 目录保留原版 Qt 源码作参考。

ImGui 中的审核操作会保存到图片同名 JSON：

- 左键单击选框、拖动新增人工“漏报”标注，已有框内部也能直接画框，无需勾选“画框”；重叠处优先选中最小框，Esc 取消绘制。
- `Ctrl+Z` 或“编辑 → 撤销”恢复上一步标注操作及 JSON 文件，支持画框、审核、改类别、删除、缺陷关联和清空审核。跨图片操作一起撤销，切图后仍可撤销；保留最近 50 次成功操作，重新打开项目或完成模型识别后清空历史。
- 检测框或结果表格右键：单条/批量审核、修改类别、自定义类别、删除、缺陷绑定和解绑。
- 类别按项目独立：未配置时从当前项目已有标注提取；通过“工具 → 项目类别设置”或右键“修改类别 → 项目类别设置”编辑，每行一个，首项作为新画框的默认类别。保存到项目根目录 `.visioninspect-classes.json`，不会修改已有标注，也不会影响其他项目。自定义类别仍可用于单次修改；如需固定出现在菜单中，请加入项目类别列表。
- 缺陷实例页签：新建或绑定已有实例、删除实例并保存同一零件所有相关图片，跨相机关联用于零件级去重。
- 图片树与缩略图右键：标记无识别目标、清空审核。删除和清空操作先确认；清空审核会删除该图 JSON。
- 工具菜单：设置审核人员；模型识别可选择强制覆盖已有 JSON。
- 统计窗口：图片级分类统计、零件级去重统计和 Precision / Recall / F1；Excel 导出可选择输出目录。

保存采用临时文件替换，失败项保留原文件和内存数据。跨图片操作若部分文件保存失败，会列出失败路径；已成功保存的图片保持已提交状态，可修复权限后重试。
