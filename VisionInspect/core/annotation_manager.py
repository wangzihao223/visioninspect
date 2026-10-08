"""标注管理模块.

负责检测框（Annotation）的新增、删除、修改、选择、更新类别。
"""

from typing import Optional

from data.image_data import Annotation, ImageData
from utils.common import AnnotationSource, ReviewType
from utils.logger import get_logger

logger = get_logger(__name__)


class AnnotationManager:
    """标注管理器.

    管理当前图片的检测框集合，维护当前选中的标注。
    """

    def __init__(self):
        self.current_image = None
        self.current_annotations = []
        self.selected_annotation = None

    # ------------------------------------------------------------------
    # 加载
    # ------------------------------------------------------------------
    def set_image(self, image: Optional[ImageData]):
        """设置当前图片并加载其标注."""
        self.current_image = image
        self.current_annotations = image.annotations if image else []
        self.selected_annotation = None

    # ------------------------------------------------------------------
    # 基础操作
    # ------------------------------------------------------------------
    def add_box(self, bbox, class_name: str = "缺陷", confidence: float = 0.0) -> Annotation:
        """新增人工标注框.

        Args:
            bbox: [x1,y1,x2,y2]
            class_name: 缺陷类别名称
            confidence: 置信度（人工框为 0）

        Returns:
            新创建的 Annotation
        """
        ann = Annotation(
            bbox=bbox,
            class_name=class_name,
            confidence=confidence,
            source=AnnotationSource.HUMAN,
            review_type=ReviewType.UNREVIEW,
        )
        self.current_annotations.append(ann)
        logger.debug("新增标注: %s bbox=%s", ann.id, bbox)
        return ann

    def delete_box(self, annotation: Annotation) -> bool:
        """删除标注框."""
        if annotation not in self.current_annotations:
            return False
        self.current_annotations.remove(annotation)
        if self.selected_annotation == annotation:
            self.selected_annotation = None
        logger.debug("删除标注: %s", annotation.id)
        return True

    def modify_box(self, annotation: Annotation, bbox=None, class_name=None):
        """修改标注框（位置和/或类别）."""
        if bbox is not None:
            annotation.update_bbox(bbox)
        if class_name is not None:
            annotation.change_class(class_name)
        logger.debug("修改标注: %s", annotation.id)
        return annotation

    def select_box(self, annotation: Optional[Annotation]):
        """选中标注框."""
        self.selected_annotation = annotation

    def update_label(self, annotation: Annotation, class_name: str):
        """更新标注类别标签."""
        annotation.change_class(class_name)

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------
    def get_box_at(self, x: float, y: float, tolerance: float = 10.0):
        """获取包含/靠近指定点的标注框（命中优先，然后边缘容差）.

        用于鼠标点击选择。

        Args:
            x, y: 图片坐标
            tolerance: 边缘点击容差（像素）

        Returns:
            Annotation 或 None
        """
        if not self.current_annotations:
            return None

        # 优先：点完全在框内
        for ann in self.current_annotations:
            bbox = ann.bbox
            if bbox[0] <= x <= bbox[2] and bbox[1] <= y <= bbox[3]:
                return ann

        # 其次：靠近框边缘（容差内）
        best = None
        best_dist = float("inf")
        for ann in self.current_annotations:
            bbox = ann.bbox
            dx = max(bbox[0] - x, 0, x - bbox[2])
            dy = max(bbox[1] - y, 0, y - bbox[3])
            dist = (dx**2 + dy**2) ** 0.5
            if dist <= tolerance and dist < best_dist:
                best_dist = dist
                best = ann
        return best

    def get_annotations_by_review(self, review_type):
        """按审核类型获取标注列表."""
        return [ann for ann in self.current_annotations if ann.review_type == review_type]