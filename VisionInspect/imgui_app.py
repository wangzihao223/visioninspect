"""Dear ImGui frontend using the original desktop layout."""

from __future__ import annotations

import os
import sys
import threading
from collections import OrderedDict
from copy import deepcopy
from pathlib import Path
from queue import Empty, SimpleQueue

import numpy as np
from PIL import Image
from imgui_bundle import hello_imgui, imgui, immapp

if sys.platform != "emscripten":
    from imgui_bundle import immvision, portable_file_dialogs as pfd

    immvision.use_rgb_color_order()

from core.annotation_manager import AnnotationManager
from core.defect_manager import DefectManager
from core.image_manager import ImageManager
from core.project_manager import ProjectManager
from core.project_classes import available_classes, detected_classes, save_project_classes
from core.review_manager import ReviewManager
from core.review_actions import ReviewActions
from core.statistics_manager import StatisticsManager
from models.model_manager import ModelManager
from models.yolo_engine import YOLOEngine
from storage.config_manager import ConfigManager
from storage.excel_export import ExcelExporter
from storage.json_reader import JsonManager
from utils.common import ReviewType
from utils.logger import get_logger
from utils.runtime_paths import data_directory

logger = get_logger(__name__)


class VisionInspectApp:
    def __init__(self):
        self.config = ConfigManager()
        self.project_manager = ProjectManager()
        self.image_manager = ImageManager()
        self.annotation_manager = AnnotationManager()
        self.review_manager = ReviewManager(str(self.config.get("review.default_user", "admin")))
        self.defect_manager = DefectManager()
        self.statistics_manager = StatisticsManager()
        self.model_path = str(self.config.get("paths.last_model", ""))
        saved_project = str(self.config.get("paths.last_project", ""))
        self.project_path = saved_project if os.path.isdir(saved_project) else str(Path(__file__).parent / "examples")
        self.search = ""
        self.selected_annotation = None
        self.actions = None
        self._selected_ids = set()
        self._selection_anchor = None
        self._selected_defect_id = None
        self._pending_focus = None
        self._draw_start = None
        self._drawing_mode = False
        self._canvas_geometry = None
        self._confirmation = None
        self._binding = None
        self._class_editor = None
        self._project_classes_editor = None
        self._tree_expansion = None
        self._reveal_part = None
        self.show_user = False
        self.user_name = self.review_manager.current_user
        self.force_inference = False
        self.status = "就绪 · Ctrl+O 打开数据目录"
        self.error = ""
        self.show_stats = False
        self.show_about = False
        self.show_model = False
        self._style_ready = False
        self._left_width = float(self.config.get("ui.left_width", 240))
        self._right_width = float(self.config.get("ui.right_width", 320))
        self._thumbnail_height = float(self.config.get("ui.thumbnail_height", 146))
        self._texture = None
        self._texture_path = ""
        self._thumbnail_cache = OrderedDict()
        self._zoom = 1.0
        self._pan = (0.0, 0.0)
        self._file_dialog = None
        self._dialog_kind = ""
        self._directory_dialog = None
        self._inference_running = False
        self._inference_thread = None
        self._events = SimpleQueue()
        self._progress = 0.0

    @property
    def project(self):
        return self.project_manager.current_project

    @property
    def image(self):
        return self.image_manager.current_image

    @staticmethod
    def _review_color(status):
        colors = {
            "unreviewed": (0.48, 0.48, 0.48, 1), "unreview": (0.48, 0.48, 0.48, 1),
            "partial": (0.72, 0.49, 0.02, 1), "finished": (0.08, 0.55, 0.18, 1),
            "correct": (0.08, 0.55, 0.18, 1), "has_defect": (0.86, 0.15, 0.15, 1),
            "miss": (0.72, 0.49, 0.02, 1), "wrong_class": (0.05, 0.35, 0.80, 1),
            "false_positive": (0.86, 0.15, 0.15, 1), "overkill": (0.61, 0.12, 0.75, 1),
        }
        return imgui.ImVec4(*colors.get(status, (0.25, 0.25, 0.25, 1)))

    def _bind_project(self, project):
        self.project_manager.current_project = project
        self.image_manager.set_project(project)
        self.defect_manager.set_project(project)
        self.defect_manager.select_defect(None)
        self.statistics_manager.set_project(project)
        self.actions = ReviewActions(project, self.review_manager)
        self.selected_annotation = None
        self._selected_ids.clear()
        self._selection_anchor = None
        self._selected_defect_id = None
        self._binding = None
        self._class_editor = None
        self._project_classes_editor = None
        self.annotation_manager.set_image(self.image)
        self.review_manager.current_image = self.image
        self._texture = None
        self._texture_path = ""
        self._thumbnail_cache.clear()
        self.reset_view()

    def open_project(self):
        if self._inference_running:
            return
        try:
            project = self.project_manager.open_project(self.project_path.strip().strip('"'))
            self._bind_project(project)
            self.project_path = project.root_path
            self.config.set("paths.last_project", self.project_path)
            self.status = f"已打开：{project.project_name} · {project.get_total_images()} 张图片"
            self.error = ""
        except Exception as exc:
            logger.exception("打开项目失败")
            self.error = str(exc)

    def select_image(self, part_id, image_id):
        image = self.image_manager.load_image(part_id, image_id)
        if image:
            self.annotation_manager.set_image(image)
            self.review_manager.current_image = image
            self.selected_annotation = None
            self._selected_ids.clear()
            self._selection_anchor = None
            self._selected_defect_id = None
            self._reveal_part = part_id
            self.reset_view()

    def reset_view(self):
        self._zoom = 1.0
        self._pan = (0.0, 0.0)
        self._draw_start = None
        self._pending_focus = None

    def _move_image(self, delta):
        image = self.image_manager.next_image() if delta > 0 else self.image_manager.previous_image()
        if image:
            self.select_image(image.part_id, image.image_id)

    def _next_unreviewed(self):
        image = self.image_manager.next_unreview_image()
        if image:
            self.select_image(image.part_id, image.image_id)
        else:
            self.status = "所有图片均已审核完成"

    def review(self, annotation, review_type):
        if not self.image or annotation not in self.image.annotations or self._inference_running:
            return
        self._apply_action(lambda: self.actions.review(self.image, [annotation.id], review_type), f"已保存：{review_type.display_name}")

    def _apply_action(self, operation, message):
        if not self.actions or self._inference_running:
            return False
        selected_id = self.selected_annotation.id if self.selected_annotation else None
        try:
            operation()
            self.status = message
            self.error = ""
            return True
        except Exception as exc:
            logger.exception("审核操作失败")
            self.error = str(exc)
            return False
        finally:
            self.annotation_manager.set_image(self.image)
            self.review_manager.current_image = self.image
            available = {annotation.id for annotation in self.image.annotations} if self.image else set()
            self._selected_ids.intersection_update(available)
            self.selected_annotation = self.image.get_annotation(selected_id) if self.image else None
            if self.selected_annotation is None and self._selected_ids:
                self.selected_annotation = self.image.get_annotation(next(iter(self._selected_ids)))
            self.annotation_manager.select_box(self.selected_annotation)
            part = self.project.get_current_part()
            defect = part.get_defect(self._selected_defect_id) if part else None
            self.defect_manager.select_defect(defect)
            if not defect:
                self._selected_defect_id = None

    def _undo(self):
        if not self.actions or not self.actions.can_undo or self._inference_running:
            return
        self._draw_start = None
        label = self.actions.undo_label
        restored = []
        if self._apply_action(lambda: restored.append(self.actions.undo()), f"已撤销：{label}"):
            image = restored[0]
            if image is not self.image:
                self.select_image(image.part_id, image.image_id)

    def _selected_annotations(self):
        return [annotation for annotation in self.image.annotations if annotation.id in self._selected_ids] if self.image else []

    def _select_annotation(self, annotation, additive=False, extend=False, focus=False):
        if annotation is None:
            self._selected_ids.clear()
            self.selected_annotation = None
            self.annotation_manager.select_box(None)
            return
        if extend and self._selection_anchor:
            ids = [item.id for item in self.image.annotations]
            if self._selection_anchor in ids:
                start, end = sorted((ids.index(self._selection_anchor), ids.index(annotation.id)))
                self._selected_ids = set(ids[start:end + 1])
            else:
                self._selected_ids = {annotation.id}
                self._selection_anchor = annotation.id
        elif additive:
            if annotation.id in self._selected_ids:
                self._selected_ids.remove(annotation.id)
            else:
                self._selected_ids.add(annotation.id)
            self._selection_anchor = annotation.id
        else:
            self._selected_ids = {annotation.id}
            self._selection_anchor = annotation.id
        self.selected_annotation = annotation if annotation.id in self._selected_ids else next(iter(self._selected_annotations()), None)
        self.annotation_manager.select_box(self.selected_annotation)
        if focus:
            self._pending_focus = annotation.id

    def _review_selected(self, review_type):
        ids = [annotation.id for annotation in self._selected_annotations()]
        if ids:
            self._apply_action(lambda: self.actions.review(self.image, ids, review_type), f"已保存 {len(ids)} 个检测框：{review_type.display_name}")

    def _change_selected_class(self, class_name):
        ids = [annotation.id for annotation in self._selected_annotations()]
        if ids:
            self._apply_action(lambda: self.actions.change_class(self.image, ids, class_name), f"已修改 {len(ids)} 个检测框类别：{class_name}")

    def _delete_selected(self):
        image = self.image
        ids = [annotation.id for annotation in self._selected_annotations()]
        if ids:
            self._confirmation = (f"删除选中的 {len(ids)} 个检测框？关联关系也会更新。", lambda: self._apply_action(lambda: self.actions.delete_annotations(image, ids), "已删除检测框"))

    def _focus_next(self):
        if self.image and self.image.annotations:
            annotations = self.image.annotations
            index = annotations.index(self.selected_annotation) + 1 if self.selected_annotation in annotations else 0
            self._select_annotation(annotations[index % len(annotations)], focus=True)

    def _request_binding(self):
        annotations = self._selected_annotations()
        if annotations:
            self._binding = {"image": self.image, "ids": [annotation.id for annotation in annotations], "class_name": annotations[0].review_class or annotations[0].class_name, "description": "", "defect_id": ""}

    def _request_delete_defect(self, defect):
        part_id, defect_id = defect.part_id, defect.defect_id
        self._confirmation = (f"删除缺陷 #{defect.index} {defect.class_name}？该零件所有图片中的关联框将解绑，检测框保留。", lambda: self._apply_action(lambda: self.actions.delete_defect(part_id, defect_id), "已删除缺陷实例并保存关联图片"))

    def _add_box(self, bbox):
        classes = available_classes(self.project)
        class_name = classes[0] if classes else "缺陷"
        created = []
        def operation():
            created.append(self.actions.add_box(self.image, bbox, class_name))
        if self._apply_action(operation, f"已新增人工框（漏报）：{class_name}"):
            self._select_annotation(self.image.get_annotation(created[0]))

    def _choose_path(self, kind):
        if self._file_dialog is not None or self._directory_dialog is not None:
            return
        if kind in ("project", "export"):
            start = Path(self.project_path).expanduser()
            if not start.is_dir():
                start = Path.home()
            self._directory_dialog = {"kind": kind, "path": str(start), "entries": None, "error": ""}
        else:
            self._dialog_kind = kind
            self._file_dialog = pfd.open_file("选择 YOLO 模型", self.model_path, ["YOLO 模型", "*.pt"])

    def _draw_directory_dialog(self):
        dialog = self._directory_dialog
        if dialog is None:
            return
        imgui.open_popup("选择目录")
        imgui.set_next_window_size((620, 480), imgui.Cond_.appearing)
        if not imgui.begin_popup_modal("选择目录")[0]:
            return
        imgui.text("数据根目录" if dialog["kind"] == "project" else "报告输出目录")
        imgui.set_next_item_width(-1)
        changed, path = imgui.input_text("##directory_path", dialog["path"])
        if changed:
            dialog["path"] = path
            dialog["entries"] = None
        directory = Path(dialog["path"]).expanduser()
        if imgui.button("上一级"):
            dialog["path"] = str(directory.parent)
            dialog["entries"] = None
        imgui.same_line()
        if imgui.button("主目录"):
            dialog["path"] = str(Path.home())
            dialog["entries"] = None
        directory = Path(dialog["path"]).expanduser()
        if dialog["entries"] is None:
            if not dialog["path"].strip():
                dialog["entries"] = []
                dialog["error"] = "请输入目录路径"
            else:
                try:
                    with os.scandir(directory) as items:
                        dialog["entries"] = sorted((item.name for item in items if item.is_dir()), key=str.casefold)
                    dialog["error"] = ""
                except OSError as exc:
                    dialog["entries"] = []
                    dialog["error"] = str(exc)
        if dialog["error"]:
            imgui.text_wrapped(dialog["error"])
        imgui.begin_child("directory_entries", (0, -40), imgui.ChildFlags_.borders)
        for name in dialog["entries"]:
            if imgui.selectable(name, False)[0]:
                dialog["path"] = str(directory / name)
                dialog["entries"] = None
                break
        imgui.end_child()
        imgui.begin_disabled(not dialog["path"].strip() or not directory.is_dir())
        if imgui.button("选择此目录"):
            kind = dialog["kind"]
            selected = str(directory.resolve())
            self._directory_dialog = None
            imgui.close_current_popup()
            if kind == "project":
                self.project_path = selected
                self.open_project()
            else:
                self._export(selected)
        imgui.end_disabled()
        imgui.same_line()
        if imgui.button("取消"):
            self._directory_dialog = None
            imgui.close_current_popup()
        imgui.end_popup()

    def _edit_project_classes(self):
        if self.project and not self._inference_running:
            self._project_classes_editor = "\n".join(available_classes(self.project))

    def _save_project_classes(self):
        try:
            save_project_classes(self.project, self._project_classes_editor.splitlines())
            self.status = "已保存当前项目的可选类别"
            self.error = ""
            return True
        except (ValueError, OSError) as exc:
            self.error = str(exc)
            return False

    def _poll_events(self):
        if self._file_dialog is not None and self._file_dialog.ready(0):
            result = self._file_dialog.result()
            self._file_dialog = None
            if result:
                if self._dialog_kind == "project":
                    self.project_path = result
                    self.open_project()
                elif self._dialog_kind == "export":
                    self._export(result)
                else:
                    self.model_path = result[0]
        while True:
            try:
                kind, payload = self._events.get_nowait()
            except Empty:
                break
            if kind == "progress":
                current, total, self.status = payload
                self._progress = current / max(1, total)
            elif kind == "done":
                project, result = payload
                for part in project.parts:
                    part.defects = []
                self.project_manager._rebuild_defects(project)
                self._bind_project(project)
                self._inference_running = False
                self.status = f"推理完成：识别 {result['processed']}，跳过 {result['skipped']}，失败 {result['failed']}"
            elif kind == "error":
                self._inference_running = False
                self.error = payload

    def run_inference(self):
        if self._inference_running or not self.project:
            return
        self.model_path = self.model_path.strip().strip('"')
        if not os.path.isfile(self.model_path):
            self.error = f"模型文件不存在：{self.model_path}"
            return
        project = deepcopy(self.project)
        model_path = self.model_path
        confidence = float(self.config.get("inference.confidence_threshold", 0.25))
        iou = float(self.config.get("inference.iou_threshold", 0.45))
        device = str(self.config.get("inference.device", "auto"))
        force = self.force_inference
        self.config.set("paths.last_model", model_path)
        self._inference_running = True
        self._progress = 0.0
        self.error = ""
        self.status = "正在加载模型…"

        def worker():
            try:
                manager = ModelManager()
                info = manager.load_model(model_path)
                engine = YOLOEngine(manager.current_model, info)
                engine.configure(confidence, iou, None if device == "auto" else device)
                result = engine.predict_folder(project, force=force, progress_callback=lambda *values: self._events.put(("progress", values)))
                self._events.put(("done", (project, result)))
            except Exception as exc:
                self._events.put(("error", f"推理失败：{exc}"))

        self._inference_thread = threading.Thread(target=worker, daemon=True)
        self._inference_thread.start()

    def _setup_style(self):
        if self._style_ready:
            return
        imgui.style_colors_light()
        style = imgui.get_style()
        style.window_rounding = 0
        style.child_rounding = 0
        style.frame_rounding = 2
        style.tab_rounding = 2
        style.window_padding = (6, 6)
        style.frame_padding = (6, 4)
        style.item_spacing = (6, 5)
        style.frame_border_size = 1
        style.child_border_size = 1
        for name, color in {
            "window_bg": (0.94, 0.94, 0.94, 1), "child_bg": (1, 1, 1, 1),
            "text": (0.12, 0.12, 0.12, 1), "border": (0.69, 0.69, 0.69, 1),
            "frame_bg": (1, 1, 1, 1), "button": (0.96, 0.96, 0.96, 1),
            "button_hovered": (0.87, 0.93, 0.98, 1), "button_active": (0.72, 0.85, 0.96, 1),
            "header": (0.73, 0.85, 0.95, 1), "header_hovered": (0.85, 0.91, 0.97, 1),
            "header_active": (0.57, 0.76, 0.92, 1), "tab": (0.9, 0.9, 0.9, 1),
            "tab_selected": (1, 1, 1, 1), "table_header_bg": (0.93, 0.93, 0.93, 1),
        }.items():
            style.set_color_(getattr(imgui.Col_, name), imgui.ImVec4(*color))
        self._style_ready = True

    def _handle_shortcuts(self):
        if imgui.get_io().want_text_input or imgui.is_popup_open("", imgui.PopupFlags_.any_popup_id) or self._inference_running:
            return
        if imgui.get_io().key_ctrl:
            if imgui.is_key_pressed(imgui.Key.z, False):
                self._undo()
            elif imgui.is_key_pressed(imgui.Key.o):
                self._choose_path("project")
            elif imgui.is_key_pressed(imgui.Key.m):
                self.show_model = True
            elif imgui.is_key_pressed(imgui.Key._0):
                self.reset_view()
            elif imgui.is_key_pressed(imgui.Key.e):
                self._choose_path("export")
            elif imgui.is_key_pressed(imgui.Key.a) and self.image:
                self._selected_ids = {annotation.id for annotation in self.image.annotations}
                self.selected_annotation = next(iter(self.image.annotations), None)
            return
        if imgui.is_key_pressed(imgui.Key.a):
            self._move_image(-1)
        elif imgui.is_key_pressed(imgui.Key.d):
            self._move_image(1)
        elif imgui.is_key_pressed(imgui.Key.f):
            self._next_unreviewed()
        elif imgui.is_key_pressed(imgui.Key.e):
            self._focus_next()
        elif imgui.is_key_pressed(imgui.Key.delete):
            self._delete_selected()
        elif imgui.is_key_pressed(imgui.Key.escape):
            self._draw_start = None
            self._drawing_mode = False
        if self.selected_annotation is not None:
            for key, review_type in zip((imgui.Key._1, imgui.Key._2, imgui.Key._3, imgui.Key._4, imgui.Key._5, imgui.Key._0), ReviewType):
                if imgui.is_key_pressed(key):
                    self._review_selected(review_type)
        if imgui.is_key_pressed(imgui.Key.equal) or imgui.is_key_pressed(imgui.Key.keypad_add):
            self._zoom = min(40, self._zoom * 1.25)
        elif imgui.is_key_pressed(imgui.Key.minus) or imgui.is_key_pressed(imgui.Key.keypad_subtract):
            self._zoom = max(0.1, self._zoom / 1.25)

    def _export(self, output_dir=""):
        if self.project:
            try:
                self.status = "报告已导出：" + ExcelExporter.export_report(self.project, output_dir)
                self.error = ""
            except Exception as exc:
                self.error = f"导出失败：{exc}"

    def _draw_menu(self):
        if imgui.begin_main_menu_bar():
            if imgui.begin_menu("文件"):
                if imgui.menu_item("打开数据目录…", "Ctrl+O", False, not self._inference_running)[0]:
                    self._choose_path("project")
                if imgui.menu_item("导出 Excel 评估报告", "Ctrl+E", False, bool(self.project) and not self._inference_running)[0]:
                    self._choose_path("export")
                imgui.separator()
                if imgui.menu_item("退出", "", False, not self._inference_running)[0]:
                    hello_imgui.get_runner_params().app_shall_exit = True
                imgui.end_menu()
            if imgui.begin_menu("编辑"):
                enabled = bool(self.actions and self.actions.can_undo and not self._inference_running)
                label = f"撤销：{self.actions.undo_label}" if self.actions and self.actions.can_undo else "撤销"
                if imgui.menu_item(label, "Ctrl+Z", False, enabled)[0]:
                    self._undo()
                imgui.end_menu()
            if imgui.begin_menu("工具"):
                if imgui.menu_item("项目类别设置…", "", False, bool(self.project) and not self._inference_running)[0]:
                    self._edit_project_classes()
                if imgui.menu_item("模型识别…", "Ctrl+M", False, not self._inference_running)[0]:
                    self.show_model = True
                if imgui.menu_item("适应图片", "Ctrl+0", False)[0]:
                    self.reset_view()
                if imgui.menu_item("设置审核人员…", "", False)[0]:
                    self.user_name = self.review_manager.current_user
                    self.show_user = True
                if imgui.menu_item("缺陷实例关联…", "", False, bool(self._selected_ids) and not self._inference_running)[0]:
                    self._request_binding()
                imgui.end_menu()
            if imgui.begin_menu("统计分析"):
                if imgui.menu_item("审核统计", "", False, bool(self.project))[0]:
                    self.show_stats = True
                imgui.end_menu()
            if imgui.begin_menu("帮助"):
                if imgui.menu_item("关于 / 快捷键", "", False)[0]:
                    self.show_about = True
                imgui.end_menu()
            imgui.end_main_menu_bar()

    def _splitter(self, name, position, size, horizontal=False):
        imgui.set_cursor_screen_pos(position)
        imgui.invisible_button(name, size)
        if imgui.is_item_hovered() or imgui.is_item_active():
            imgui.set_mouse_cursor(imgui.MouseCursor_.resize_ns if horizontal else imgui.MouseCursor_.resize_ew)
        if imgui.is_item_active():
            delta = imgui.get_io().mouse_delta
            return delta.y if horizontal else delta.x
        return 0.0

    def draw(self):
        self._setup_style()
        self._poll_events()
        self._handle_shortcuts()
        self._draw_menu()
        viewport = imgui.get_main_viewport()
        menu_height = imgui.get_frame_height()
        status_height = imgui.get_frame_height() + (imgui.get_text_line_height_with_spacing() if self.error else 0)
        imgui.set_next_window_pos((viewport.pos.x, viewport.pos.y + menu_height))
        imgui.set_next_window_size((viewport.size.x, max(1, viewport.size.y - menu_height)))
        flags = imgui.WindowFlags_.no_title_bar | imgui.WindowFlags_.no_move | imgui.WindowFlags_.no_resize | imgui.WindowFlags_.no_saved_settings | imgui.WindowFlags_.no_scrollbar
        imgui.begin("##desktop", flags=flags)
        origin = imgui.get_cursor_screen_pos()
        avail = imgui.get_content_region_avail()
        width, height = max(1.0, avail.x), max(1.0, avail.y - status_height - 5)
        left = min(max(130.0, self._left_width), width * 0.28)
        right = min(max(210.0, self._right_width), width * 0.32)
        remaining = max(1.0, width - left - 6)
        center = max(1.0, remaining - right - 6)
        thumbnails = min(max(100.0, self._thumbnail_height), height * 0.35)
        upper = max(1.0, height - thumbnails - 6)
        imgui.begin_disabled(self._inference_running)
        imgui.begin_child("navigation", (left, height), imgui.ChildFlags_.borders)
        self._draw_navigation()
        imgui.end_child()
        delta = self._splitter("left_splitter", (origin.x + left, origin.y), (6, height))
        if delta:
            self._left_width = left + delta
        imgui.set_cursor_screen_pos((origin.x + left + 6, origin.y))
        imgui.begin_child("image_area", (center, upper), imgui.ChildFlags_.borders, imgui.WindowFlags_.no_scrollbar | imgui.WindowFlags_.no_scroll_with_mouse)
        self._draw_image()
        imgui.end_child()
        delta = self._splitter("right_splitter", (origin.x + left + 6 + center, origin.y), (6, upper))
        if delta:
            self._right_width = right - delta
        imgui.set_cursor_screen_pos((origin.x + left + center + 12, origin.y))
        imgui.begin_child("results", (right, upper), imgui.ChildFlags_.borders)
        self._draw_results()
        imgui.end_child()
        delta = self._splitter("thumbnail_splitter", (origin.x + left + 6, origin.y + upper), (remaining, 6), True)
        if delta:
            self._thumbnail_height = thumbnails - delta
        imgui.set_cursor_screen_pos((origin.x + left + 6, origin.y + upper + 6))
        imgui.begin_child("thumbnails", (remaining, thumbnails), imgui.ChildFlags_.borders, imgui.WindowFlags_.horizontal_scrollbar)
        self._draw_thumbnails()
        imgui.end_child()
        imgui.end_disabled()
        imgui.set_cursor_screen_pos((origin.x, origin.y + height + 5))
        self._draw_status()
        imgui.end()
        self._draw_dialogs()

    def _draw_navigation(self):
        imgui.set_next_item_width(-1)
        _, self.search = imgui.input_text_with_hint("##search", "搜索目录或文件名…", self.search)
        imgui.text_disabled("零件号 / 图片")
        imgui.separator()
        if not self.project:
            imgui.text_wrapped("通过“文件 → 打开数据目录”加载项目。")
            if imgui.button("打开数据目录…", (-1, 0)):
                self._choose_path("project")
            return
        keyword = self.search.casefold().strip()
        for part in self.project.parts:
            images = [image for image in part.images if not keyword or keyword in part.part_id.casefold() or keyword in image.file_name.casefold()]
            if not images:
                continue
            if keyword or self._tree_expansion is not None or self._reveal_part == part.part_id:
                imgui.set_next_item_open(bool(keyword) or self._tree_expansion is True or self._reveal_part == part.part_id, imgui.Cond_.always)
            else:
                imgui.set_next_item_open(part.part_id == self.project.current_part_id, imgui.Cond_.once)
            imgui.push_style_color(imgui.Col_.text, self._review_color(part.get_part_status().value))
            expanded = imgui.tree_node(f"{part.part_id}##{part.part_id}")
            imgui.pop_style_color()
            if expanded:
                for image in images:
                    imgui.push_style_color(imgui.Col_.text, self._review_color(image.get_review_status().value))
                    if imgui.selectable(f"{image.file_name}##{image.image_id}", self.image is image)[0]:
                        self.select_image(part.part_id, image.image_id)
                    imgui.pop_style_color()
                    if imgui.begin_popup_context_item(f"image_menu_{image.image_id}"):
                        self._image_review_menu(image)
                        imgui.end_popup()
                imgui.tree_pop()
        self._tree_expansion = None
        self._reveal_part = None
        if imgui.begin_popup_context_window("tree_menu", imgui.PopupFlags_.mouse_button_right | imgui.PopupFlags_.no_open_over_items):
            if imgui.menu_item("全部展开", "", False)[0]:
                self._tree_expansion = True
            if imgui.menu_item("全部折叠", "", False)[0]:
                self._tree_expansion = False
            imgui.end_popup()

    def _image_review_menu(self, image):
        if imgui.menu_item("标记已审核（无识别目标）", "", False, not image.is_ever_reviewed())[0]:
            operation = lambda: self._apply_action(lambda: self.actions.mark_empty(image), f"已标记无识别目标：{image.file_name}")
            if image.annotations:
                self._confirmation = (f"确认 {image.file_name} 无识别目标？将清除该图 {len(image.annotations)} 个检测框。", operation)
            else:
                operation()
        if imgui.menu_item("清空审核…", "", False)[0]:
            self._confirmation = (f"清空 {image.file_name} 的全部检测框和审核记录？将删除该图同名 JSON。", lambda: self._apply_action(lambda: self.actions.clear_image(image), f"已清空审核：{image.file_name}"))

    @staticmethod
    def _load_texture(path, thumbnail=False):
        with Image.open(path) as image:
            if thumbnail:
                image.thumbnail((120, 90))
            pixels = np.array(image.convert("RGB"), dtype=np.uint8, copy=True)
        return immvision.GlTexture(pixels)

    def _draw_image(self):
        imgui.begin_disabled(self.image is None)
        if imgui.button("上一张"):
            self._move_image(-1)
        imgui.same_line()
        if imgui.button("下一张"):
            self._move_image(1)
        imgui.same_line()
        if imgui.button("适应图片"):
            self.reset_view()
        imgui.same_line()
        _, self._drawing_mode = imgui.checkbox("画框", self._drawing_mode)
        if imgui.is_item_hovered():
            imgui.set_tooltip("单击选框，左键拖动新建（支持已有框内部）。勾选后优先画框；Ctrl/Shift 点击多选，Esc 取消。")
        imgui.end_disabled()
        imgui.separator()
        position = imgui.get_cursor_screen_pos()
        avail = imgui.get_content_region_avail()
        size = (max(1, avail.x), max(1, avail.y))
        imgui.invisible_button("canvas", size, imgui.ButtonFlags_.mouse_button_left | imgui.ButtonFlags_.mouse_button_right | imgui.ButtonFlags_.mouse_button_middle)
        hovered = imgui.is_item_hovered()
        active = imgui.is_item_active()
        draw = imgui.get_window_draw_list()
        end = (position.x + size[0], position.y + size[1])
        draw.add_rect_filled(position, end, imgui.get_color_u32((0.91, 0.91, 0.91, 1)))
        if not self.image:
            draw.add_text((position.x + 18, position.y + 24), imgui.get_color_u32((0.4, 0.4, 0.4, 1)), "选择图片开始审核")
            return
        if self._texture_path != self.image.file_path:
            self._texture = None
            self._texture_path = self.image.file_path
            try:
                self._texture = self._load_texture(self.image.file_path)
            except (OSError, ValueError) as exc:
                self.error = f"无法读取图片：{exc}"
        if self._texture is None:
            draw.add_text((position.x + 18, position.y + 24), imgui.get_color_u32((0.8, 0.1, 0.1, 1)), "图片读取失败，请检查文件")
            return
        image_width, image_height = self._texture.image_size
        self.image.width, self.image.height = image_width, image_height
        fit_scale = min(size[0] / image_width, size[1] / image_height)
        io = imgui.get_io()
        center = (position.x + size[0] / 2, position.y + size[1] / 2)
        if self._pending_focus:
            annotation = self.image.get_annotation(self._pending_focus)
            if annotation:
                left, top, right, bottom = annotation.bbox
                focus_scale = min(size[0] / max(right - left + 80, image_width * 0.12), size[1] / max(bottom - top + 80, image_height * 0.12))
                self._zoom = min(40, max(1, focus_scale / fit_scale))
                self._pan = ((image_width / 2 - (left + right) / 2) * fit_scale * self._zoom, (image_height / 2 - (top + bottom) / 2) * fit_scale * self._zoom)
            self._pending_focus = None
        if hovered and io.mouse_wheel:
            new_zoom = min(40.0, max(0.1, self._zoom * 1.2 ** io.mouse_wheel))
            ratio = new_zoom / self._zoom
            self._pan = tuple((mouse - middle) - (mouse - middle - pan) * ratio for mouse, middle, pan in zip((io.mouse_pos.x, io.mouse_pos.y), center, self._pan))
            self._zoom = new_zoom
        if active and (imgui.is_mouse_down(2) or (imgui.is_key_down(imgui.Key.space) and imgui.is_mouse_down(0))):
            self._draw_start = None
            self._pan = (self._pan[0] + io.mouse_delta.x, self._pan[1] + io.mouse_delta.y)
            imgui.set_mouse_cursor(imgui.MouseCursor_.resize_all)
        scale = fit_scale * self._zoom
        start = (center[0] - image_width * scale / 2 + self._pan[0], center[1] - image_height * scale / 2 + self._pan[1])
        self._canvas_geometry = (start, scale, (position.x, position.y), size)
        point = ((io.mouse_pos.x - start[0]) / scale, (io.mouse_pos.y - start[1]) / scale)
        if hovered and (imgui.is_mouse_clicked(0) or imgui.is_mouse_clicked(1)) and not imgui.is_key_down(imgui.Key.space):
            matches = [ann for ann in self.image.annotations if ann.bbox[0] <= point[0] <= ann.bbox[2] and ann.bbox[1] <= point[1] <= ann.bbox[3]]
            annotation = min(matches, key=lambda ann: (ann.bbox[2] - ann.bbox[0]) * (ann.bbox[3] - ann.bbox[1])) if matches else None
            if imgui.is_mouse_clicked(1):
                if annotation is None or annotation.id not in self._selected_ids:
                    self._select_annotation(annotation)
                imgui.open_popup("canvas_review")
            elif not io.key_ctrl and not io.key_shift and 0 <= point[0] <= image_width and 0 <= point[1] <= image_height:
                self._draw_start = point
                self._select_annotation(None if self._drawing_mode else annotation)
            else:
                self._select_annotation(annotation, additive=io.key_ctrl, extend=io.key_shift)
        draw.push_clip_rect(position, end, True)
        draw.add_image(imgui.ImTextureRef(self._texture.texture_id), start, (start[0] + image_width * scale, start[1] + image_height * scale))
        for index, annotation in enumerate(self.image.annotations, 1):
            left, top, right, bottom = annotation.bbox
            first = (start[0] + left * scale, start[1] + top * scale)
            last = (start[0] + right * scale, start[1] + bottom * scale)
            color = imgui.get_color_u32(self._review_color(annotation.review_type.value))
            draw.add_rect(first, last, color, thickness=3 if annotation.id in self._selected_ids else 1.5)
            label = f"{index} {annotation.review_class or annotation.class_name}"
            if annotation.defect_id:
                defect = self.project.get_current_part().get_defect(annotation.defect_id)
                if defect:
                    label += f" [#{defect.index}]"
            text_size = imgui.calc_text_size(label)
            label_top = max(position.y, first[1] - text_size.y - 4)
            draw.add_rect_filled((first[0], label_top), (first[0] + text_size.x + 8, label_top + text_size.y + 4), imgui.get_color_u32((0.22, 0.22, 0.22, 0.9)))
            draw.add_text((first[0] + 4, label_top + 2), imgui.get_color_u32((1, 1, 1, 1)), label)
        if self._draw_start:
            clipped = (max(0, min(image_width, point[0])), max(0, min(image_height, point[1])))
            dragged = ((point[0] - self._draw_start[0]) ** 2 + (point[1] - self._draw_start[1]) ** 2) * scale ** 2 >= io.mouse_drag_threshold ** 2
            first = (start[0] + min(self._draw_start[0], clipped[0]) * scale, start[1] + min(self._draw_start[1], clipped[1]) * scale)
            last = (start[0] + max(self._draw_start[0], clipped[0]) * scale, start[1] + max(self._draw_start[1], clipped[1]) * scale)
            if dragged:
                draw.add_rect(first, last, imgui.get_color_u32((0.1, 0.4, 0.9, 1)), thickness=2)
            if imgui.is_mouse_released(0):
                bbox = [*self._draw_start, *clipped]
                self._draw_start = None
                if dragged and abs(bbox[2] - bbox[0]) >= 5 and abs(bbox[3] - bbox[1]) >= 5:
                    self._add_box(bbox)
        draw.pop_clip_rect()
        if imgui.begin_popup("canvas_review"):
            self._review_menu()
            imgui.end_popup()

    def _review_menu(self):
        annotations = self._selected_annotations()
        if not annotations:
            imgui.text_disabled("左键拖动可新增人工框，已有框内部同样可画")
            return
        prefix = f"批量审核（{len(annotations)}）· " if len(annotations) > 1 else ""
        for index, review_type in enumerate(ReviewType):
            if imgui.menu_item(prefix + review_type.display_name, str((index + 1) % 6), False)[0]:
                self._review_selected(review_type)
        imgui.separator()
        if imgui.begin_menu("批量修改类别" if len(annotations) > 1 else "修改类别"):
            classes = available_classes(self.project)
            if not classes:
                imgui.text_disabled("当前项目暂无类别，请设置或输入自定义类别")
            for class_name in classes:
                if imgui.menu_item(class_name, "", False)[0]:
                    self._change_selected_class(class_name)
            if imgui.menu_item("自定义类别…", "", False)[0]:
                self._class_editor = annotations[0].class_name
            imgui.separator()
            if imgui.menu_item("项目类别设置…", "", False)[0]:
                self._edit_project_classes()
            imgui.end_menu()
        if imgui.menu_item("缺陷实例关联…", "", False)[0]:
            self._request_binding()
        if imgui.menu_item("解除缺陷关联", "", False, any(annotation.defect_id for annotation in annotations))[0]:
            ids = [annotation.id for annotation in annotations]
            self._apply_action(lambda: self.actions.unbind(self.image, ids), "已解除缺陷关联")
        imgui.separator()
        if imgui.menu_item(f"删除（{len(annotations)}）…", "Del", False)[0]:
            self._delete_selected()

    def _draw_results(self):
        if imgui.begin_tab_bar("result_tabs"):
            if imgui.begin_tab_item("标注结果")[0]:
                flags = imgui.TableFlags_.borders | imgui.TableFlags_.row_bg | imgui.TableFlags_.resizable | imgui.TableFlags_.scroll_y
                if imgui.begin_table("annotations", 5, flags | imgui.TableFlags_.scroll_x, (0, max(40, imgui.get_content_region_avail().y - 88))):
                    for heading in ("类别", "系统识别结果", "置信度", "审核", "来源"):
                        imgui.table_setup_column(heading)
                    imgui.table_setup_scroll_freeze(0, 1)
                    imgui.table_headers_row()
                    for index, annotation in enumerate(self.image.annotations if self.image else []):
                        imgui.table_next_row()
                        imgui.table_next_column()
                        imgui.push_id(index)
                        if imgui.selectable(annotation.class_name, annotation.id in self._selected_ids, imgui.SelectableFlags_.span_all_columns)[0]:
                            io = imgui.get_io()
                            self._select_annotation(annotation, additive=io.key_ctrl, extend=io.key_shift, focus=not io.key_ctrl and not io.key_shift)
                        if imgui.begin_popup_context_item("review"):
                            if annotation.id not in self._selected_ids:
                                self._select_annotation(annotation)
                            self._review_menu()
                            imgui.end_popup()
                        imgui.pop_id()
                        imgui.table_next_column()
                        imgui.text(annotation.model_label or "—")
                        imgui.table_next_column()
                        imgui.text(f"{annotation.confidence:.3f}" if annotation.confidence else "—")
                        imgui.table_next_column()
                        imgui.text_colored(self._review_color(annotation.review_type.value), annotation.review_type.display_name)
                        imgui.table_next_column()
                        imgui.text({"model": "模型", "human": "人工", "modify": "修改"}.get(annotation.source.value, annotation.source.value))
                    imgui.end_table()
                imgui.begin_disabled(self.selected_annotation is None)
                button_width = max(1, (imgui.get_content_region_avail().x - 12) / 3)
                for index, review_type in enumerate(ReviewType):
                    key = (index + 1) % 6
                    if imgui.button(f"{key} {review_type.display_name}", (button_width, 0)):
                        self._review_selected(review_type)
                    if index % 3 != 2:
                        imgui.same_line()
                imgui.end_disabled()
                imgui.text_disabled(f"已选 {len(self._selected_ids)} 个 · Ctrl/Shift 多选 · 右键操作")
                imgui.end_tab_item()
            if imgui.begin_tab_item("缺陷实例")[0]:
                part = self.project.get_current_part() if self.project else None
                if imgui.begin_table("defects", 3, imgui.TableFlags_.borders | imgui.TableFlags_.row_bg | imgui.TableFlags_.scroll_y, (0, max(40, imgui.get_content_region_avail().y - 96))):
                    for heading in ("编号", "类别", "关联框"):
                        imgui.table_setup_column(heading)
                    imgui.table_headers_row()
                    for index, defect in enumerate(part.defects if part else [], 1):
                        imgui.table_next_row()
                        imgui.table_next_column()
                        if imgui.selectable(f"{defect.index or index}##{defect.defect_id}", self._selected_defect_id == defect.defect_id, imgui.SelectableFlags_.span_all_columns)[0]:
                            self._selected_defect_id = defect.defect_id
                            self.defect_manager.select_defect(defect)
                            self._selected_ids = {annotation.id for annotation in self.image.annotations if annotation.defect_id == defect.defect_id}
                            self.selected_annotation = next(iter(self._selected_annotations()), None)
                        if imgui.begin_popup_context_item(f"defect_{defect.defect_id}"):
                            if imgui.menu_item("删除缺陷实例…", "", False)[0]:
                                self._request_delete_defect(defect)
                            imgui.end_popup()
                        imgui.table_next_column()
                        imgui.text(defect.class_name)
                        imgui.table_next_column()
                        imgui.text(str(len(defect.annotation_bindings)))
                    imgui.end_table()
                imgui.begin_disabled(not self._selected_ids)
                if imgui.button("新建 / 绑定缺陷实例"):
                    self._request_binding()
                imgui.end_disabled()
                imgui.same_line()
                defect = part.get_defect(self._selected_defect_id) if part else None
                imgui.begin_disabled(defect is None)
                if imgui.button("删除"):
                    self._request_delete_defect(defect)
                imgui.end_disabled()
                if defect:
                    imgui.text_wrapped(f"#{defect.index} {defect.class_name} · {len(defect.annotation_bindings)} 个关联框")
                imgui.end_tab_item()
            imgui.end_tab_bar()

    def _draw_thumbnails(self):
        part = self.project.get_current_part() if self.project else None
        if not part:
            imgui.text_disabled("当前零件的图片缩略图")
            return
        for index, image in enumerate(part.images):
            if index:
                imgui.same_line()
            imgui.push_id(image.image_id)
            position = imgui.get_cursor_screen_pos()
            if imgui.invisible_button("thumbnail", (140, 116)):
                self.select_image(image.part_id, image.image_id)
            visible = imgui.is_item_visible()
            if imgui.begin_popup_context_item("thumbnail_review"):
                self._image_review_menu(image)
                imgui.end_popup()
            if visible:
                if image.file_path not in self._thumbnail_cache:
                    try:
                        self._thumbnail_cache[image.file_path] = self._load_texture(image.file_path, True)
                    except (OSError, ValueError):
                        self._thumbnail_cache[image.file_path] = None
                    while len(self._thumbnail_cache) > 128:
                        self._thumbnail_cache.popitem(last=False)
                self._thumbnail_cache.move_to_end(image.file_path)
                texture = self._thumbnail_cache[image.file_path]
                draw = imgui.get_window_draw_list()
                if image is self.image:
                    draw.add_rect_filled(position, (position.x + 140, position.y + 116), imgui.get_color_u32((0.75, 0.87, 0.96, 1)))
                if texture:
                    width, height = texture.image_size
                    left, top = position.x + (140 - width) / 2, position.y + (92 - height) / 2
                    draw.add_image(imgui.ImTextureRef(texture.texture_id), (left, top), (left + width, top + height))
                color = imgui.get_color_u32(self._review_color(image.get_review_status().value))
                draw.add_rect(position, (position.x + 140, position.y + 116), color)
                draw.push_clip_rect(position, (position.x + 140, position.y + 116), True)
                draw.add_text((position.x + 6, position.y + 96), color, image.file_name)
                draw.pop_clip_rect()
            imgui.pop_id()

    def _draw_status(self):
        if self._inference_running:
            imgui.progress_bar(self._progress, (150, 0), "模型识别中")
            imgui.same_line()
        if self.project:
            stats = self.project.get_statistics()
            imgui.text(f"零件 {self.project.current_part_id or '—'} | 图片 {self.image.file_name if self.image else '—'} | 审核 {stats['reviewed_images']}/{stats['total_images']} ({stats['progress']:.1f}%)")
            imgui.same_line()
        imgui.text_disabled(self.status)
        if self.error:
            imgui.text_colored(self._review_color("false_positive"), self.error)
            if imgui.is_item_hovered():
                imgui.set_tooltip(self.error)

    def _draw_dialogs(self):
        self._draw_action_dialogs()
        self._draw_directory_dialog()
        for title, attribute in (("模型识别", "show_model"), ("统计分析", "show_stats"), ("关于 VisionInspect", "show_about"), ("审核人员", "show_user")):
            if not getattr(self, attribute):
                continue
            imgui.open_popup(title)
            imgui.set_next_window_size((740 if attribute == "show_stats" else 560, 0), imgui.Cond_.appearing)
            if imgui.begin_popup_modal(title, flags=imgui.WindowFlags_.always_auto_resize)[0]:
                if attribute == "show_model":
                    imgui.text("YOLO 模型文件")
                    imgui.set_next_item_width(450)
                    _, self.model_path = imgui.input_text("##model_path", self.model_path)
                    imgui.same_line()
                    if imgui.button("浏览…"):
                        self._choose_path("model")
                    _, self.force_inference = imgui.checkbox("强制重新识别（覆盖已有 JSON 和审核记录）", self.force_inference)
                    imgui.text_wrapped("默认跳过已有 JSON。勾选强制重新识别后，将覆盖检测框、审核记录和缺陷绑定。")
                    imgui.begin_disabled(not self.project or self._inference_running)
                    if imgui.button("开始批量识别"):
                        self.run_inference()
                        if self._inference_running:
                            self.show_model = False
                            imgui.close_current_popup()
                    imgui.end_disabled()
                    if self.error:
                        imgui.text_wrapped(self.error)
                elif attribute == "show_stats":
                    self._draw_statistics()
                    if imgui.button("导出 Excel 报告"):
                        self._choose_path("export")
                elif attribute == "show_user":
                    imgui.set_next_item_width(360)
                    _, self.user_name = imgui.input_text("审核人员", self.user_name)
                    imgui.begin_disabled(not self.user_name.strip())
                    if imgui.button("保存"):
                        self.review_manager.set_user(self.user_name.strip())
                        self.config.set("review.default_user", self.review_manager.current_user)
                        self.show_user = False
                        imgui.close_current_popup()
                    imgui.end_disabled()
                else:
                    imgui.text_wrapped("VisionInspect · Dear ImGui\n\nA / D 切图；E 定位下一个检测框；F 下一张未审核。\n1–5 / 0 审核；Del 删除；Ctrl+A 全选；Ctrl/Shift 多选。\n单击选框，左键拖动新增人工框（已有框内部也可画）；Esc 取消。\nCtrl+Z 或编辑 → 撤销：恢复上一步操作及 JSON，最多 50 步。\n右键审核、改类别、缺陷绑定。\n滚轮缩放；中键或空格+左键拖动；Ctrl+0 适应图片。\nCtrl+O 打开目录；Ctrl+M 模型识别；Ctrl+E 导出。")
                if imgui.button("关闭"):
                    setattr(self, attribute, False)
                    imgui.close_current_popup()
                imgui.end_popup()

    def _draw_action_dialogs(self):
        if self._project_classes_editor is not None:
            imgui.open_popup("项目类别设置")
            imgui.set_next_window_size((520, 0), imgui.Cond_.appearing)
            if imgui.begin_popup_modal("项目类别设置", flags=imgui.WindowFlags_.always_auto_resize)[0]:
                imgui.text(f"当前项目：{self.project.project_name}")
                imgui.text_wrapped("每行一个类别，可增加、删除或调整顺序。第一项用于新画框；设置仅影响此项目，不修改已有标注。")
                _, self._project_classes_editor = imgui.input_text_multiline("##project_classes", self._project_classes_editor, (480, 210))
                if imgui.button("填入项目已有类别"):
                    self._project_classes_editor = "\n".join(detected_classes(self.project))
                imgui.begin_disabled(not self._project_classes_editor.strip())
                if imgui.button("保存类别") and self._save_project_classes():
                    self._project_classes_editor = None
                    imgui.close_current_popup()
                imgui.end_disabled()
                imgui.same_line()
                if imgui.button("取消"):
                    self._project_classes_editor = None
                    imgui.close_current_popup()
                if self.error:
                    imgui.text_wrapped(self.error)
                imgui.end_popup()
        if self._confirmation is not None:
            imgui.open_popup("确认操作")
            imgui.set_next_window_size((520, 0), imgui.Cond_.appearing)
            if imgui.begin_popup_modal("确认操作", flags=imgui.WindowFlags_.always_auto_resize)[0]:
                message, operation = self._confirmation
                imgui.text_wrapped(message)
                if imgui.button("确认") and operation():
                    self._confirmation = None
                    imgui.close_current_popup()
                imgui.same_line()
                if imgui.button("取消"):
                    self._confirmation = None
                    imgui.close_current_popup()
                if self.error:
                    imgui.text_wrapped(self.error)
                imgui.end_popup()
        if self._class_editor is not None:
            imgui.open_popup("修改类别")
            if imgui.begin_popup_modal("修改类别", flags=imgui.WindowFlags_.always_auto_resize)[0]:
                _, self._class_editor = imgui.input_text("类别名称", self._class_editor)
                imgui.begin_disabled(not self._class_editor.strip())
                if imgui.button("保存"):
                    ids = list(self._selected_ids)
                    if self._apply_action(lambda: self.actions.change_class(self.image, ids, self._class_editor), "已修改类别"):
                        self._class_editor = None
                        imgui.close_current_popup()
                imgui.end_disabled()
                imgui.same_line()
                if imgui.button("取消"):
                    self._class_editor = None
                    imgui.close_current_popup()
                if self.error:
                    imgui.text_wrapped(self.error)
                imgui.end_popup()
        if self._binding is not None:
            imgui.open_popup("缺陷实例关联")
            imgui.set_next_window_size((560, 0), imgui.Cond_.appearing)
            if imgui.begin_popup_modal("缺陷实例关联", flags=imgui.WindowFlags_.always_auto_resize)[0]:
                binding = self._binding
                image = binding["image"]
                part = self.project.get_part(image.part_id)
                imgui.text(f"零件：{part.part_id} · 已选 {len(binding['ids'])} 个检测框")
                selected = part.get_defect(binding["defect_id"])
                label = f"#{selected.index} {selected.class_name}" if selected else "新建缺陷实例"
                if imgui.begin_combo("关联到", label):
                    if imgui.selectable("新建缺陷实例", not binding["defect_id"])[0]:
                        binding["defect_id"] = ""
                    for defect in part.defects:
                        if imgui.selectable(f"#{defect.index} {defect.class_name}##{defect.defect_id}", defect.defect_id == binding["defect_id"])[0]:
                            binding["defect_id"] = defect.defect_id
                    imgui.end_combo()
                if not binding["defect_id"]:
                    _, binding["class_name"] = imgui.input_text("缺陷类别", binding["class_name"])
                    _, binding["description"] = imgui.input_text("备注", binding["description"])
                imgui.text_wrapped("同一零件不同图片中的相同缺陷可绑定到一个实例，用于零件级去重。已有其他绑定的检测框需先解绑。")
                imgui.begin_disabled(not binding["defect_id"] and not binding["class_name"].strip())
                if imgui.button("确认绑定"):
                    created = []
                    def operation():
                        created.append(self.actions.bind(image, binding["ids"], binding["defect_id"] or None, binding["class_name"].strip(), binding["description"]))
                    if self._apply_action(operation, "已保存缺陷关联"):
                        self._selected_defect_id = created[0]
                        self._binding = None
                        imgui.close_current_popup()
                imgui.end_disabled()
                imgui.same_line()
                if imgui.button("取消"):
                    self._binding = None
                    imgui.close_current_popup()
                if self.error:
                    imgui.text_wrapped(self.error)
                imgui.end_popup()

    def _draw_statistics(self):
        if not self.project:
            imgui.text_disabled("请先打开项目")
            return
        if imgui.begin_tab_bar("statistics_tabs"):
            if imgui.begin_tab_item("图片级统计")[0]:
                stats = self.statistics_manager.image_statistics()
                imgui.text(f"图片数 {stats['total_images']} · 已审核 {stats['reviewed_images']} · 未审核框 {stats['unreviewed_count']}")
                if imgui.begin_table("class_statistics", 7, imgui.TableFlags_.borders | imgui.TableFlags_.scroll_y, (0, 300)):
                    for heading in ["类别"] + [review.display_name for review in ReviewType]:
                        imgui.table_setup_column(heading)
                    imgui.table_headers_row()
                    for class_name, values in stats["by_class"].items():
                        imgui.table_next_row()
                        imgui.table_next_column()
                        imgui.text(class_name)
                        for review_type in ReviewType:
                            imgui.table_next_column()
                            imgui.text(str(values.get(review_type.value, 0)))
                    imgui.end_table()
                imgui.end_tab_item()
            if imgui.begin_tab_item("零件级统计")[0]:
                stats = self.statistics_manager.part_statistics()
                metrics = " · ".join(f"{name} {stats[key]:.2%}" if stats[key] is not None else f"{name} —" for key, name in (("precision", "Precision"), ("recall", "Recall"), ("f1", "F1")))
                imgui.text(metrics)
                if imgui.begin_table("part_statistics", 7, imgui.TableFlags_.borders | imgui.TableFlags_.scroll_y, (0, 300)):
                    for heading in ("零件", "缺陷数", "检出", "漏报", "误报", "错报", "过杀"):
                        imgui.table_setup_column(heading)
                    imgui.table_headers_row()
                    for part in stats["per_part"]:
                        imgui.table_next_row()
                        for key in ("part_id", "total_defects", "detected", "missed", "false_positive", "wrong_class", "overkill"):
                            imgui.table_next_column()
                            imgui.text(str(part[key]))
                    imgui.end_table()
                imgui.end_tab_item()
            imgui.end_tab_bar()

    def cleanup(self):
        self._texture = None
        self._thumbnail_cache.clear()
        self.config.set("ui.left_width", self._left_width)
        self.config.set("ui.right_width", self._right_width)
        self.config.set("ui.thumbnail_height", self._thumbnail_height)

    def can_exit(self):
        if self._inference_running:
            self.error = "模型识别进行中，请等待完成后退出。"
            return False
        return True


def load_chinese_font():
    project_root = Path(__file__).resolve().parent.parent
    font_paths = (
        Path(getattr(sys, "_MEIPASS", project_root)) / "fonts" / "NotoSansSC.otf",
        Path(r"C:\Windows\Fonts\msyh.ttc"),
        Path(r"C:\Windows\Fonts\simhei.ttf"),
        Path("/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc"),
        Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"),
        Path("/System/Library/Fonts/PingFang.ttc"),
    )
    for font_path in font_paths:
        if font_path.is_file():
            hello_imgui.load_font(str(font_path), 16.0)
            return
    logger.warning("未找到支持中文的 UI 字体")


def run():
    app = VisionInspectApp()

    runner = hello_imgui.RunnerParams()
    runner.app_window_params.window_title = "VisionInspect - AI模型识别结果标记评估程序"
    runner.app_window_params.window_geometry.size = (1440, 900)
    runner.imgui_window_params.default_imgui_window_type = hello_imgui.DefaultImGuiWindowType.no_default_window
    runner.imgui_window_params.remember_theme = False
    if getattr(sys, "frozen", False):
        data_directory().mkdir(parents=True, exist_ok=True)
        runner.ini_filename = str(data_directory() / "VisionInspect_imgui.ini")
    else:
        runner.ini_filename = "VisionInspect_imgui.ini"
    runner.callbacks.show_gui = app.draw
    runner.callbacks.load_additional_fonts = load_chinese_font
    runner.callbacks.before_exit = app.cleanup
    runner.callbacks.confirm_exit = app.can_exit
    immapp.run(runner)
