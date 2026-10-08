"""右侧标注结果面板.

包含两个 Tab：
    1. 标注结果：当前图片的标注列表（类别/置信度/审核状态/来源）
    2. 缺陷实例：当前零件的缺陷实例列表（编号/类别/绑定相机数）

支持右键审核、修改类别、删除标注、新建/删除缺陷实例。
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QMenu,
    QPushButton,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from data.defect_data import Defect
from data.image_data import Annotation, ImageData
from utils.common import ReviewType
from utils.logger import get_logger

logger = get_logger(__name__)

ANNOTATION_HEADERS = ["类别", "置信度", "审核", "来源"]
DEFECT_HEADERS = ["编号", "缺陷类别", "绑定相机数", "缺陷ID"]


class AnnotationTable(QTableWidget):
    """标注结果表格."""

    annotation_selected = Signal(object)
    annotation_review_requested = Signal(object, object)
    annotation_class_change_requested = Signal(object, str)
    annotation_delete_requested = Signal(object)
    annotations_review_requested = Signal(list, object)
    annotations_class_change_requested = Signal(list, str)
    annotations_delete_requested = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setColumnCount(4)
        self.setHorizontalHeaderLabels(ANNOTATION_HEADERS)
        self.verticalHeader().setVisible(False)
        self.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)

        self.cellClicked.connect(self._on_cell_clicked)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

        self._annotations = []

    def set_image(self, image: ImageData):
        """加载图片的标注列表."""
        self._annotations = image.annotations if image else []
        self.setRowCount(0)
        self.setRowCount(len(self._annotations))
        for row, ann in enumerate(self._annotations):
            self._fill_row(row, ann)

    def load_data(self, annotations: list):
        """直接加载标注列表."""
        self._annotations = list(annotations)
        self.setRowCount(0)
        self.setRowCount(len(self._annotations))
        for row, ann in enumerate(self._annotations):
            self._fill_row(row, ann)

    def refresh(self):
        """刷新当前列表."""
        self.setRowCount(0)
        self.setRowCount(len(self._annotations))
        for row, ann in enumerate(self._annotations):
            self._fill_row(row, ann)

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------
    def _fill_row(self, row: int, ann: Annotation):
        """填充一行数据."""
        # 类别（显示审核后类别）
        cls_item = QTableWidgetItem(ann.class_name)
        cls_item.setData(Qt.ItemDataRole.UserRole, ann)
        self.setItem(row, 0, cls_item)

        # 置信度
        conf_text = f"{ann.confidence:.3f}" if ann.confidence > 0 else "-"
        self.setItem(row, 1, QTableWidgetItem(conf_text))

        # 审核状态
        review_item = QTableWidgetItem(ann.review_type.display_name)
        review_item.setForeground(QBrush(QColor(ann.review_type.color)))
        self.setItem(row, 2, review_item)

        # 来源
        source_name = {
            "model": "模型",
            "human": "人工",
            "modify": "修改",
        }.get(ann.source.value, ann.source.value)
        self.setItem(row, 3, QTableWidgetItem(source_name))

    def _on_cell_clicked(self, row: int, column: int):
        """点击行选中标注框."""
        if 0 <= row < len(self._annotations):
            self.annotation_selected.emit(self._annotations[row])

    # ------------------------------------------------------------------
    # 多选
    # ------------------------------------------------------------------
    def get_selected_annotations(self) -> list:
        """获取当前所有选中行对应的标注列表（按行号排序）."""
        rows = sorted({index.row() for index in self.selectedIndexes()})
        return [self._annotations[r] for r in rows if 0 <= r < len(self._annotations)]

    # ------------------------------------------------------------------
    # 右键菜单
    # ------------------------------------------------------------------
    def _show_context_menu(self, pos):
        """在指定位置显示右键菜单.

        多行选中时显示批量操作菜单，单行选中时显示原有单条菜单。
        """
        row = self.rowAt(pos.y())
        if row < 0 or row >= len(self._annotations):
            return

        # 确保右键点击的行处于选中状态
        if row not in {index.row() for index in self.selectedIndexes()}:
            self.clearSelection()
            self.selectRow(row)

        selected = self.get_selected_annotations()
        if not selected:
            return

        # 同步选中第一个标注（图片查看器高亮）
        ann = selected[0]
        self.annotation_selected.emit(ann)

        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu { font-size: 13px; }"
            "QMenu::item { padding: 6px 24px; }"
            "QMenu::item:selected { background-color: #3D7EFF; color: white; }"
        )

        review_entries = [
            (ReviewType.CORRECT, "正确"),
            (ReviewType.MISS, "漏报"),
            (ReviewType.WRONG_CLASS, "错报"),
            (ReviewType.FALSE_POSITIVE, "误报"),
            (ReviewType.OVERKILL, "过杀"),
            (ReviewType.UNREVIEW, "未审核"),
        ]

        if len(selected) > 1:
            # 批量操作
            for rt, name in review_entries:
                action = menu.addAction(f"批量审核 - {name}")
                action.triggered.connect(
                    lambda checked, t=rt: self.annotations_review_requested.emit(selected, t)
                )

            menu.addSeparator()

            # 批量修改类别子菜单
            class_menu = menu.addMenu("批量修改类别")
            try:
                from storage.config_manager import ConfigManager

                config = ConfigManager()
                defect_classes = config.get_defect_classes()
                for cls_name in defect_classes:
                    cls_action = class_menu.addAction(cls_name)
                    cls_action.triggered.connect(
                        lambda checked, c=cls_name: self.annotations_class_change_requested.emit(selected, c)
                    )
            except Exception as e:
                logger.debug("加载缺陷类别失败: %s", e)

            menu.addSeparator()
            delete_action = menu.addAction(f"批量删除（{len(selected)}）")
            delete_action.triggered.connect(
                lambda: self.annotations_delete_requested.emit(selected)
            )
        else:
            # 单条操作
            for rt, name in review_entries:
                action = menu.addAction(name)
                action.triggered.connect(
                    lambda checked, t=rt: self.annotation_review_requested.emit(ann, t)
                )

            menu.addSeparator()

            # 修改类别子菜单
            class_menu = menu.addMenu("修改类别")
            try:
                from storage.config_manager import ConfigManager

                config = ConfigManager()
                defect_classes = config.get_defect_classes()
                for cls_name in defect_classes:
                    cls_action = class_menu.addAction(cls_name)
                    cls_action.triggered.connect(
                        lambda checked, c=cls_name: self.annotation_class_change_requested.emit(ann, c)
                    )
            except Exception as e:
                logger.debug("加载缺陷类别失败: %s", e)

            menu.addSeparator()
            delete_action = menu.addAction("删除")
            delete_action.triggered.connect(
                lambda: self.annotation_delete_requested.emit(ann)
            )

        menu.exec(self.viewport().mapToGlobal(pos))


class DefectTable(QTableWidget):
    """缺陷实例列表."""

    defect_deleted = Signal(str, str)  # part_id, defect_id
    defect_selected = Signal(object)   # Defect

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setColumnCount(4)
        self.setHorizontalHeaderLabels(DEFECT_HEADERS)
        self.verticalHeader().setVisible(False)
        self.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setToolTip("绑定到同一缺陷实例的检测框在零件级统计时只计一次")

        self._defects = []
        self._part_id = ""

        self.cellClicked.connect(self._on_cell_clicked)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

    # ------------------------------------------------------------------
    # 加载
    # ------------------------------------------------------------------
    def load_defects(self, part_id: str, defects: list):
        """加载零件的缺陷实例列表."""
        self._part_id = part_id
        self._defects = list(defects)
        self.setRowCount(0)
        self.setRowCount(len(self._defects))

        for row, defect in enumerate(self._defects):
            # 编号（零件内顺序）
            index_item = QTableWidgetItem(f"#{defect.index or row + 1}")
            index_item.setData(Qt.ItemDataRole.UserRole, defect)
            self.setItem(row, 0, index_item)

            # 缺陷类别
            self.setItem(row, 1, QTableWidgetItem(defect.class_name))

            # 绑定相机数
            num = len(defect.annotation_bindings)
            binding_text = f"{num}" if num > 0 else "暂无"
            self.setItem(row, 2, QTableWidgetItem(binding_text))

            # 缺陷ID
            self.setItem(row, 3, QTableWidgetItem(defect.defect_id))

    def get_selected_defect(self):
        """获取当前选中的缺陷实例."""
        row = self.currentRow()
        if 0 <= row < len(self._defects):
            return self._defects[row]
        return None

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------
    def _on_cell_clicked(self, row: int, column: int):
        """点击行选中缺陷实例."""
        if 0 <= row < len(self._defects):
            self.defect_selected.emit(self._defects[row])

    def _show_context_menu(self, pos):
        """右键菜单（删除缺陷实例）."""
        row = self.rowAt(pos.y())
        if row < 0 or row >= len(self._defects):
            return
        defect = self._defects[row]
        self.selectRow(row)

        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu { font-size: 13px; }"
            "QMenu::item { padding: 6px 24px; }"
            "QMenu::item:selected { background-color: #3D7EFF; color: white; }"
        )
        info_action = menu.addAction(
            f"缺陷: #{defect.index or row + 1} {defect.class_name}\n"
            f"ID: {defect.defect_id}\n"
            f"绑定: {len(defect.annotation_bindings)} 个检测框"
        )
        info_action.setEnabled(False)

        menu.addSeparator()
        delete_action = menu.addAction("删除缺陷实例")
        delete_action.triggered.connect(
            lambda: self.defect_deleted.emit(self._part_id, defect.defect_id)
        )

        menu.exec(self.viewport().mapToGlobal(pos))


class ResultPanel(QWidget):
    """右侧结果面板（含标注结果 + 缺陷实例两个 Tab）.

    信号：
        annotation_selected: 选中标注
        annotation_review_requested: 右键审核（annotation, review_type）
        annotation_class_change_requested: 右键修改类别（annotation, class_name）
        annotation_delete_requested: 右键删除标注（annotation）
        defect_selected: 选中缺陷实例（Defect）
        defect_deleted: 删除缺陷实例（part_id, defect_id）
    """

    annotation_selected = Signal(object)
    annotation_review_requested = Signal(object, object)
    annotation_class_change_requested = Signal(object, str)
    annotation_delete_requested = Signal(object)
    annotations_review_requested = Signal(list, object)
    annotations_class_change_requested = Signal(list, str)
    annotations_delete_requested = Signal(list)
    defect_selected = Signal(object)
    defect_deleted = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(260)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Tab 容器
        self.tab_widget = QTabWidget()
        self.annotation_tab = AnnotationTable()
        self.defect_tab_widget = QWidget()
        defect_layout = QVBoxLayout(self.defect_tab_widget)
        defect_layout.setContentsMargins(4, 4, 4, 4)

        self.defect_table = DefectTable()
        defect_layout.addWidget(self.defect_table, 1)

        # 缺陷实例操作按钮
        btn_layout = QHBoxLayout()
        self.new_defect_btn = QPushButton("新建缺陷实例")
        self.new_defect_btn.setToolTip("将当前选中的检测框创建为新的缺陷实例")
        self.delete_defect_btn = QPushButton("删除")
        self.delete_defect_btn.setToolTip("删除选中的缺陷实例（解绑所有检测框）")
        btn_layout.addWidget(self.new_defect_btn)
        btn_layout.addWidget(self.delete_defect_btn)
        defect_layout.addLayout(btn_layout)

        self.tab_widget.addTab(self.annotation_tab, "标注结果")
        self.tab_widget.addTab(self.defect_tab_widget, "缺陷实例")
        layout.addWidget(self.tab_widget)

        # 信号转发
        self.annotation_tab.annotation_selected.connect(self.annotation_selected)
        self.annotation_tab.annotation_review_requested.connect(self.annotation_review_requested)
        self.annotation_tab.annotation_class_change_requested.connect(self.annotation_class_change_requested)
        self.annotation_tab.annotation_delete_requested.connect(self.annotation_delete_requested)
        self.annotation_tab.annotations_review_requested.connect(self.annotations_review_requested)
        self.annotation_tab.annotations_class_change_requested.connect(self.annotations_class_change_requested)
        self.annotation_tab.annotations_delete_requested.connect(self.annotations_delete_requested)
        self.defect_table.defect_selected.connect(self.defect_selected)
        self.defect_table.defect_deleted.connect(self.defect_deleted)
        self.delete_defect_btn.clicked.connect(self._on_delete_defect_clicked)

        self._part_id = ""
        self._defects = []

    # ------------------------------------------------------------------
    # 数据加载
    # ------------------------------------------------------------------
    def set_image(self, image: ImageData):
        """加载图片的标注列表."""
        self.annotation_tab.set_image(image)

    def load_annotations(self, annotations: list):
        """直接加载标注列表."""
        self.annotation_tab.load_data(annotations)

    def refresh_annotations(self):
        """刷新标注列表."""
        self.annotation_tab.refresh()

    def refresh_all(self, image=None):
        """刷新全部内容."""
        if image is not None:
            self.annotation_tab.set_image(image)
        self.annotation_tab.refresh()

    # 兼容旧接口
    def refresh(self):
        """刷新标注列表（兼容旧代码）."""
        self.annotation_tab.refresh()

    def set_image_and_defects(self, image, part_id="", defects=None):
        """同时刷新标注和缺陷实例列表."""
        if image is not None:
            self.annotation_tab.set_image(image)
        if part_id:
            self._part_id = part_id
        if defects is not None:
            self._defects = list(defects)
            self.defect_table.load_defects(self._part_id, self._defects)

    def set_part(self, part_id, defects):
        """设置当前零件的缺陷实例."""
        self._part_id = part_id
        self._defects = list(defects)
        self.defect_table.load_defects(part_id, defects)

    def selectRow(self, row):
        """选中指定行（兼容旧接口，转发到标注表格）."""
        self.annotation_tab.selectRow(row)
        self.annotation_tab.setCurrentCell(row, 0)

    # ------------------------------------------------------------------
    # 缺陷实例
    # ------------------------------------------------------------------
    def load_defects(self, part_id: str, defects: list):
        """加载缺陷实例列表."""
        self._part_id = part_id
        self._defects = list(defects)
        self.defect_table.load_defects(part_id, defects)

    def refresh_defects(self, part_id=None, defects=None):
        """刷新缺陷实例列表."""
        if part_id is not None:
            self._part_id = part_id
        if defects is not None:
            self._defects = list(defects)
        self.defect_table.load_defects(self._part_id, self._defects)

    def switch_to_annotations(self):
        """切换到标注结果 Tab."""
        self.tab_widget.setCurrentIndex(0)

    def switch_to_defects(self):
        """切换到缺陷实例 Tab."""
        self.tab_widget.setCurrentIndex(1)

    # ------------------------------------------------------------------
    # 按钮
    # ------------------------------------------------------------------
    def _on_delete_defect_clicked(self):
        """删除选中的缺陷实例."""
        defect = self.defect_table.get_selected_defect()
        if defect:
            self.defect_deleted.emit(self._part_id, defect.defect_id)
