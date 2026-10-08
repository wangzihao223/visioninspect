"""主窗口模块.

整合所有 UI 控件与业务逻辑：
    - 菜单栏（文件/工具/统计分析/帮助）
    - 左侧零件树
    - 中央图片查看器
    - 右侧标注结果面板
    - 底部缩略图条
    - 状态栏审核进度
    - 审核交互（右键菜单 + 快捷键）
    - YOLO 批量推理（后台线程）
    - 缺陷关联与统计分析
"""

import os
from datetime import datetime

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtGui import QAction, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressDialog,
    QSplitter,
    QVBoxLayout,
    QWidget,
    QApplication,
)

from core.annotation_manager import AnnotationManager
from core.defect_manager import DefectManager
from core.image_manager import ImageManager
from core.project_manager import ProjectManager
from core.review_manager import ReviewManager
from core.statistics_manager import StatisticsManager
from data.image_data import Annotation, ImageData
from models.model_manager import ModelManager
from models.yolo_engine import YOLOEngine
from storage.config_manager import ConfigManager
from storage.json_reader import JsonManager
from ui.dialogs import DefectBindDialog, ModelSelectDialog, StatisticsDialog, UserDialog
from ui.image_view import ImageViewer
from ui.result_panel import ResultPanel
from ui.status_bar import StatusBarWidget
from ui.thumbnail_view import ThumbnailWidget
from ui.tree_widget import PartTreeWidget
from utils.common import ReviewStatus, ReviewType
from utils.logger import get_logger

logger = get_logger(__name__)


class InferenceWorker(QThread):
    """YOLO 推理后台线程."""

    progress = Signal(int, int, str)   # 当前, 总数, 消息
    finished_ok = Signal(dict)
    failed = Signal(str)

    def __init__(self, engine: YOLOEngine, project, force: bool = False, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.project = project
        self.force = force

    def run(self):
        """线程执行."""
        try:
            result = self.engine.predict_folder(
                self.project,
                force=self.force,
                progress_callback=self._on_progress,
            )
            self.finished_ok.emit(result)
        except Exception as e:
            logger.error("推理线程异常: %s", e)
            self.failed.emit(str(e))

    def _on_progress(self, current: int, total: int, message: str):
        """进度回调."""
        self.progress.emit(current, total, message)


class MainWindow(QMainWindow):
    """主窗口."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("VisionInspect - AI模型识别结果标记评估程序")
        self.resize(1440, 900)

        # 管理人员
        self.config = ConfigManager()
        self.project_manager = ProjectManager()
        self.image_manager = ImageManager()
        self.annotation_manager = AnnotationManager()
        default_user = self.config.get("review.default_user", "admin")
        self.review_manager = ReviewManager(str(default_user))
        self.defect_manager = DefectManager()
        self.statistics_manager = StatisticsManager()
        self.model_manager = ModelManager()
        self.yolo_engine = YOLOEngine()

        # 推理线程
        self.inference_worker = None
        self.progress_dialog = None

        self._init_ui()
        self._setup_menu()
        self._setup_shortcuts()
        self._connect_signals()

    # ------------------------------------------------------------------
    # UI 构建
    # ------------------------------------------------------------------
    def _init_ui(self):
        """构建主界面布局."""
        # 状态栏
        self.status_widget = StatusBarWidget()
        self.setStatusBar(self.status_widget)

        # 左侧：搜索框 + 零件树
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("搜索目录或文件名...")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setMinimumWidth(220)

        self.tree_widget = PartTreeWidget()

        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(2)
        left_layout.addWidget(self.search_edit, 0)
        left_layout.addWidget(self.tree_widget, 1)

        # 中央图片查看器
        self.image_viewer = ImageViewer()
        self.image_viewer.setMinimumSize(600, 400)

        # 右侧标注面板
        self.result_panel = ResultPanel()

        # 底部缩略图
        self.thumbnail_widget = ThumbnailWidget()

        # 中央区域
        center_widget = QWidget()
        center_layout = QVBoxLayout(center_widget)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(0)

        # 图片显示 + 右侧面板
        main_splitter = QSplitter(Qt.Orientation.Horizontal)
        main_splitter.addWidget(self.image_viewer)
        main_splitter.addWidget(self.result_panel)
        main_splitter.setStretchFactor(0, 4)
        main_splitter.setStretchFactor(1, 1)
        main_splitter.setSizes([1000, 300])

        # 中间区域 + 缩略图
        center_layout.addWidget(main_splitter, 1)
        center_layout.addWidget(self.thumbnail_widget, 0)

        # 全部布局
        root_layout = QHBoxLayout()
        root_splitter = QSplitter(Qt.Orientation.Horizontal)
        root_splitter.addWidget(left_widget)
        root_splitter.addWidget(center_widget)
        root_splitter.setStretchFactor(0, 1)
        root_splitter.setStretchFactor(1, 4)
        root_splitter.setSizes([260, 1100])

        root_widget = QWidget()
        root_layout.addWidget(root_splitter)
        root_widget.setLayout(root_layout)
        self.setCentralWidget(root_widget)

        # 初始状态
        self.status_widget.reset()

    # ------------------------------------------------------------------
    # 菜单栏
    # ------------------------------------------------------------------
    def _setup_menu(self):
        """构建菜单栏."""
        menubar = self.menuBar()

        # 文件菜单
        file_menu = menubar.addMenu("文件(&F)")
        self.action_open_project = QAction("打开数据目录...", self)
        self.action_open_project.setShortcut(QKeySequence("Ctrl+O"))
        self.action_open_project.triggered.connect(self.open_project_dialog)
        file_menu.addAction(self.action_open_project)

        file_menu.addSeparator()
        self.action_export_report = QAction("导出Excel评估报告...", self)
        self.action_export_report.setShortcut(QKeySequence("Ctrl+E"))
        self.action_export_report.triggered.connect(self.export_report)
        file_menu.addAction(self.action_export_report)

        file_menu.addSeparator()
        self.action_exit = QAction("退出", self)
        self.action_exit.setShortcut(QKeySequence("Ctrl+Q"))
        self.action_exit.triggered.connect(self.close)
        file_menu.addAction(self.action_exit)

        # 工具菜单
        tool_menu = menubar.addMenu("工具(&T)")
        self.action_select_model = QAction("加载YOLO模型...", self)
        self.action_select_model.setShortcut(QKeySequence("Ctrl+M"))
        self.action_select_model.triggered.connect(self.load_model_dialog)
        tool_menu.addAction(self.action_select_model)

        self.action_run_inference = QAction("批量模型识别...", self)
        self.action_run_inference.triggered.connect(self.run_inference_dialog)
        tool_menu.addAction(self.action_run_inference)

        tool_menu.addSeparator()
        self.action_set_user = QAction("设置审核人员...", self)
        self.action_set_user.triggered.connect(self.set_user_dialog)
        tool_menu.addAction(self.action_set_user)

        self.action_bind_defect = QAction("缺陷实例关联...", self)
        self.action_bind_defect.triggered.connect(self.bind_defect_dialog)
        tool_menu.addAction(self.action_bind_defect)

        # 统计分析菜单
        stat_menu = menubar.addMenu("统计分析(&S)")
        self.action_image_stats = QAction("图片级统计", self)
        self.action_image_stats.triggered.connect(self.show_image_statistics)
        stat_menu.addAction(self.action_image_stats)

        self.action_part_stats = QAction("零件级统计", self)
        self.action_part_stats.triggered.connect(self.show_part_statistics)
        stat_menu.addAction(self.action_part_stats)

        # 帮助菜单
        help_menu = menubar.addMenu("帮助(&H)")
        self.action_about = QAction("关于", self)
        self.action_about.triggered.connect(self.show_about)
        help_menu.addAction(self.action_about)

    # ------------------------------------------------------------------
    # 快捷键
    # ------------------------------------------------------------------
    def _setup_shortcuts(self):
        """设置审核快捷键."""
        shortcuts = {
            "A": self._on_prev_image,
            "D": self._on_next_image,
            "E": self._focus_next_annotation,
            "F": self._on_next_unreview,
            "1": lambda: self._quick_review(ReviewType.CORRECT),
            "2": lambda: self._quick_review(ReviewType.MISS),
            "3": lambda: self._quick_review(ReviewType.WRONG_CLASS),
            "4": lambda: self._quick_review(ReviewType.FALSE_POSITIVE),
            "5": lambda: self._quick_review(ReviewType.OVERKILL),
            "0": lambda: self._quick_review(ReviewType.UNREVIEW),
            "Del": self._delete_selected_annotation,
            "+": self.image_viewer.zoom_in,
            "-": self.image_viewer.zoom_out,
            "Ctrl+0": self.image_viewer.reset_view,
        }
        self._shortcuts = {}
        for key, callback in shortcuts.items():
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.activated.connect(callback)
            self._shortcuts[key] = shortcut

    # ------------------------------------------------------------------
    # 信号连接
    # ------------------------------------------------------------------
    def _connect_signals(self):
        """连接信号."""
        # 搜索框 → 树过滤
        self.search_edit.textChanged.connect(self.tree_widget.filter)

        # 树 → 业务
        self.tree_widget.part_selected.connect(self._on_part_selected)
        self.tree_widget.image_selected.connect(self.load_image_by_id)
        self.tree_widget.image_mark_review_requested.connect(self._on_mark_image_reviewed)
        self.tree_widget.image_clear_review_requested.connect(self._on_clear_image_review)

        # 缩略图 → 业务
        self.thumbnail_widget.thumbnail_clicked.connect(self._on_thumbnail_clicked)

        # 图片查看器 → 业务
        self.image_viewer.annotation_clicked.connect(self._on_annotation_clicked)
        self.image_viewer.box_drawn.connect(self._on_box_drawn)
        self.image_viewer.review_requested.connect(self._on_right_click_review)
        self.image_viewer.class_change_requested.connect(self._on_class_change_requested)
        self.image_viewer.delete_requested.connect(self._on_delete_annotation)

        # 结果面板
        self.result_panel.annotation_selected.connect(self._on_annotation_selected)
        self.result_panel.annotation_review_requested.connect(self._on_right_click_review)
        self.result_panel.annotation_class_change_requested.connect(self._on_class_change_requested)
        self.result_panel.annotation_delete_requested.connect(self._on_delete_annotation)
        self.result_panel.annotations_review_requested.connect(self._on_batch_review)
        self.result_panel.annotations_class_change_requested.connect(self._on_batch_class_change)
        self.result_panel.annotations_delete_requested.connect(self._on_batch_delete)
        self.result_panel.defect_selected.connect(self._on_defect_selected)
        self.result_panel.defect_deleted.connect(self._on_defect_deleted)
        self.result_panel.new_defect_btn.clicked.connect(self._on_new_defect_from_selected)

    # ------------------------------------------------------------------
    # 项目操作
    # ------------------------------------------------------------------
    def open_project_dialog(self):
        """打开数据目录."""
        last_project = self.config.get("paths.last_project", "")
        if not os.path.isdir(str(last_project)):
            last_project = os.path.join(os.path.dirname(os.path.dirname(__file__)), "examples")
        path = QFileDialog.getExistingDirectory(
            self,
            "选择数据根目录",
            str(last_project),
        )
        if not path:
            return

        try:
            project = self.project_manager.open_project(path)
            self.config.set("paths.last_project", path)
        except Exception as e:
            QMessageBox.critical(self, "错误", f"打开项目失败:\n{e}")
            return

        # 绑定管理人
        self.image_manager.set_project(project)
        self.annotation_manager.set_image(project.get_current_image())
        self.defect_manager.set_project(project)
        self.statistics_manager.set_project(project)
        self.defect_manager.select_defect(None)
        # 设置图片查看器的项目引用（用于显示缺陷编号）
        self.image_viewer._project = project

        # 刷新界面
        self._refresh_all()

        # 加载当前图片
        current = project.get_current_image()
        if current:
            self._show_image(current)
        else:
            self.image_viewer.clear_view()
            self.review_manager.current_image = None
            self.result_panel.set_image(None)
            self.result_panel.load_defects("", [])
            self.thumbnail_widget.load_images([])
            self.status_widget.update_current()

    def _refresh_all(self):
        """刷新全部界面."""
        project = self.project_manager.current_project
        if not project:
            return

        self.tree_widget.load_project(
            project,
            project.current_part_id,
            project.current_image_id,
        )

        # 若搜索框有关键字，刷新后重新应用过滤
        if self.search_edit.text().strip():
            self.tree_widget.filter(self.search_edit.text())

        part = project.get_current_part()
        if part:
            self.thumbnail_widget.load_images(part.images, project.current_image_id)

        self.status_widget.update_progress(project)

    # ------------------------------------------------------------------
    # 图片浏览
    # ------------------------------------------------------------------
    def _on_part_selected(self, part_id: str):
        """选中零件."""
        project = self.project_manager.current_project
        if not project:
            return
        part = project.get_part(part_id)
        if not part:
            return
        project.current_part_id = part_id
        # 选中零件时默认加载第一张未审核或第一张
        if part.images:
            target = part.images[0]
            for img in part.images:
                if not img.is_review_finished():
                    target = img
                    break
            self.load_image_by_id(part_id, target.image_id)
        else:
            # 无图片，刷新状态栏
            self.status_widget.update_current(part_id)
            self.status_widget.update_progress(project)

    def load_image_by_id(self, part_id: str, image_id: str):
        """按零件/图片 id 加载."""
        img = self.image_manager.load_image(part_id, image_id)
        if img:
            self._show_image(img)
            self._sync_tree_selection(part_id, image_id)

    def _on_thumbnail_clicked(self, image):
        """点击缩略图."""
        self.load_image_by_id(image.part_id, image.image_id)

    def _show_image(self, image: ImageData):
        """显示图片并更新周边控件."""
        self.image_viewer.show_image(image)
        self.annotation_manager.set_image(image)
        self.review_manager.current_image = image
        self.result_panel.set_image(image)

        # 状态栏
        part = self.project_manager.current_project.get_part(image.part_id) if self.project_manager.current_project else None
        self.status_widget.update_current(image.part_id, image.file_name)
        if part:
            self.thumbnail_widget.load_images(part.images, image.image_id)
            # 同步右侧缺陷实例列表
            self.result_panel.refresh_defects(part.part_id, part.defects)

        # 缩略图选中同步
        self.thumbnail_widget.select_image(image.image_id)

    def _sync_tree_selection(self, part_id: str, image_id: str):
        """同步树选中."""
        self.tree_widget.select_image(part_id, image_id)

    # ------------------------------------------------------------------
    # 快捷键图片切换（A/D/F）
    # ------------------------------------------------------------------
    def _on_prev_image(self):
        """上一张图片（快捷键 A）."""
        img = self.image_manager.previous_image()
        self._after_image_switch(img)

    def _on_next_image(self):
        """下一张图片（快捷键 D）."""
        img = self.image_manager.next_image()
        self._after_image_switch(img)

    def _on_next_unreview(self):
        """跳转下一张未审核图片（快捷键 F）."""
        img = self.image_manager.next_unreview_image()
        if img is None:
            project = self.project_manager.current_project
            if project:
                self.status_widget.update_progress(project)
            self.statusBar().showMessage("所有图片均已审核完成", 3000)
            return
        self._after_image_switch(img)

    def _after_image_switch(self, img):
        """图片切换后的统一刷新处理."""
        if img is None:
            return
        project = self.project_manager.current_project
        if project is None:
            return
        # 同步项目当前状态
        project.current_part_id = img.part_id
        project.current_image_id = img.image_id
        # 刷新主图与右侧面板
        self._show_image(img)
        # 同步树节点选中
        self.tree_widget.select_image(img.part_id, img.image_id)
        # 刷新状态栏
        self.status_widget.update_current(img.part_id, img.file_name)
        self.status_widget.update_progress(project)
        # 空余状态栏显示当前进度信息
        current_part = self.image_manager.current_part
        if current_part:
            self.statusBar().showMessage(
                f"第 {self.image_manager.image_index + 1}/{len(current_part.images)} 张",
                3000,
            )

    # ------------------------------------------------------------------
    # 审核操作
    # ------------------------------------------------------------------
    def _on_annotation_clicked(self, annotation: Annotation):
        """点击标注框."""
        self.annotation_manager.select_box(annotation)
        self._sync_result_panel_selection(annotation)

    def _on_annotation_selected(self, annotation: Annotation):
        """从结果面板选中标注."""
        self.annotation_manager.select_box(annotation)
        self.image_viewer.focus_annotation(annotation)
        x1, y1, x2, y2 = [int(round(v)) for v in annotation.bbox]
        class_name = annotation.review_class or annotation.class_name or "缺陷"
        self.statusBar().showMessage(
            f"已定位缺陷: {class_name} ({x1}, {y1})-({x2}, {y2})",
            3000,
        )

    def _focus_next_annotation(self):
        """Shortcut E: locate the next defect box in the current image."""
        image = self.annotation_manager.current_image
        if not image or not image.annotations:
            self.statusBar().showMessage("当前图片没有缺陷框", 3000)
            return

        annotations = image.annotations
        selected = self.annotation_manager.selected_annotation
        try:
            next_index = (annotations.index(selected) + 1) % len(annotations)
        except ValueError:
            next_index = 0

        annotation = annotations[next_index]
        self.annotation_manager.select_box(annotation)
        self.image_viewer.focus_annotation(annotation)
        self._sync_result_panel_selection(annotation)

        x1, y1, x2, y2 = [int(round(v)) for v in annotation.bbox]
        class_name = annotation.review_class or annotation.class_name or "缺陷"
        self.statusBar().showMessage(
            f"已定位缺陷 {next_index + 1}/{len(annotations)}: {class_name} "
            f"({x1}, {y1})-({x2}, {y2})",
            3000,
        )

    def _sync_result_panel_selection(self, annotation: Annotation):
        """同步结果面板选中行."""
        anns = self.annotation_manager.current_annotations
        if annotation in anns:
            row = anns.index(annotation)
            self.result_panel.selectRow(row)

    def _quick_review(self, review_type: ReviewType):
        """快捷键快速审核当前选中的标注."""
        ann = self.annotation_manager.selected_annotation
        if ann is None:
            return
        self._apply_review(ann, review_type)

    def _apply_review(self, annotation: Annotation, review_type: ReviewType):
        """应用审核并保存."""
        # 应用审核
        if review_type == ReviewType.CORRECT:
            self.review_manager.set_correct(annotation)
        elif review_type == ReviewType.MISS:
            self.review_manager.set_miss(annotation)
        elif review_type == ReviewType.WRONG_CLASS:
            self.review_manager.set_wrong_class(annotation)
        elif review_type == ReviewType.FALSE_POSITIVE:
            self.review_manager.set_false_positive(annotation)
        elif review_type == ReviewType.OVERKILL:
            self.review_manager.set_overkill(annotation)
        elif review_type == ReviewType.UNREVIEW:
            self.review_manager.set_unreview(annotation)

        # 更新界面
        self.image_viewer.update_annotation_style(annotation)
        self.result_panel.refresh()

        # 保存 JSON
        self._save_current_image()

        # 更新树/缩略图状态
        self._refresh_status_after_review()

    def _delete_selected_annotation(self):
        """删除当前选中的标注（Del 键）. """
        ann = self.annotation_manager.selected_annotation
        if ann is None:
            return
        self._delete_annotation(ann)

    def _on_delete_annotation(self, annotation: Annotation):
        """从右键菜单删除标注.

        Args:
            annotation: 要删除的标注
        """
        if annotation is None:
            return
        self._delete_annotation(annotation)

    def _delete_annotation(self, annotation: Annotation):
        """删除标注通用方法."""
        if annotation is None:
            return
        if self.annotation_manager.delete_box(annotation):
            self.image_viewer.refresh_annotations()
            self.result_panel.refresh()
            self._save_current_image()
            self._refresh_status_after_review()

    def _on_right_click_review(self, annotation: Annotation, review_type):
        """右键菜单选择的审核类型."""
        if annotation is None:
            return
        # 同步选中
        self.annotation_manager.select_box(annotation)
        self.image_viewer.set_selected_annotation(annotation)
        self._sync_result_panel_selection(annotation)
        # 应用审核
        self._apply_review(annotation, review_type)

    def _on_class_change_requested(self, annotation: Annotation, class_name: str):
        """右键菜单修改标注类别.

        Args:
            annotation: 要修改类别的标注
            class_name: 新的缺陷类别名称
        """
        if annotation is None or not class_name:
            return
        self.annotation_manager.update_label(annotation, class_name)
        self.image_viewer.refresh_annotations()
        self.result_panel.refresh()
        self._save_current_image()
        self._refresh_status_after_review()
        logger.debug("修改标注 %s 类别为: %s", annotation.id, class_name)

    # ------------------------------------------------------------------
    # 批量操作
    # ------------------------------------------------------------------
    def _on_batch_review(self, annotations: list, review_type: ReviewType):
        """批量应用审核.

        Args:
            annotations: 选中的标注列表
            review_type: 审核类型
        """
        if not annotations or review_type is None:
            return
        for ann in annotations:
            if review_type == ReviewType.CORRECT:
                self.review_manager.set_correct(ann)
            elif review_type == ReviewType.MISS:
                self.review_manager.set_miss(ann)
            elif review_type == ReviewType.WRONG_CLASS:
                self.review_manager.set_wrong_class(ann)
            elif review_type == ReviewType.FALSE_POSITIVE:
                self.review_manager.set_false_positive(ann)
            elif review_type == ReviewType.OVERKILL:
                self.review_manager.set_overkill(ann)
            elif review_type == ReviewType.UNREVIEW:
                self.review_manager.set_unreview(ann)

        # 统一刷新界面与保存
        self.image_viewer.refresh_annotations()
        self.result_panel.refresh()
        self._save_current_image()
        self._refresh_status_after_review()
        logger.debug("批量审核 %d 个标注 → %s", len(annotations), review_type.display_name)

    def _on_batch_class_change(self, annotations: list, class_name: str):
        """批量修改标注类别.

        Args:
            annotations: 选中的标注列表
            class_name: 新的缺陷类别名称
        """
        if not annotations or not class_name:
            return
        for ann in annotations:
            self.annotation_manager.update_label(ann, class_name)

        # 统一刷新界面与保存
        self.image_viewer.refresh_annotations()
        self.result_panel.refresh()
        self._save_current_image()
        self._refresh_status_after_review()
        logger.debug("批量修改 %d 个标注类别为: %s", len(annotations), class_name)

    def _on_batch_delete(self, annotations: list):
        """批量删除标注（带确认）.

        Args:
            annotations: 选中的标注列表
        """
        if not annotations:
            return
        ret = QMessageBox.question(
            self,
            "确认删除",
            f"确定要删除选中的 {len(annotations)} 个标注吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if ret != QMessageBox.StandardButton.Yes:
            return

        for ann in annotations:
            self.annotation_manager.delete_box(ann)

        # 统一刷新界面与保存
        self.image_viewer.refresh_annotations()
        self.result_panel.refresh()
        self._save_current_image()
        self._refresh_status_after_review()
        logger.debug("批量删除 %d 个标注", len(annotations))

    # ------------------------------------------------------------------
    # 缺陷实例操作
    # ------------------------------------------------------------------
    def _on_defect_selected(self, defect):
        """从缺陷实例面板选中缺陷实例."""
        if defect is None:
            return
        self.defect_manager.select_defect(defect)
        # 刷新主图（高亮绑定框）
        img = self.annotation_manager.current_image
        if img:
            self.image_viewer.refresh_annotations()
        self.statusBar().showMessage(
            f"已选择缺陷实例 #{defect.index or ''} {defect.class_name}，"
            f"绑定 {len(defect.annotation_bindings)} 个检测框",
            3000,
        )

    def _on_defect_deleted(self, part_id: str, defect_id: str):
        """删除缺陷实例."""
        if not part_id or not defect_id:
            return
        if self.defect_manager.delete_defect(part_id, defect_id):
            # 刷新缺陷实例列表 + 主图标注
            project = self.project_manager.current_project
            if project:
                part = project.get_part(part_id)
                if part and part.part_id == project.current_part_id:
                    self.result_panel.refresh_defects(part.part_id, part.defects)
            img = self.annotation_manager.current_image
            if img:
                self.image_viewer.refresh_annotations()
            self.statusBar().showMessage(f"已删除缺陷实例: {defect_id}", 3000)

    def _on_new_defect_from_selected(self):
        """从当前选中的检测框创建新缺陷实例并绑定."""
        project = self.project_manager.current_project
        if not project:
            QMessageBox.warning(self, "提示", "请先打开数据目录")
            return
        part = project.get_current_part()
        ann = self.annotation_manager.selected_annotation
        if not part or not ann:
            QMessageBox.warning(self, "提示", "请先在图片中选中一个检测框")
            return
        if ann.defect_id:
            QMessageBox.warning(self, "提示", "该检测框已绑定到缺陷实例，无需重复创建")
            return

        config = ConfigManager()
        defect_classes = config.get_defect_classes()
        dlg = DefectBindDialog(self, defect_classes, part.defects)
        if dlg.exec() != dlg.DialogCode.Accepted:
            return

        img = self.annotation_manager.current_image
        if not img:
            return

        try:
            if dlg.create_new:
                defect = self.defect_manager.create_defect(
                    part.part_id, dlg.selected_class, dlg.desc_edit.text()
                )
            else:
                defect = self.defect_manager.get_defect(part.part_id, str(dlg.selected_defect_id))
                if not defect:
                    QMessageBox.warning(self, "错误", "缺陷实例不存在")
                    return
                self.defect_manager.select_defect(defect)

            # 设置零件内编号
            for idx, d in enumerate(part.defects, 1):
                d.index = idx

            if self.defect_manager.bind_annotation(part.part_id, img, ann):
                # 刷新全部界面
                self.result_panel.refresh_defects(part.part_id, part.defects)
                self.image_viewer.refresh_annotations()
                self._save_current_image()
                self.statusBar().showMessage(
                    f"检测框已绑定到缺陷 #{defect.index} {defect.class_name}", 3000
                )
            else:
                QMessageBox.warning(self, "绑定失败", "无法绑定该标注到缺陷实例")
        except Exception as e:
            QMessageBox.critical(self, "操作失败", str(e))

    def _refresh_status_after_review(self):
        """审核后刷新状态（树/缩略图/状态栏/进度）."""
        project = self.project_manager.current_project
        if not project:
            return
        part = project.get_current_part()
        if part:
            self.tree_widget.update_part_status(part)
        img = project.get_current_image()
        if img:
            self.tree_widget.update_image_status(img.part_id, img.image_id, img)
            self.thumbnail_widget.update_image_style(img.image_id, img)
        self.status_widget.update_progress(project)

    def _save_current_image(self):
        """保存当前图片 JSON."""
        img = self.annotation_manager.current_image
        if img:
            self.review_manager.finalize_image(img)
            if not JsonManager.save_image_data(img):
                QMessageBox.critical(self, "保存失败", f"无法保存审核结果，请检查目录写入权限：\n{img.json_path}")
                return False
        return True

    # ------------------------------------------------------------------
    # 图片级审核操作（树右键菜单）
    # ------------------------------------------------------------------
    def _on_mark_image_reviewed(self, part_id: str, image_id: str):
        """标记图片已审核：创建空审核数据（该图无任何识别目标）.

        Args:
            part_id: 零件号
            image_id: 图片 id
        """
        project = self.project_manager.current_project
        if not project:
            return
        part = project.get_part(part_id)
        if not part:
            return
        img = part.get_image(image_id)
        if not img:
            return

        # 已审核过则不做操作
        if img.is_ever_reviewed():
            self.statusBar().showMessage(f"图片已审核过，无需重复标记: {img.file_name}", 3000)
            return

        # 创建空审核数据：清空全部标注（表示无识别目标），记录审核人/时间
        img.annotations = []
        img.review_user = self.review_manager.current_user
        img.review_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        img.review_status_text = "finished"
        JsonManager.save_image_data(img)

        # 刷新树/缩略图/状态栏
        self._refresh_image_review_ui(img)

        self.statusBar().showMessage(f"已标记审核（无识别目标）: {img.file_name}", 3000)
        logger.info("标记图片已审核: %s（用户=%s）", img.image_id, img.review_user)

    def _on_clear_image_review(self, part_id: str, image_id: str):
        """清空图片审核：确认后删除审核 JSON 并清除内存审核数据.

        Args:
            part_id: 零件号
            image_id: 图片 id
        """
        project = self.project_manager.current_project
        if not project:
            return
        part = project.get_part(part_id)
        if not part:
            return
        img = part.get_image(image_id)
        if not img:
            return

        # 不存在审核数据则提示
        if not JsonManager.json_exists(img):
            self.statusBar().showMessage(f"该图片无审核数据: {img.file_name}", 3000)
            return

        # 确认删除
        ret = QMessageBox.question(
            self,
            "确认清空审核",
            f"确定要删除该图片的审核数据吗？\n{img.file_name}\n（将同时删除对应的 JSON 文件）",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if ret != QMessageBox.StandardButton.Yes:
            return

        # 删除 JSON 文件
        try:
            if os.path.exists(img.json_path):
                os.remove(img.json_path)
        except OSError as e:
            QMessageBox.critical(self, "删除失败", f"删除 JSON 文件失败:\n{e}")
            return

        # 清除内存审核数据
        img.annotations = []
        img.review_user = ""
        img.review_time = ""
        img.review_status_text = "unreviewed"

        # 刷新树/缩略图/状态栏
        self._refresh_image_review_ui(img)

        self.statusBar().showMessage(f"已清空审核: {img.file_name}", 3000)
        logger.info("清空图片审核: %s", img.image_id)

    def _refresh_image_review_ui(self, img):
        """刷新图片审核操作后的界面状态（树/缩略图/状态栏/当前主图）."""
        project = self.project_manager.current_project
        if not project:
            return

        # 刷新零件与图片节点状态
        part = project.get_part(img.part_id)
        if part:
            self.tree_widget.update_part_status(part)
        self.tree_widget.update_image_status(img.part_id, img.image_id, img)

        # 若该零件是当前显示零件，刷新缩略图
        if img.part_id == project.current_part_id:
            current_part = project.get_current_part()
            if current_part:
                self.thumbnail_widget.load_images(current_part.images, project.current_image_id)

        # 若该图片是当前显示图片，刷新主图标注与结果面板
        current_img = self.annotation_manager.current_image
        if current_img and current_img.image_id == img.image_id:
            self.image_viewer.refresh_annotations()
            self.result_panel.set_image(img)

        self.status_widget.update_progress(project)

    # ------------------------------------------------------------------
    # 框选新增人工标注
    # ------------------------------------------------------------------
    def _on_box_drawn(self, bbox: list):
        """框选完成 → 新增人工标注框."""
        if not self.annotation_manager.current_image:
            return
        # 使用默认类别
        from storage.config_manager import ConfigManager

        config = ConfigManager()
        classes = config.get_defect_classes()
        class_name = classes[0] if classes else "缺陷"

        # 新增人工框默认审核状态为"漏报"（人工框选即模型漏检的缺陷）
        ann = self.annotation_manager.add_box(bbox, class_name=class_name)
        ann.review_type = ReviewType.MISS  # 人工新增框默认标记为"漏报"
        ann.review_class = class_name

        self.image_viewer.refresh_annotations()
        self.result_panel.refresh()
        self._save_current_image()

        # 选中新框（便于直接审核），但不弹模态框，避免快捷键误触发
        self.annotation_manager.select_box(ann)
        self.image_viewer.set_selected_annotation(ann)

        # 使用状态栏临时提示而非模态对话框，避免阻塞时快捷键误操作
        self.statusBar().showMessage(
            f"已新增人工检测框（类别：{class_name}，状态：漏报）"
            " | 可右键或数字键调整审核类型",
            5000,
        )

    # ------------------------------------------------------------------
    # 模型识别
    # ------------------------------------------------------------------
    def load_model_dialog(self):
        """加载模型."""
        last_model = self.config.get("paths.last_model", "")
        dlg = QFileDialog.getOpenFileName(
            self,
            "选择 YOLO 模型",
            str(last_model),
            "YOLO 模型 (*.pt)",
        )
        if not dlg[0]:
            return
        path = dlg[0]

        try:
            info = self.model_manager.load_model(path)
            self.config.set("paths.last_model", path)
            self.yolo_engine.set_model(self.model_manager.current_model, info)
            # 应用推理配置
            conf = float(str(self.config.get("inference.confidence_threshold", 0.25)))
            iou = float(str(self.config.get("inference.iou_threshold", 0.45)))
            self.yolo_engine.configure(conf_thres=conf, iou_thres=iou)
            QMessageBox.information(
                self,
                "模型加载成功",
                f"模型: {info.model_name}\n版本: {info.version}\n类别: {len(info.classes)} 个",
            )
        except Exception as e:
            QMessageBox.critical(self, "加载失败", f"模型加载失败:\n{e}")

    def run_inference_dialog(self):
        """批量模型识别."""
        if not self.project_manager.current_project:
            QMessageBox.warning(self, "提示", "请先打开数据目录")
            return
        if self.model_manager.current_model is None:
            QMessageBox.warning(self, "提示", "请先加载 YOLO 模型")
            return

        last_model = self.config.get("paths.last_model", "")
        dlg = ModelSelectDialog(self, str(last_model))
        if dlg.exec() != dlg.DialogCode.Accepted:
            return

        # 确认模型
        if dlg.model_path:
            try:
                info = self.model_manager.load_model(dlg.model_path)
                self.yolo_engine.set_model(self.model_manager.current_model, info)
                self.config.set("paths.last_model", dlg.model_path)
            except Exception as e:
                QMessageBox.critical(self, "加载模型失败", str(e))
                return

        # 启动后台线程
        self._start_inference(dlg.force)

    def _start_inference(self, force: bool):
        """启动推理线程."""
        if self.inference_worker and self.inference_worker.isRunning():
            QMessageBox.information(self, "提示", "推理任务正在进行中")
            return

        project = self.project_manager.current_project
        if not project:
            return

        self.inference_worker = InferenceWorker(self.yolo_engine, project, force)
        self.inference_worker.progress.connect(self._on_inference_progress)
        self.inference_worker.finished_ok.connect(self._on_inference_finished)
        self.inference_worker.failed.connect(self._on_inference_failed)

        # 进度对话框
        total = project.get_total_images()
        self.progress_dialog = QProgressDialog("正在批量识别...", "", 0, max(total, 1), self)
        self.progress_dialog.setCancelButton(None)
        self.progress_dialog.setWindowTitle("模型识别进度")
        self.progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self.progress_dialog.setAutoClose(False)
        self.progress_dialog.setAutoReset(False)
        self.progress_dialog.setMinimumWidth(400)
        self.inference_worker.start()
        self.progress_dialog.show()

    def _on_inference_progress(self, current: int, total: int, message: str):
        """推理进度."""
        if self.progress_dialog:
            self.progress_dialog.setMaximum(max(total, 1))
            self.progress_dialog.setValue(current)
            self.progress_dialog.setLabelText(f"{message}\n{current}/{total}")

    def _on_inference_finished(self, result: dict):
        """推理完成."""
        if self.progress_dialog:
            self.progress_dialog.close()
            self.progress_dialog = None

        # 重新加载项目（JSON 已更新）
        self.project_manager.reload_project()
        project = self.project_manager.current_project
        if project:
            self.image_manager.set_project(project)
            self.annotation_manager.set_image(project.get_current_image())
            self.defect_manager.set_project(project)
            self.defect_manager.select_defect(None)
            self.statistics_manager.set_project(project)
            self.image_viewer._project = project
            self._refresh_all()
            current = project.get_current_image()
            if current:
                self._show_image(current)

        QMessageBox.information(
            self,
            "识别完成",
            f"处理完成！\n"
            f"识别: {result.get('processed', 0)} 张\n"
            f"跳过: {result.get('skipped', 0)} 张\n"
            f"失败: {result.get('failed', 0)} 张",
        )

    def _on_inference_failed(self, error: str):
        """推理失败."""
        if self.progress_dialog:
            self.progress_dialog.close()
            self.progress_dialog = None
        QMessageBox.critical(self, "识别失败", f"模型识别失败:\n{error}")

    # ------------------------------------------------------------------
    # 缺陷关联
    # ------------------------------------------------------------------
    def bind_defect_dialog(self):
        """缺陷实例关联对话框."""
        project = self.project_manager.current_project
        if not project:
            QMessageBox.warning(self, "提示", "请先打开数据目录")
            return

        part = project.get_current_part()
        ann = self.annotation_manager.selected_annotation
        if not part or not ann:
            QMessageBox.warning(self, "提示", "请先在图片中选中一个检测框")
            return

        config = ConfigManager()
        defect_classes = config.get_defect_classes()
        current_defects = part.defects

        dlg = DefectBindDialog(self, defect_classes, current_defects)
        if dlg.exec() != dlg.DialogCode.Accepted:
            return

        img = self.annotation_manager.current_image
        if not img:
            return

        try:
            if dlg.create_new:
                # 创建新缺陷实例
                defect = self.defect_manager.create_defect(
                    part.part_id,
                    dlg.selected_class,
                    dlg.desc_edit.text(),
                )
            else:
                # 选择现有缺陷
                defect = self.defect_manager.get_defect(part.part_id, str(dlg.selected_defect_id))
                if not defect:
                    QMessageBox.warning(self, "错误", "缺陷实例不存在")
                    return
                self.defect_manager.select_defect(defect)

            # 绑定标注
            if self.defect_manager.bind_annotation(part.part_id, img, ann):
                self.image_viewer.update_annotation_style(ann)
                self.result_panel.refresh()
                self._save_current_image()
                QMessageBox.information(
                    self,
                    "绑定成功",
                    f"标注已绑定到缺陷: {defect.defect_id}\n"
                    f"可切换到其他相机图片继续绑定同一缺陷。",
                )
            else:
                QMessageBox.warning(self, "绑定失败", "无法绑定该标注到缺陷实例")
        except Exception as e:
            QMessageBox.critical(self, "操作失败", str(e))

    # ------------------------------------------------------------------
    # 统计与导出
    # ------------------------------------------------------------------
    def show_image_statistics(self):
        """显示图片级统计."""
        project = self.project_manager.current_project
        if not project:
            QMessageBox.warning(self, "提示", "请先打开数据目录")
            return

        stats = self.statistics_manager.image_statistics()
        text = (
            "======== 图片级统计 ========\n"
            f"总图片数: {stats.get('total_images', 0)}\n"
            f"已审核: {stats.get('reviewed_images', 0)}\n"
            "\n--- 审核结果统计 ---\n"
            f"正确: {stats.get('correct_count', 0)}\n"
            f"漏报: {stats.get('miss_count', 0)}\n"
            f"错报: {stats.get('wrong_class_count', 0)}\n"
            f"误报: {stats.get('false_positive_count', 0)}\n"
            f"过杀: {stats.get('overkill_count', 0)}\n"
            f"未审核: {stats.get('unreviewed_count', 0)}\n"
        )

        # 缺陷类别分布
        by_class = stats.get("by_class", {})
        if by_class:
            text += "\n--- 缺陷类别分布 ---\n"
            for cls, counts in by_class.items():
                text += (
                    f"{cls}: 正确{counts['correct']} 漏报{counts['miss']} "
                    f"错报{counts['wrong_class']} 误报{counts['false_positive']} "
                    f"过杀{counts['overkill']} 未审{counts['unreview']}\n"
                )

        dlg = StatisticsDialog(self, "图片级统计")
        dlg.set_text(text)
        dlg.exec()

    def show_part_statistics(self):
        """显示零件级统计."""
        project = self.project_manager.current_project
        if not project:
            QMessageBox.warning(self, "提示", "请先打开数据目录")
            return

        stats = self.statistics_manager.part_statistics()
        precision = stats.get("precision")
        recall = stats.get("recall")
        f1 = stats.get("f1")

        text = (
            "======== 零件级统计 ========\n"
            f"零件总数: {stats.get('total_parts', 0)}\n"
            f"缺陷实例总数: {stats.get('total_defects', 0)}\n"
            f"检测成功: {stats.get('detected', 0)}\n"
            f"漏检: {stats.get('missed', 0)}\n"
            f"误检: {stats.get('false_positive', 0)}\n"
            f"错检: {stats.get('wrong_class', 0)}\n"
            f"过杀: {stats.get('overkill', 0)}\n"
            "\n--- 评估指标 ---\n"
            f"Precision: {precision:.4f}\n" if precision is not None else "Precision: -\n"
            f"Recall: {recall:.4f}\n" if recall is not None else "Recall: -\n"
            f"F1 Score: {f1:.4f}\n" if f1 is not None else "F1 Score: -\n"
        )

        # 各零件详情
        per_part = stats.get("per_part", [])
        if per_part:
            text += "\n--- 各零件详情 ---\n"
            for p in per_part:
                text += (
                    f"{p.get('part_id', '')}: 缺陷{p.get('total_defects', 0)}个 "
                    f"[成功{p.get('detected', 0)} 漏{p.get('missed', 0)} "
                    f"误{p.get('false_positive', 0)} 错{p.get('wrong_class', 0)}]\n"
                )

        dlg = StatisticsDialog(self, "零件级统计")
        dlg.set_text(text)
        dlg.exec()

    def export_report(self):
        """导出 Excel 报告."""
        project = self.project_manager.current_project
        if not project:
            QMessageBox.warning(self, "提示", "请先打开数据目录")
            return

        path = QFileDialog.getSaveFileName(
            self,
            "保存Excel报告",
            os.path.join(project.root_path, "模型评估报告.xlsx"),
            "Excel 文件 (*.xlsx)",
        )
        if not path[0]:
            return

        try:
            output_dir = os.path.dirname(path[0])
            file_path = self.statistics_manager.export_report(output_dir)
            ret = QMessageBox.question(
                self,
                "导出成功",
                f"Excel 报告已导出:\n{file_path}\n\n是否立即打开？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if ret == QMessageBox.StandardButton.Yes:
                # 使用系统默认软件打开
                os.startfile(file_path)
        except Exception as e:
            QMessageBox.critical(self, "导出失败", f"导出报告失败:\n{e}")

    # ------------------------------------------------------------------
    # 其他
    # ------------------------------------------------------------------
    def set_user_dialog(self):
        """设置审核人员."""
        dlg = UserDialog(self, self.review_manager.current_user)
        if dlg.exec() == dlg.DialogCode.Accepted:
            self.review_manager.set_user(dlg.user_name)
            self.config.set("review.default_user", dlg.user_name)
            QMessageBox.information(self, "设置成功", f"审核人员: {dlg.user_name}")

    def show_about(self):
        """关于对话框."""
        QMessageBox.about(
            self,
            "关于 VisionInspect",
            "<h3>VisionInspect V2.0</h3>"
            "<p>AI模型识别结果标记评估程序</p>"
            "<p>功能：</p>"
            "<ul>"
            "<li>YOLO 模型批量识别</li>"
            "<li>人工审核标记（正确/漏报/错报/误报/过杀）</li>"
            "<li>零件级缺陷关联</li>"
            "<li>统计分析（Precision/Recall/F1）</li>"
            "<li>Excel 报告导出</li>"
            "</ul>",
        )

    def closeEvent(self, event):
        """关闭程序."""
        if self.inference_worker and self.inference_worker.isRunning():
            QMessageBox.information(self, "推理进行中", "请等待当前推理任务完成后退出。")
            event.ignore()
            return

        self.config.save_config()
        logger.info("程序退出")
        super().closeEvent(event)
