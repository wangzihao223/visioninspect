"""通用工具：枚举定义、常量、颜色映射."""

from enum import Enum

# 支持的图片扩展名
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp")


class ReviewType(Enum):
    """审核分类."""

    CORRECT = "correct"              # 正确（绿色）
    MISS = "miss"                    # 漏报（黄色）
    WRONG_CLASS = "wrong_class"      # 错报（蓝色）
    FALSE_POSITIVE = "false_positive"  # 误报（红色）
    OVERKILL = "overkill"            # 过杀（紫色）
    UNREVIEW = "unreview"            # 未审核（灰色）

    @property
    def display_name(self) -> str:
        """中文显示名称."""
        return REVIEW_TYPE_NAMES[self]

    @property
    def color(self) -> str:
        """十六进制颜色."""
        return REVIEW_TYPE_COLORS[self]


REVIEW_TYPE_NAMES = {
    ReviewType.CORRECT: "正确",
    ReviewType.MISS: "漏报",
    ReviewType.WRONG_CLASS: "错报",
    ReviewType.FALSE_POSITIVE: "误报",
    ReviewType.OVERKILL: "过杀",
    ReviewType.UNREVIEW: "未审核",
}

REVIEW_TYPE_COLORS = {
    ReviewType.CORRECT: "#00CC00",
    ReviewType.MISS: "#FFCC00",
    ReviewType.WRONG_CLASS: "#0066FF",
    ReviewType.FALSE_POSITIVE: "#FF3333",
    ReviewType.OVERKILL: "#AA00FF",
    ReviewType.UNREVIEW: "#999999",
}


class AnnotationSource(Enum):
    """标注来源."""

    MODEL = "model"   # 模型检测
    HUMAN = "human"   # 人工新增
    MODIFY = "modify" # 人工修改


class ReviewStatus(Enum):
    """图片审核状态."""

    UNREVIEWED = "unreviewed"      # 未审核（灰色）
    PARTIAL = "partial"            # 部分审核（黄色）
    FINISHED = "finished"          # 审核完成（绿色）
    HAS_DEFECT = "has_defect"      # 存在缺陷（红色）


def parse_review_type(value: str) -> ReviewType:
    """将字符串转换为 ReviewType."""
    if not value:
        return ReviewType.UNREVIEW
    for rt in ReviewType:
        if rt.value == value:
            return rt
    return ReviewType.UNREVIEW


def parse_source(value: str) -> AnnotationSource:
    """将字符串转换为 AnnotationSource."""
    if value == AnnotationSource.MODEL.value:
        return AnnotationSource.MODEL
    if value == AnnotationSource.HUMAN.value:
        return AnnotationSource.HUMAN
    if value == AnnotationSource.MODIFY.value:
        return AnnotationSource.MODIFY
    return AnnotationSource.MODEL