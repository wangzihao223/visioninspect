"""VisionInspect Dear ImGui 应用入口。"""

import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

def main():
    try:
        from imgui_app import run
    except ModuleNotFoundError as exc:
        print(f"缺少依赖 {exc.name}，请使用项目虚拟环境，或运行：\n"
              f'"{sys.executable}" -m pip install -r "{BASE_DIR}/requirements.txt"', file=sys.stderr)
        raise SystemExit(1) from exc
    run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
