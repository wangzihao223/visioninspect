"""状态栏控件.

显示：
    当前：零件号 / 图片名
    审核：已审核数量 / 总数量 / 百分比
    各审核状态计数
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QStatusBar

from data.project_data import ProjectData
from utils.logger import get_logger

logger = get_logger(__name__)


class StatusBarWidget(QStatusBar):
    """状态栏控件."""

    def __init__(self, parent=None):
        super().__init__(parent)

        self.part_label = QLabel("零件: -")
        self.image_label = QLabel("图片: -")
        self.progress_label = QLabel("审核: 0/0 (0%)")
        self.status_label = QLabel("未审核: 0  存在问题: 0")

        for label in (self.part_label, self.image_label, self.progress_label, self.status_label):
            label.setStyleSheet("font-size: 12px;")

        self.addWidget(self.part_label)
        self.addWidget(self.image_label)
        self.addWidget(self.progress_label)
        self.addWidget(self.status_label)
        self.addPermanentWidget(QLabel(""))

    # ------------------------------------------------------------------
    # 更新
    # ------------------------------------------------------------------
    def update_progress(self, project: ProjectData):
        """更新审核进度."""
        if not project:
            self.reset()
            return
        total = project.get_total_images()
        reviewed = project.get_reviewed_images()
        progress = project.get_progress()
        unreviewed = project.get_unreviewed_images()
        problem = project.get_problem_images()

        self.progress_label.setText(f"审核: {reviewed}/{total} ({progress:.1f}%)")
        self.status_label.setText(f"未审核: {unreviewed}  存在问题: {problem}")

    def update_current(self, part_id: str = "", image_name: str = ""):
        """更新当前选中信息."""
        self.part_label.setText(f"零件: {part_id or '-'}")
        self.image_label.setText(f"图片: {image_name or '-'}")

    def reset(self):
        """重置状态栏."""
        self.part_label.setText("零件: -")
        self.image_label.setText("图片: -")
        self.progress_label.setText("审核: 0/0 (0%)")
        self.status_label.setText("未审核: 0  存在问题: 0")
