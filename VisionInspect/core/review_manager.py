"""审核管理模块.

负责人工审核逻辑：正确、漏报、错报、误报、过杀、未审核。
"""

from datetime import datetime
from typing import Optional

from data.image_data import Annotation, ImageData
from storage.json_reader import JsonManager
from utils.common import AnnotationSource, ReviewType
from utils.logger import get_logger

logger = get_logger(__name__)


class ReviewManager:
    """审核管理器.

    负责设定标注的审核分类，并保存审核人员/时间信息。
    """

    def __init__(self, user_name: str = "admin"):
        self.current_user = user_name
        self.current_image = None

    # ------------------------------------------------------------------
    # 审核操作
    # ------------------------------------------------------------------
    def set_correct(self, annotation: Annotation, review_class: Optional[str] = None):
        """标记为 正确（快捷键 1）."""
        self._apply_review(annotation, ReviewType.CORRECT, review_class)

    def set_miss(self, annotation: Annotation, review_class: Optional[str] = None):
        """标记为 漏报（快捷键 2）."""
        self._apply_review(annotation, ReviewType.MISS, review_class)

    def set_wrong_class(self, annotation: Annotation, review_class: Optional[str] = None):
        """标记为 错报（快捷键 3）."""
        self._apply_review(annotation, ReviewType.WRONG_CLASS, review_class)

    def set_false_positive(self, annotation: Annotation, review_class: Optional[str] = None):
        """标记为 误报（快捷键 4）."""
        self._apply_review(annotation, ReviewType.FALSE_POSITIVE, review_class)

    def set_overkill(self, annotation: Annotation, review_class: Optional[str] = None):
        """标记为 过杀（快捷键 5）."""
        self._apply_review(annotation, ReviewType.OVERKILL, review_class)

    def set_unreview(self, annotation: Annotation):
        """标记为 未审核（快捷键 0）."""
        self._apply_review(annotation, ReviewType.UNREVIEW)

    def delete_annotation(self, annotation: Annotation) -> bool:
        """删除标注."""
        if self.current_image and annotation in self.current_image.annotations:
            self.current_image.remove_annotation(annotation)
            return True
        return False

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------
    def _apply_review(self, annotation: Annotation, review_type: ReviewType, review_class: Optional[str] = None):
        """应用审核类型并记录审核信息."""
        if not annotation:
            return

        annotation.set_review(review_type, review_class)
        logger.debug(
            "审核标记: %s → %s（用户=%s）",
            annotation.id,
            review_type.display_name,
            self.current_user,
        )

    # ------------------------------------------------------------------
    # 保存
    # ------------------------------------------------------------------
    def finalize_image(self, image: Optional[ImageData] = None):
        """审核后更新图片的审核信息（用户/时间）.

        调用方应在保存 JSON 前调用此方法。
        """
        if image is not None:
            self.current_image = image
        if not self.current_image:
            return
        self.current_image.review_user = self.current_user
        self.current_image.review_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def set_user(self, user_name: str):
        """设置当前审核人员."""
        self.current_user = user_name or "admin"