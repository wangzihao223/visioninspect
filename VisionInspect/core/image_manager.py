"""图片管理模块.

负责图片切换、当前图片状态管理。
对应快捷键：A 上一张 / D 下一张 / F 跳转下一张未审核图片。
"""

from typing import Optional

from data.image_data import ImageData
from data.project_data import ProjectData
from utils.logger import get_logger

logger = get_logger(__name__)


class ImageManager:
    """图片管理器.

    管理当前选中的零件与图片。

    Attributes:
        project: 当前项目
    """

    def __init__(self, project: Optional[ProjectData] = None):
        self.project = project
        self.current_part = None
        self.current_image = None
        self.image_index = -1

    # ------------------------------------------------------------------
    # 初始化
    # ------------------------------------------------------------------
    def set_project(self, project: ProjectData):
        """绑定项目并重置状态."""
        self.project = project
        self._sync_current()

    def _sync_current(self):
        """根据项目的 current_* 同步内部状态."""
        if not self.project:
            self.current_part = None
            self.current_image = None
            self.image_index = -1
            return

        self.current_part = self.project.get_current_part()
        self.current_image = self.project.get_current_image()

        if self.current_part and self.current_image:
            images = self.current_part.images
            for i, img in enumerate(images):
                if img.image_id == self.current_image.image_id:
                    self.image_index = i
                    break
        else:
            self.image_index = -1

    # ------------------------------------------------------------------
    # 加载/切换
    # ------------------------------------------------------------------
    def load_image(self, part_id: str, image_id: str):
        """加载指定零件下的指定图片."""
        if not self.project:
            return None
        part = self.project.get_part(part_id)
        if not part:
            return None
        img = part.get_image(image_id)
        if not img:
            return None

        self.project.current_part_id = part_id
        self.project.current_image_id = image_id
        self._sync_current()
        return img

    def select_image(self, image: Optional[ImageData]):
        """按 ImageData 对象选择图片."""
        if not image:
            return None
        return self.load_image(image.part_id, image.image_id)

    def next_image(self):
        """下一张图片（快捷键 D）."""
        return self._move_image(1)

    def previous_image(self):
        """上一张图片（快捷键 A）."""
        return self._move_image(-1)

    def next_unreview_image(self):
        """跳转下一张未审核完成的图片（快捷键 F）.

        从当前图片之后开始查找；若当前零件无未审核图片，
        则继续查找后续零件。
        """
        if not self.project:
            return None

        images = [image for part in self.project.parts for image in part.images]
        current_index = next((index for index, image in enumerate(images) if image is self.current_image), -1)
        for offset in range(1, len(images) + 1):
            image = images[(current_index + offset) % len(images)]
            if not image.is_review_finished():
                return self.load_image(image.part_id, image.image_id)

        return None

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------
    def _move_image(self, delta: int):
        """按偏移量移动图片（全局顺序，跨零件循环切换）.

        与左侧数据导航树的展示顺序一致：按 project.parts 顺序
        依次展开各零件的图片，首尾相接循环切换（A 到上一张，
        上一张可能是上一个零件的最后一张；D 到下一张，
        下一张可能是下一个零件的第一张）。
        """
        if not self.project or not self.current_image:
            return None

        # 构建全局图片列表（对齐数据导航树顺序）
        all_images = []
        for part in self.project.parts:
            all_images.extend(part.images)
        if not all_images:
            return None

        # 定位当前图片在全局列表中的索引
        current_id = self.current_image.image_id
        total = len(all_images)
        for idx, img in enumerate(all_images):
            if img.image_id == current_id:
                new_index = (idx + delta) % total
                target = all_images[new_index]
                return self.load_image(target.part_id, target.image_id)

        # 当前图片不在列表中（异常情况），回退到全局第一张
        return self.load_image(all_images[0].part_id, all_images[0].image_id)

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------
    def get_previous_image(self):
        """获取上一张图片对象（不切换）."""
        if not self.current_part or self.image_index < 0:
            return None
        images = self.current_part.images
        if len(images) <= 1:
            return None
        idx = (self.image_index - 1) % len(images)
        return images[idx]

    def get_next_image(self):
        """获取下一张图片对象（不切换）."""
        if not self.current_part or self.image_index < 0:
            return None
        images = self.current_part.images
        if len(images) <= 1:
            return None
        idx = (self.image_index + 1) % len(images)
        return images[idx]
