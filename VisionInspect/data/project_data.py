"""项目数据对象：ProjectData 和 PartData."""

import os

from data.defect_data import Defect
from data.image_data import ImageData
from data.model_info import ModelInfo
from utils.common import ReviewType, ReviewStatus
from utils.logger import get_logger

logger = get_logger(__name__)


class PartData:
    """零件号数据对象.

    Attributes:
        part_id: 零件号（一级目录名）
        images: 该零件下的图片列表
        defects: 该零件的缺陷实例列表
    """

    def __init__(self, part_id: str = ""):
        self.part_id = part_id
        self.images = []
        self.defects = []

    # ------------------------------------------------------------------
    # 图片操作
    # ------------------------------------------------------------------
    def add_image(self, image: ImageData):
        """新增图片."""
        self.images.append(image)

    def get_images(self) -> list:
        """获取全部图片."""
        return self.images

    def get_image(self, image_id: str):
        """按图片 id 获取."""
        for img in self.images:
            if img.image_id == image_id:
                return img
        return None

    def get_unreview_images(self) -> list:
        """获取未审核完成的图片列表."""
        return [img for img in self.images if not img.is_review_finished()]

    def get_reviewed_count(self) -> int:
        """已审核（完成）图片数量."""
        return sum(1 for img in self.images if img.is_review_finished())

    def get_total_count(self) -> int:
        """图片总数."""
        return len(self.images)

    # ------------------------------------------------------------------
    # 缺陷操作
    # ------------------------------------------------------------------
    def get_defect_count(self) -> int:
        """缺陷实例数量."""
        return len(self.defects)

    def add_defect(self, defect: Defect):
        """新增缺陷实例."""
        self.defects.append(defect)

    def remove_defect(self, defect_id: str) -> bool:
        """移除缺陷实例."""
        for i, d in enumerate(self.defects):
            if d.defect_id == defect_id:
                del self.defects[i]
                return True
        return False

    def get_defect(self, defect_id: str):
        """按 id 获取缺陷实例."""
        for d in self.defects:
            if d.defect_id == defect_id:
                return d
        return None

    # ------------------------------------------------------------------
    # 状态
    # ------------------------------------------------------------------
    def get_part_status(self) -> ReviewStatus:
        """零件审核状态（基于图片状态汇总）.

        规则：
            - 全部图片审核完成且无缺陷 → FINISHED
            - 存在缺陷 → HAS_DEFECT
            - 部分审核 → PARTIAL
            - 全部未审核 → UNREVIEWED
        """
        if not self.images:
            return ReviewStatus.UNREVIEWED
        finished = [img for img in self.images if img.is_review_finished()]
        if not finished:
            return ReviewStatus.UNREVIEWED
        if len(finished) < len(self.images):
            return ReviewStatus.PARTIAL
        has_defect = any(img.has_problem() for img in self.images)
        return ReviewStatus.HAS_DEFECT if has_defect else ReviewStatus.FINISHED

    def __repr__(self):
        return f"PartData({self.part_id}, images={len(self.images)}, defects={len(self.defects)})"


class ProjectData:
    """检测项目数据对象.

    表示一个打开的数据根目录项目。

    Attributes:
        project_name: 项目名称
        root_path: 数据根目录
        parts: 零件列表
        model_info: 当前项目关联的模型信息
        current_part_id: 当前选中的零件号
    """

    def __init__(self):
        self.project_name = ""
        self.root_path = ""
        self.parts = []
        self.model_info = ModelInfo()
        self.review_classes = None
        self.current_part_id = ""
        self.current_image_id = ""

    # ------------------------------------------------------------------
    # 零件操作
    # ------------------------------------------------------------------
    def add_part(self, part: PartData):
        """新增零件."""
        self.parts.append(part)

    def remove_part(self, part_id: str) -> bool:
        """移除零件."""
        for i, p in enumerate(self.parts):
            if p.part_id == part_id:
                del self.parts[i]
                return True
        return False

    def get_part(self, part_id: str):
        """按零件号获取 PartData."""
        for p in self.parts:
            if p.part_id == part_id:
                return p
        return None

    def get_parts(self) -> list:
        """获取全部零件."""
        return self.parts

    # ------------------------------------------------------------------
    # 当前选择
    # ------------------------------------------------------------------
    def get_current_part(self):
        """获取当前零件."""
        return self.get_part(self.current_part_id)

    def get_current_image(self):
        """获取当前图片."""
        part = self.get_current_part()
        if not part:
            return None
        return part.get_image(self.current_image_id)

    # ------------------------------------------------------------------
    # 统计
    # ------------------------------------------------------------------
    def get_total_images(self) -> int:
        """总图片数."""
        return sum(len(p.images) for p in self.parts)

    def get_reviewed_images(self) -> int:
        """已审核（完成）图片数."""
        return sum(p.get_reviewed_count() for p in self.parts)

    def get_unreviewed_images(self) -> int:
        """未审核（完成）图片数."""
        return self.get_total_images() - self.get_reviewed_images()

    def get_problem_images(self) -> int:
        """存在问题的图片数."""
        return sum(
            1 for p in self.parts for img in p.images if img.has_problem()
        )

    def get_progress(self) -> float:
        """审核进度百分比（0-100）."""
        total = self.get_total_images()
        if total == 0:
            return 0.0
        return round(self.get_reviewed_images() / total * 100, 1)

    def get_total_defects(self) -> int:
        """缺陷实例总数."""
        return sum(p.get_defect_count() for p in self.parts)

    def get_statistics(self) -> dict:
        """项目级汇总统计."""
        stats = {
            "total_images": self.get_total_images(),
            "reviewed_images": self.get_reviewed_images(),
            "unreviewed_images": self.get_unreviewed_images(),
            "problem_images": self.get_problem_images(),
            "progress": self.get_progress(),
            "total_parts": len(self.parts),
            "total_defects": self.get_total_defects(),
            # 图片级审核结果计数
            "correct_count": 0,
            "miss_count": 0,
            "wrong_class_count": 0,
            "false_positive_count": 0,
            "overkill_count": 0,
        }
        for part in self.parts:
            for img in part.images:
                for ann in img.annotations:
                    if ann.review_type == ReviewType.CORRECT:
                        stats["correct_count"] += 1
                    elif ann.review_type == ReviewType.MISS:
                        stats["miss_count"] += 1
                    elif ann.review_type == ReviewType.WRONG_CLASS:
                        stats["wrong_class_count"] += 1
                    elif ann.review_type == ReviewType.FALSE_POSITIVE:
                        stats["false_positive_count"] += 1
                    elif ann.review_type == ReviewType.OVERKILL:
                        stats["overkill_count"] += 1
        return stats

    def __repr__(self):
        return f"ProjectData({self.project_name}, root={self.root_path}, parts={len(self.parts)})"
