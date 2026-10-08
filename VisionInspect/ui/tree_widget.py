"""左侧零件树控件.

树形结构显示：
    零件号
        └── 图片列表
状态着色：
    零件：灰色=未审核/无图，黄色=部分审核，绿色=审核完成，红色=存在缺陷
    图片：灰色=未审核，绿色=已审核，红色=存在问题
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import QMenu, QTreeWidget, QTreeWidgetItem

from data.project_data import PartData, ProjectData
from utils.common import ReviewStatus
from utils.logger import get_logger

logger = get_logger(__name__)

STATUS_COLORS = {
    ReviewStatus.UNREVIEWED: "#999999",
    ReviewStatus.PARTIAL: "#FFCC00",
    ReviewStatus.FINISHED: "#00CC00",
    ReviewStatus.HAS_DEFECT: "#FF3333",
}

PART_STATUS_NAMES = {
    ReviewStatus.UNREVIEWED: "未审核",
    ReviewStatus.PARTIAL: "部分审核",
    ReviewStatus.FINISHED: "审核完成",
    ReviewStatus.HAS_DEFECT: "存在缺陷",
}


class PartTreeWidget(QTreeWidget):
    """零件树控件."""

    part_selected = Signal(str)          # 零件号
    image_selected = Signal(str, str)    # 零件号, 图片id
    image_mark_review_requested = Signal(str, str)   # 零件号, 图片id（标记已审核）
    image_clear_review_requested = Signal(str, str)  # 零件号, 图片id（清空审核）

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHeaderLabel("数据导航")
        self.setColumnCount(1)
        self.setMinimumWidth(220)
        self.itemClicked.connect(self._on_item_clicked)
        self._part_items = {}
        self._image_items = {}
        self._loading = False
        # 保存当前项目与选中状态，用于搜索过滤后保留/恢复
        self._project = None
        self._current_part_id = ""
        self._current_image_id = ""
        self._search_keyword = ""

    # ------------------------------------------------------------------
    # 加载
    # ------------------------------------------------------------------
    def load_project(self, project: ProjectData, current_part_id: str = "", current_image_id: str = ""):
        """加载项目零件树."""
        self._loading = True
        self._project = project
        self._current_part_id = current_part_id
        self._current_image_id = current_image_id
        self.clear()
        self._part_items = {}
        self._image_items = {}

        for part in project.parts:
            part_item = QTreeWidgetItem([part.part_id])
            self._style_part(part_item, part)
            self.addTopLevelItem(part_item)
            self._part_items[part.part_id] = part_item

            for img in part.images:
                img_item = QTreeWidgetItem([img.file_name])
                self._style_image(img_item, img)
                part_item.addChild(img_item)
                self._image_items[(part.part_id, img.image_id)] = img_item

        # 展开并选中当前
        if current_part_id in self._part_items:
            part_item = self._part_items[current_part_id]
            part_item.setExpanded(True)
            self.setCurrentItem(part_item)
            if (current_part_id, current_image_id) in self._image_items:
                img_item = self._image_items[(current_part_id, current_image_id)]
                self.setCurrentItem(img_item)

        self._loading = False

    # ------------------------------------------------------------------
    # 搜索过滤
    # ------------------------------------------------------------------
    def filter(self, keyword: str):
        """按关键字过滤树节点（目录名/文件名模糊匹配）.

        关键字为空时恢复原始完整树；否则仅显示匹配的目录与图片节点。
        匹配规则：
            - 目录名（零件号）包含关键字 → 显示该目录及其全部图片
            - 文件名包含关键字 → 显示该目录及匹配的图片节点
        """
        if self._project is None:
            return
        self._search_keyword = (keyword or "").strip()
        if not self._search_keyword:
            # 清除搜索 → 恢复原始完整树
            self.load_project(self._project, self._current_part_id, self._current_image_id)
            return

        keyword_lower = self._search_keyword.lower()

        self._loading = True
        self.clear()
        self._part_items = {}
        self._image_items = {}

        for part in self._project.parts:
            part_name = part.part_id or ""
            if keyword_lower in part_name.lower():
                # 目录名匹配 → 显示该目录及其全部图片
                matched_images = list(part.images)
            else:
                # 文件名匹配 → 仅显示匹配的图片节点
                matched_images = [
                    img for img in part.images
                    if keyword_lower in (img.file_name or "").lower()
                ]
            if not matched_images:
                continue

            part_item = QTreeWidgetItem([part_name])
            self._style_part(part_item, part)
            self.addTopLevelItem(part_item)
            self._part_items[part.part_id] = part_item

            for img in matched_images:
                img_item = QTreeWidgetItem([img.file_name])
                self._style_image(img_item, img)
                part_item.addChild(img_item)
                self._image_items[(part.part_id, img.image_id)] = img_item

            # 搜索结果显示时自动展开
            part_item.setExpanded(True)

        # 保持当前选中（若其在过滤结果中）
        if (self._current_part_id, self._current_image_id) in self._image_items:
            self.setCurrentItem(self._image_items[(self._current_part_id, self._current_image_id)])
        elif self._current_part_id in self._part_items:
            self.setCurrentItem(self._part_items[self._current_part_id])

        self._loading = False

    # ------------------------------------------------------------------
    # 刷新
    # ------------------------------------------------------------------
    def update_part_status(self, part: PartData):
        """更新零件节点颜色."""
        if part.part_id not in self._part_items:
            return
        self._style_part(self._part_items[part.part_id], part)

    def update_image_status(self, part_id: str, image_id: str, image=None):
        """更新图片节点颜色."""
        key = (part_id, image_id)
        if key not in self._image_items:
            return
        item = self._image_items[key]
        if image is not None:
            self._style_image(item, image)

    def refresh_all(self, project: ProjectData, current_part_id: str, current_image_id: str):
        """整体刷新（保留展开状态）."""
        expanded_parts = set()
        for pid, item in self._part_items.items():
            if item.isExpanded():
                expanded_parts.add(pid)

        self.load_project(project, current_part_id, current_image_id)

        for pid in expanded_parts:
            if pid in self._part_items:
                self._part_items[pid].setExpanded(True)

        # 若搜索框仍有关键字，重新应用过滤
        if self._search_keyword:
            self.filter(self._search_keyword)

    # ------------------------------------------------------------------
    # 样式
    # ------------------------------------------------------------------
    def _style_part(self, item: QTreeWidgetItem, part: PartData):
        """设置零件节点颜色."""
        status = part.get_part_status()
        color = STATUS_COLORS.get(status, "#999999")
        item.setForeground(0, QBrush(QColor(color)))
        item.setToolTip(0, f"零件号: {part.part_id}\n状态: {PART_STATUS_NAMES.get(status, '未知')}")

    def _style_image(self, item: QTreeWidgetItem, img):
        """设置图片节点颜色."""
        status = img.get_review_status()
        color = STATUS_COLORS.get(status, "#999999")
        item.setForeground(0, QBrush(QColor(color)))
        item.setToolTip(0, f"{img.file_name}\n状态: {status.value}")

    # ------------------------------------------------------------------
    # 事件
    # ------------------------------------------------------------------
    def _on_item_clicked(self, item: QTreeWidgetItem, column: int):
        """点击处理."""
        if self._loading:
            return
        item = self.currentItem()
        if item is None:
            return

        # 判断是零件还是图片
        parent = item.parent()
        if parent is None:
            # 零件节点
            part_id = item.text(0)
            self._current_part_id = part_id
            self.part_selected.emit(part_id)
        else:
            # 图片节点
            part_id = parent.text(0)
            image_id = f"{part_id}/{item.text(0)}"
            self._current_part_id = part_id
            self._current_image_id = image_id
            self.part_selected.emit(part_id)
            self.image_selected.emit(part_id, image_id)

    def select_image(self, part_id: str, image_id: str):
        """程序化选中图片节点."""
        key = (part_id, image_id)
        if key not in self._image_items:
            return
        item = self._image_items[key]
        self.setCurrentItem(item)
        self.scrollToItem(item)
        self._current_part_id = part_id
        self._current_image_id = image_id

    # ------------------------------------------------------------------
    # 右键菜单
    # ------------------------------------------------------------------
    def contextMenuEvent(self, event):
        """右键菜单.

        空白区域：全部展开/全部折叠
        图片节点：标记已审核/清空审核
        零件节点：不弹菜单
        """
        item = self.itemAt(event.pos())
        if item is None:
            # 空白区域：全部展开/全部折叠
            menu = QMenu(self)
            expand_action = menu.addAction("全部展开")
            collapse_action = menu.addAction("全部折叠")
            action = menu.exec(event.globalPos())

            if action == expand_action:
                self.expandAll()
            elif action == collapse_action:
                self.collapseAll()
            return

        # 图片节点：弹出审核操作菜单
        if item.parent() is not None:
            part_id = item.parent().text(0)
            image_id = f"{part_id}/{item.text(0)}"
            menu = QMenu(self)
            mark_action = menu.addAction("标记已审核")
            clear_action = menu.addAction("清空审核")
            action = menu.exec(event.globalPos())

            if action == mark_action:
                self.image_mark_review_requested.emit(part_id, image_id)
            elif action == clear_action:
                self.image_clear_review_requested.emit(part_id, image_id)
            return

        # 零件节点：保持原交互，不弹菜单
