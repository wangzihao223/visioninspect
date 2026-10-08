# 桌面审核版打包

使用 PyInstaller 将 Python、ImGui 原生库和审核程序一起打包，用户无需安装 Python。支持 Windows、Linux 和 macOS 文件夹版，不包含 Torch、Ultralytics 或模型权重；模型推理不在本次发行包范围内。

## 构建

在已安装项目审核依赖的虚拟环境中，从项目根目录执行：

```powershell
.\.venv\Scripts\python.exe -m pip install pyinstaller
.\.venv\Scripts\python.exe desktop/build.py
```

输出：

- `desktop/dist/VisionInspect/`：程序目录，包含当前平台可执行文件。
- `desktop/dist/VisionInspect/_internal/`：程序运行依赖，必须与 EXE 一起分发。
- `desktop/dist/VisionInspect-<platform>-review.zip`：完整分发压缩包。
- `desktop/dist/sizes.json`：本次构建的实际字节数。

此次使用 Python 3.12、imgui-bundle 1.92.900、PyInstaller；实际体积见构建生成的 `sizes.json`。包含内置示例，不包含本机项目路径、配置和模型。程序使用系统中文字体。

打包版配置、日志和布局保存在平台用户数据目录，不需要对安装目录有写权限。标注仍写入用户打开的图片同名 JSON。

右键修改类别默认使用当前项目标注中出现的类别，不再使用全局预设。通过“工具 → 项目类别设置”编辑可选列表，每行一个类别，首项用于新画框；保存到数据项目根目录 `.visioninspect-classes.json`，不同项目独立，已有标注不变。

## 验证

```sh
desktop/dist/VisionInspect/VisionInspect --smoke-test desktop/smoke-output
```

Windows 使用 `VisionInspect.exe` 替换上面的可执行文件名。验证以隐藏窗口运行，操作临时示例副本，检查图片与缩略图、画框、审核、撤销 JSON 和 Excel 导出；结果、截图、报告输出到指定目录。
