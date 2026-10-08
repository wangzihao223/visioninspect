"""Frozen application entry and optional unattended packaging check."""

import sys


def smoke_test(destination):
    import json
    import shutil
    from pathlib import Path
    from tempfile import TemporaryDirectory
    from unittest.mock import patch

    import numpy as np
    from PIL import Image
    from imgui_bundle import hello_imgui, immapp
    from imgui_app import VisionInspectApp, load_chinese_font
    from storage.config_manager import ConfigManager
    from storage.excel_export import ExcelExporter
    from utils.common import ReviewType

    output = Path(destination).resolve()
    output.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory() as temporary, patch.object(ConfigManager, "set"):
        root = Path(temporary) / "examples"
        shutil.copytree(Path(sys._MEIPASS) / "examples", root)
        app = VisionInspectApp()
        app.project_path = str(root)
        app.open_project()
        assert app.project.get_total_images() == 5
        runner = hello_imgui.RunnerParams()
        runner.app_window_params.hidden = True
        runner.app_window_params.window_geometry.size = (1440, 900)
        runner.imgui_window_params.default_imgui_window_type = hello_imgui.DefaultImGuiWindowType.no_default_window
        runner.ini_disable = True
        runner.fps_idling.enable_idling = False
        runner.callbacks.load_additional_fonts = load_chinese_font
        runner.callbacks.before_exit = app.cleanup
        frame = 0

        def draw():
            nonlocal frame
            app.draw()
            assert not app.error, app.error
            frame += 1
            if frame == 6:
                assert app._texture is not None
                original = Path(app.image.json_path).read_bytes()
                count = len(app.image.annotations)
                app._add_box([40, 40, 100, 100])
                assert len(app.image.annotations) == count + 1
                app.review(app.selected_annotation, ReviewType.CORRECT)
                app._undo()
                app._undo()
                assert Path(app.image.json_path).read_bytes() == original
                report = ExcelExporter.export_report(app.project, str(output))
                assert Path(report).is_file()
            if frame == 12:
                runner.app_shall_exit = True

        runner.callbacks.show_gui = draw
        immapp.run(runner)
        Image.fromarray(np.asarray(hello_imgui.final_app_window_screenshot())).save(output / "screenshot.png")
        (output / "result.json").write_text(json.dumps({"passed": True, "frames": frame, "checks": ["frozen startup", "Chinese font", "image and thumbnails", "add box", "review", "undo JSON", "Excel export"]}), encoding="utf-8")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--smoke-test":
        smoke_test(sys.argv[2])
    else:
        from main import main

        raise SystemExit(main())
