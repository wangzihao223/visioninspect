"""缩略图面板控件.

显示当前零件号所有照片，带审核状态着色：
    灰色 = 未审核
    绿色 = 已审核
    红色 = 存在问题
点击缩略图快速切换图片。
"""

import os

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QListWidget,
    QListWidgetItem,
    QListView,
)

from utils.common import ReviewStatus
from utils.logger import get_logger

logger = get_logger(__name__)


class ThumbnailWidget(QListWidget):
    """缩略图面板."""

    thumbnail_clicked = Signal(object)  # ImageData

    STATUS_BORDER = {
        ReviewStatus.UNREVIEWED: "#999999",
        ReviewStatus.PARTIAL: "#FFCC00",
        ReviewStatus.FINISHED: "#00CC00",
        ReviewStatus.HAS_DEFECT: "#FF3333",
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setFlow(QListView.Flow.LeftToRight)
        self.setWrapping(True)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setIconSize(QSize(120, 90))
        self.setGridSize(QSize(150, 130))
        self.setSpacing(8)
        self.setUniformItemSizes(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setMovement(QListView.Movement.Static)
        self.itemClicked.connect(self._on_item_clicked)
        self.setMinimumHeight(140)

        self._image_items = {}
        self._current_images = []
        self._current_image_keys = ()
        self._thumbnail_cache = {}

    # ------------------------------------------------------------------
    # 加载
    # ------------------------------------------------------------------
    def load_images(self, images: list, current_image_id: str = ""):
        """加载并显示图片缩略图."""
        image_keys = tuple((img.image_id, img.file_path) for img in images)
        if image_keys == self._current_image_keys and self._image_items:
            self._current_images = list(images)
            for img in images:
                item = self._image_items.get(img.image_id)
                if item is None:
                    continue
                item.setData(Qt.ItemDataRole.UserRole, img)
                self._style_item(item, img)
            self.select_image(current_image_id)
            return

        self.clear()
        self._image_items = {}
        self._current_images = list(images)
        self._current_image_keys = image_keys

        for img in images:
            pixmap = self._load_thumbnail(img.file_path)
            item = QListWidgetItem()
            if not pixmap.isNull():
                item.setIcon(pixmap)
            item.setText(img.file_name)
            item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom)
            item.setData(Qt.ItemDataRole.UserRole, img)

            self._style_item(item, img)
            self.addItem(item)
            self._image_items[img.image_id] = item

        if current_image_id in self._image_items:
            self.select_image(current_image_id)

    def update_image_style(self, image_id: str, img=None):
        """刷新单个缩略图样式."""
        if image_id not in self._image_items:
            return
        item = self._image_items[image_id]
        if img is not None:
            self._style_item(item, img)

    def refresh_all(self, images: list, current_image_id: str):
        """整体刷新."""
        self.load_images(images, current_image_id)

    def select_image(self, image_id: str):
        """Select a thumbnail without rebuilding the thumbnail list."""
        item = self._image_items.get(image_id)
        if item is not None:
            self.setCurrentItem(item)
            self.scrollToItem(item, QAbstractItemView.ScrollHint.EnsureVisible)

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------
    def _load_thumbnail(self, file_path: str) -> QPixmap:
        """加载缩略图（按比例缩放）."""
        if not file_path or not os.path.exists(file_path):
            return QPixmap()
        try:
            stat = os.stat(file_path)
            cache_key = (file_path, stat.st_mtime_ns, stat.st_size)
        except OSError:
            return QPixmap()
        cached = self._thumbnail_cache.get(cache_key)
        if cached is not None:
            return cached

        pixmap = QPixmap(file_path)
        if pixmap.isNull():
            return QPixmap()
        thumbnail = pixmap.scaled(
            120,
            90,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._thumbnail_cache[cache_key] = thumbnail
        return thumbnail

    def _style_item(self, item: QListWidgetItem, img):
        """设置缩略图状态颜色."""
        status = img.get_review_status()
        color = self.STATUS_BORDER.get(status, "#999999")
        item.setForeground(QBrush(QColor(color)))
        item.setToolTip(f"{img.file_name}\n状态: {status.value}")

    def _on_item_clicked(self, item: QListWidgetItem):
        """点击缩略图."""
        img = item.data(Qt.ItemDataRole.UserRole)
        if img is not None:
            self.thumbnail_clicked.emit(img)
