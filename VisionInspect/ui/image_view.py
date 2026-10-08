"""核心图片显示控件.

基于 QGraphicsView 实现：
    - 高清图片显示
    - 鼠标滚轮缩放
    - 鼠标拖动平移
    - 检测框绘制（模型框 + 人工框）
    - 鼠标框选新增人工检测框
    - 标注框选中
"""

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QPainter,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QGraphicsItem,
    QGraphicsPixmapItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QMenu,
)

from data.image_data import Annotation, ImageData
from utils.common import ReviewType
from utils.logger import get_logger

logger = get_logger(__name__)


class AnnotationRectItem(QGraphicsRectItem):
    """可交互的检测框图形项.

    检测框上方显示类别名称标签。
    """

    def __init__(self, annotation: Annotation, rect: QRectF, parent=None):
        super().__init__(rect, parent)
        self.annotation = annotation
        self.is_selected = False
        # 缺陷实例编号（绑定后显示 ① ② ③，未绑定为 None）
        self.defect_no = None
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsFocusable, True)
        self.setAcceptHoverEvents(True)

        # 类别标签（背景 + 文本）
        self._label_bg = QGraphicsRectItem(self)
        self._label_bg.setPen(Qt.PenStyle.NoPen)
        self._label_text = QGraphicsSimpleTextItem(self)
        self._label_text.setFont(QFont("微软雅黑", 7))
        self._label_text.setBrush(QBrush(QColor("white")))

        self._update_style()

    def set_selected(self, selected: bool):
        """设置选中状态."""
        self.is_selected = selected
        self._update_style()

    def _update_style(self):
        """根据审核类型更新样式."""
        color = QColor(self.annotation.review_type.color)
        pen = QPen(color, 3 if self.is_selected else 1.5)
        if self.defect_no:
            # 已绑定缺陷实例：边框加粗强调
            pen.setWidth(3)
        if self.annotation.source.value == "human":
            pen.setStyle(Qt.PenStyle.DashLine)
        self.setPen(pen)

        # 半透明填充
        fill = QColor(color)
        fill.setAlpha(30)
        self.setBrush(QBrush(fill))

        # 更新类别标签
        self._update_label_style()

    def _update_label_style(self):
        """更新类别标签文本与位置."""
        # 显示审核后的类别（review_class），否则显示原始类别
        base_text = self.annotation.review_class or self.annotation.class_name or "未命名"
        if self.defect_no:
            # 已绑定：标签前加编号 ① ② ③
            circle_nums = "①②③④⑤⑥⑦⑧⑨⑩"
            no_str = circle_nums[self.defect_no - 1] if 1 <= self.defect_no <= 10 else f"#{self.defect_no}"
            text = f"{no_str} {base_text}"
        else:
            text = base_text
        self._label_text.setText(text)

        # 标签背景（半透明深色，保证可读性）
        text_rect = self._label_text.boundingRect()
        bg_w = text_rect.width() + 8
        bg_h = text_rect.height() + 4
        bg_rect = QRectF(0, 0, bg_w, bg_h)
        dark_bg = QColor(30, 30, 30)
        dark_bg.setAlpha(170)
        self._label_bg.setBrush(QBrush(dark_bg))
        self._label_bg.setRect(bg_rect)

        # 位置：检测框正上方（如超出图片则显示在框内顶部）
        bx, by = self.rect().left(), self.rect().top()
        lx = bx + (self.rect().width() - bg_w) / 2
        if lx < 0:
            lx = bx
        ly = by - bg_h - 2
        if ly < 0:
            ly = by
        self._label_bg.setPos(lx, ly)
        self._label_text.setPos(lx + 4, ly + 2)

    def update_annotation_style(self):
        """外部调用：刷新样式（审核类型变化后）."""
        self._update_style()
        self.update()


class ImageViewer(QGraphicsView):
    """图片显示控件.

    信号：
        annotation_clicked: 点击标注框（Annotation）
        box_drawn: 框选完成（[x1,y1,x2,y2] 图片坐标）
        image_clicked: 点击空白区域（场景坐标）
        review_requested: 右键菜单选择审核类型（annotation, review_type）
        delete_requested: 右键菜单删除标注（annotation）
    """

    annotation_clicked = Signal(object)
    box_drawn = Signal(list)
    image_clicked = Signal(float, float)
    review_requested = Signal(object, object)
    class_change_requested = Signal(object, str)
    delete_requested = Signal(object)

    SCALE_STEP = 1.25
    MIN_SCALE = 0.01
    MAX_SCALE = 100.0

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)

        self.setRenderHints(
            QPainter.RenderHint.Antialiasing
            | QPainter.RenderHint.SmoothPixmapTransform
        )
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setMouseTracking(True)

        self._pixmap_item = None
        self._annotation_items = {}
        self._current_image = None

        # 框选状态
        self._is_drawing = False
        self._draw_start = QPointF()
        self._draw_rect_item = None

        # 选中标注
        self.selected_annotation = None
        self._start_pos = None

        # 平移状态（中键拖拽 或 空格+左键拖拽）
        self._panning = False
        self._pan_start = QPointF()
        self._pan_scroll_start = None
        self._space_pressed = False
        self.setCursor(Qt.CursorShape.ArrowCursor)

        # 项目引用（用于查询缺陷实例编号）
        self._project = None  # type: ignore

    # ------------------------------------------------------------------
    # 图片显示
    # ------------------------------------------------------------------
    def show_image(self, image: ImageData):
        """显示图片及其标注框.

        Args:
            image: ImageData（file_path 必须存在）
        """
        self._scene.clear()
        self._annotation_items = {}
        self.selected_annotation = None
        self._current_image = image
        self._pixmap_item = None
        self._draw_rect_item = None
        self._is_drawing = False

        pixmap = QPixmap(image.file_path)
        if pixmap.isNull():
            logger.error("无法加载图片: %s", image.file_path)
            return

        self._pixmap_item = QGraphicsPixmapItem(pixmap)
        self._pixmap_item.setZValue(0)
        self._scene.addItem(self._pixmap_item)

        # 场景范围
        self._scene.setSceneRect(0, 0, pixmap.width(), pixmap.height())

        # 构建缺陷实例编号映射（用于绑定框显示编号）
        defect_map = self._build_defect_map()

        # 绘制标注框
        for ann in image.annotations:
            item = self._add_annotation_item(ann)
            # 设置绑定编号
            if ann.defect_id and ann.defect_id in defect_map:
                item.defect_no = defect_map[ann.defect_id]
                item.update_annotation_style()

        # 自适应视图
        self.fitInView(self._scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def show_pixmap(self, pixmap: QPixmap):
        """直接显示 QPixmap（无标注）."""
        self._scene.clear()
        self._annotation_items = {}
        self.selected_annotation = None
        self._current_image = None

        self._pixmap_item = QGraphicsPixmapItem(pixmap)
        self._scene.addItem(self._pixmap_item)
        self._scene.setSceneRect(0, 0, pixmap.width(), pixmap.height())
        self.fitInView(self._scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def clear_view(self):
        """清空显示."""
        self._scene.clear()
        self._annotation_items = {}
        self.selected_annotation = None
        self._current_image = None
        self._pixmap_item = None
        self._draw_rect_item = None
        self._is_drawing = False

    # ------------------------------------------------------------------
    # 标注框管理
    # ------------------------------------------------------------------
    def _add_annotation_item(self, annotation: Annotation) -> AnnotationRectItem:
        """添加标注框图形项."""
        x1, y1, x2, y2 = annotation.bbox
        rect = QRectF(x1, y1, x2 - x1, y2 - y1)
        item = AnnotationRectItem(annotation, rect)
        item.setZValue(1)
        item.mousePressEvent = self._make_ann_mouse_handler(item)
        self._scene.addItem(item)
        self._annotation_items[annotation.id] = item
        return item

    def _make_ann_mouse_handler(self, item: AnnotationRectItem):
        """为标注框生成鼠标事件处理器.

        左键：选中并触发 annotation_clicked
        右键：直接在标注框上弹出审核菜单
        """

        def handler(event):
            if event.button() == Qt.MouseButton.LeftButton:
                self._select_annotation(item.annotation)
                self.annotation_clicked.emit(item.annotation)
                event.accept()
            elif event.button() == Qt.MouseButton.RightButton:
                # 在标注框上直接弹出右键审核菜单
                self._select_annotation(item.annotation)
                self._show_context_menu(item.annotation, event.globalPosition().toPoint())
                event.accept()

        return handler

    def refresh_annotations(self):
        """刷新全部标注框（审核类型变化后调用）."""
        if not self._current_image:
            return
        # 清空旧框
        for item in self._annotation_items.values():
            self._scene.removeItem(item)
        self._annotation_items = {}

        # 设置缺陷实例编号映射（用于标注框显示编号）
        defect_map = self._build_defect_map()

        # 重新添加
        for ann in self._current_image.annotations:
            item = self._add_annotation_item(ann)
            # 设置绑定编号
            if ann.defect_id and ann.defect_id in defect_map:
                item.defect_no = defect_map[ann.defect_id]
                item.update_annotation_style()

        # 恢复选中
        if self.selected_annotation:
            item = self._annotation_items.get(self.selected_annotation.id)
            if item:
                self._select_annotation(self.selected_annotation)

    def _build_defect_map(self) -> dict:
        """构建当前零件缺陷 id → 编号 的映射用于主图显示.

        Returns:
            {defect_id: index}
        """
        from core.defect_manager import DefectManager

        defect_map = {}
        if not self._current_image:
            return defect_map
        cm = DefectManager()
        project = getattr(self, "_project", None)
        if project:
            part = project.get_part(self._current_image.part_id)
            if part:
                for i, defect in enumerate(part.defects, 1):
                    # 优先使用手动设置的 index，否则用顺序号
                    defect_num = defect.index if defect.index else i
                    defect_map[defect.defect_id] = defect_num
        return defect_map

    def update_annotation_style(self, annotation: Annotation):
        """更新单个标注框样式."""
        item = self._annotation_items.get(annotation.id)
        if item:
            item.update_annotation_style()

    def set_selected_annotation(self, annotation):
        """设置选中的标注."""
        self._select_annotation(annotation)

    def focus_annotation(self, annotation, min_context_ratio: float = 0.12) -> bool:
        """Select, center, and zoom around an annotation."""
        self._select_annotation(annotation)
        item = self._annotation_items.get(annotation.id) if annotation else None
        if item is None or self._pixmap_item is None:
            return False

        image_rect = self._pixmap_item.boundingRect()
        rect = item.rect()
        min_w = max(image_rect.width() * min_context_ratio, rect.width() * 8, 80)
        min_h = max(image_rect.height() * min_context_ratio, rect.height() * 8, 80)
        focus_w = max(rect.width(), min_w)
        focus_h = max(rect.height(), min_h)
        center = rect.center()
        focus_rect = QRectF(
            center.x() - focus_w / 2,
            center.y() - focus_h / 2,
            focus_w,
            focus_h,
        ).intersected(image_rect)

        if focus_rect.isValid():
            self.fitInView(focus_rect, Qt.AspectRatioMode.KeepAspectRatio)
            self.centerOn(center)
            return True
        return False

    def _select_annotation(self, annotation):
        """内部选中逻辑."""
        # 清除旧选中
        if self.selected_annotation:
            old_item = self._annotation_items.get(self.selected_annotation.id)
            if old_item:
                old_item.set_selected(False)
        self.selected_annotation = annotation
        if annotation:
            item = self._annotation_items.get(annotation.id)
            if item:
                item.set_selected(True)

    # ------------------------------------------------------------------
    # 缩放/平移
    # ------------------------------------------------------------------
    def zoom_in(self):
        """放大."""
        self._zoom(self.SCALE_STEP)

    def zoom_out(self):
        """缩小."""
        self._zoom(1.0 / self.SCALE_STEP)

    def reset_view(self):
        """重置视图."""
        if self._scene.sceneRect().isValid():
            self.fitInView(self._scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def _zoom(self, factor: float):
        """按因子缩放."""
        current_scale = self.transform().m11()
        new_scale = current_scale * factor
        if self.MIN_SCALE <= new_scale <= self.MAX_SCALE:
            self.scale(factor, factor)

    # ------------------------------------------------------------------
    # 鼠标事件
    # ------------------------------------------------------------------
    def wheelEvent(self, event):
        """滚轮缩放."""
        if event.angleDelta().y() > 0:
            self.zoom_in()
        else:
            self.zoom_out()
        event.accept()

    def mousePressEvent(self, event):
        """鼠标按下."""
        if event.button() == Qt.MouseButton.LeftButton:
            # 空格键按住 + 左键 = 平移模式
            if self._space_pressed:
                self._start_pan(event.position())
                event.accept()
                return

            scene_pos = self.mapToScene(event.position().toPoint())
            # 检查是否点击了检测框
            item = self._item_at(scene_pos)
            if item is not None:
                self._select_annotation(item.annotation)
                self.annotation_clicked.emit(item.annotation)
                event.accept()
                return

            # 空白区域：开始框选（人工新增检测框）
            self._is_drawing = True
            self._draw_start = scene_pos
            self._draw_rect_item = QGraphicsRectItem(QRectF(scene_pos, scene_pos))
            self._draw_rect_item.setPen(
                QPen(QColor("#00AAFF"), 2, Qt.PenStyle.DashLine)
            )
            self._draw_rect_item.setZValue(10)
            self._scene.addItem(self._draw_rect_item)
            event.accept()
            return

        if event.button() == Qt.MouseButton.RightButton:
            # 右键：弹出审核菜单
            scene_pos = self.mapToScene(event.position().toPoint())
            item = self._item_at(scene_pos)
            annotation = item.annotation if item else None
            if annotation is not None:
                self._select_annotation(annotation)
                self._show_context_menu(annotation, event.globalPosition().toPoint())
            else:
                # 空白区域右键：显示通用菜单（新增框类别选择等在 MainWindow 统一处理）
                self._show_blank_context_menu(event.globalPosition().toPoint())
            event.accept()
            return

        if event.button() == Qt.MouseButton.MiddleButton:
            # 中键拖拽平移（手动实现，ScrollHandDrag 不响应中键）
            self._start_pan(event.position())
            event.accept()
            return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        """鼠标移动."""
        # 拖拽平移
        if self._panning:
            self._move_pan(event.position())
            event.accept()
            return

        if self._is_drawing and self._draw_rect_item:
            scene_pos = self.mapToScene(event.position().toPoint())
            rect = QRectF(self._draw_start, scene_pos).normalized()
            # 限制在图片范围内
            if self._pixmap_item:
                img_rect = self._pixmap_item.boundingRect()
                rect = rect.intersected(img_rect)
            self._draw_rect_item.setRect(rect)
            event.accept()
            return

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        """鼠标释放."""
        # 结束平移
        if self._panning:
            self._stop_pan()
            event.accept()
            return

        if event.button() == Qt.MouseButton.LeftButton and self._is_drawing:
            self._is_drawing = False
            if self._draw_rect_item:
                rect = self._draw_rect_item.rect()
                self._scene.removeItem(self._draw_rect_item)
                self._draw_rect_item = None

                # 只有足够大的框才算有效
                if rect.width() >= 5 and rect.height() >= 5:
                    bbox = [rect.left(), rect.top(), rect.right(), rect.bottom()]
                    self.box_drawn.emit(bbox)
                else:
                    # 视为点击空白
                    self.image_clicked.emit(rect.center().x(), rect.center().y())
            event.accept()
            return

        super().mouseReleaseEvent(event)

    # ------------------------------------------------------------------
    # 键盘事件（空格键平移）
    # ------------------------------------------------------------------
    def keyPressEvent(self, event):
        """键盘按下."""
        if event.key() == Qt.Key.Key_Space:
            self._space_pressed = True
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            event.accept()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        """键盘释放."""
        if event.key() == Qt.Key.Key_Space:
            self._space_pressed = False
            if not self._panning:
                self.setCursor(Qt.CursorShape.ArrowCursor)
            event.accept()
            return
        super().keyReleaseEvent(event)

    # ------------------------------------------------------------------
    # 平移实现（中键拖拽 或 空格+左键拖拽）
    # ------------------------------------------------------------------
    def _start_pan(self, pos):
        """开始平移."""
        self._panning = True
        self._pan_start = pos
        self._pan_scroll_start = (
            self.horizontalScrollBar().value(),
            self.verticalScrollBar().value(),
        )
        self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def _move_pan(self, pos):
        """平移过程中移动."""
        if not self._panning or self._pan_scroll_start is None:
            return
        dx = pos.x() - self._pan_start.x()
        dy = pos.y() - self._pan_start.y()
        self.horizontalScrollBar().setValue(self._pan_scroll_start[0] - dx)
        self.verticalScrollBar().setValue(self._pan_scroll_start[1] - dy)

    def _stop_pan(self):
        """结束平移."""
        self._panning = False
        self._pan_scroll_start = None
        if self._space_pressed:
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)

    # ------------------------------------------------------------------
    # 右键菜单
    # ------------------------------------------------------------------
    def _show_context_menu(self, annotation: Annotation, global_pos):
        """显示标注审核右键菜单.

        对应需求文档 4.7 方式一：
            正确 / 漏报 / 错报 / 误报 / 过杀 / 删除
        """
        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu { font-size: 13px; }"
            "QMenu::item { padding: 6px 24px; }"
            "QMenu::item:selected { background-color: #3D7EFF; color: white; }"
        )

        # 快捷键数字对应：1正确 2漏报 3错报 4误报 5过杀 0未审核
        shortcuts = {
            ReviewType.CORRECT: "1",
            ReviewType.MISS: "2",
            ReviewType.WRONG_CLASS: "3",
            ReviewType.FALSE_POSITIVE: "4",
            ReviewType.OVERKILL: "5",
            ReviewType.UNREVIEW: "0",
        }
        review_entries = [
            (ReviewType.CORRECT, "正确"),
            (ReviewType.MISS, "漏报"),
            (ReviewType.WRONG_CLASS, "错报"),
            (ReviewType.FALSE_POSITIVE, "误报"),
            (ReviewType.OVERKILL, "过杀"),
            (ReviewType.UNREVIEW, "未审核"),
        ]
        for rt, name in review_entries:
            key_hint = shortcuts.get(rt, "")
            label = f"{name}    {key_hint}" if key_hint else name
            action = menu.addAction(label)
            action.triggered.connect(lambda checked, t=rt: self.review_requested.emit(annotation, t))

        menu.addSeparator()

        # 修改类别子菜单（与右侧表单右键菜单一致）
        class_menu = menu.addMenu("修改类别")
        try:
            from storage.config_manager import ConfigManager

            config = ConfigManager()
            defect_classes = config.get_defect_classes()
            for cls_name in defect_classes:
                cls_action = class_menu.addAction(cls_name)
                cls_action.triggered.connect(
                    lambda checked, c=cls_name: self.class_change_requested.emit(annotation, c)
                )
        except Exception as e:
            logger.debug("加载缺陷类别失败: %s", e)

        menu.addSeparator()
        delete_action = menu.addAction("删除")
        delete_action.triggered.connect(
            lambda: self.delete_requested.emit(annotation)
        )

        menu.exec(global_pos)

    def _show_blank_context_menu(self, global_pos):
        """空白区域右键菜单."""
        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu { font-size: 13px; }"
            "QMenu::item { padding: 6px 24px; }"
            "QMenu::item:selected { background-color: #3D7EFF; color: white; }"
        )
        action = menu.addAction("在空白处框选可新增人工检测框")
        action.setEnabled(False)
        menu.exec(global_pos)

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------
    def _item_at(self, pos: QPointF):
        """获取指定场景坐标最上层的标注框."""
        items = self._scene.items(pos)
        for item in items:
            if isinstance(item, AnnotationRectItem):
                return item
        return None

    def fit_to_image(self):
        """适应图片大小."""
        self.fitInView(self._scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
