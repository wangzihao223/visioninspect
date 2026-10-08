"""图片数据与标注对象."""

import os
from datetime import datetime
from typing import Optional

from utils.common import (
    AnnotationSource,
    ReviewType,
    ReviewStatus,
    parse_review_type,
    parse_source,
)
from utils.geometry import bbox_to_points, points_to_bbox
from utils.logger import get_logger

logger = get_logger(__name__)


class Annotation:
    """检测框标注对象.

    表示一个检测框，来源可能是模型、人工或人工修改。

    Attributes:
        id: 唯一标识
        bbox: [x1,y1,x2,y2]
        class_id: 模型类别 id
        class_name: 类别名称（如"线头"）
        model_label: 模型原始识别类别，人工改类后保持不变
        confidence: 置信度
        source: 来源（model/human/modify）
        review_type: 审核类型（正确/漏报/错报/误报/过杀/未审核）
        review_class: 审核后的类别（人工修正的缺陷名称）
        defect_id: 关联的零件级缺陷实例 id
    """

    _id_counter = 0

    def __init__(
        self,
        bbox=None,
        class_id=None,
        class_name: str = "",
        confidence: float = 0.0,
        source: AnnotationSource = AnnotationSource.MODEL,
        review_type: ReviewType = ReviewType.UNREVIEW,
        review_class: str = "",
        defect_id: Optional[str] = None,
        annotation_id: Optional[str] = None,
        defect_class: str = "",
        defect_description: str = "",
        model_label: Optional[str] = None,
    ):
        if annotation_id:
            self.id = annotation_id
        else:
            self.id = Annotation._generate_id()
        self.bbox = list(bbox) if bbox else [0, 0, 0, 0]
        self.class_id = class_id
        self.class_name = class_name
        self.model_label = class_name if model_label is None and source == AnnotationSource.MODEL else (model_label or "")
        self.confidence = float(confidence)
        self.source = source
        self.review_type = review_type
        self.review_class = review_class or class_name
        self.defect_id = defect_id
        self.defect_class = defect_class
        self.defect_description = defect_description

    @staticmethod
    def _generate_id() -> str:
        """生成唯一标注 id."""
        Annotation._id_counter += 1
        return f"ANN_{Annotation._id_counter:06d}"

    # ------------------------------------------------------------------
    # 审核操作
    # ------------------------------------------------------------------
    def set_review(self, review_type: ReviewType, review_class: Optional[str] = None):
        """设置审核类型."""
        self.review_type = review_type
        if review_class is not None:
            self.review_class = review_class
        elif review_type == ReviewType.CORRECT:
            self.review_class = self.class_name

    def change_class(self, class_name: str):
        """修改/修正类别名称.

        同时更新 class_name（模型原始类别）和 review_class（审核类别），
        使右侧面板列表与检测框标签同步显示新类别。
        不自动改变 review_type，新增人工框保持"未审核"状态。
        """
        self.class_name = class_name
        self.review_class = class_name
        # 注意：不自动改变 review_type，人工新增框保持"未审核"状态
        # 只有用户显式审核时才改变状态

    def update_bbox(self, bbox):
        """更新 bbox."""
        self.bbox = list(bbox)

    def set_defect(self, defect_id: str):
        """绑定缺陷实例."""
        self.defect_id = defect_id
        if not defect_id:
            self.defect_class = ""
            self.defect_description = ""

    # ------------------------------------------------------------------
    # 序列化
    # ------------------------------------------------------------------
    def to_dict(self) -> dict:
        """转换为 LabelMe shapes 格式字典."""
        return {
            "id": self.id,
            "label": self.class_name,
            "score": round(self.confidence, 6),
            "points": bbox_to_points(self.bbox),
            "group_id": None,
            "shape_type": "rectangle",
            "flags": {},
            "source": self.source.value,
            "model_class_id": self.class_id,
            "model_label": self.model_label,
            "review_type": self.review_type.value,
            "review_class": self.review_class,
            "defect_id": self.defect_id,
            "defect_class": self.defect_class,
            "defect_description": self.defect_description,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Annotation":
        """从 LabelMe shapes 字典创建 Annotation."""
        ann = cls(
            bbox=points_to_bbox(data.get("points", [])),
            class_id=data.get("model_class_id"),
            class_name=data.get("label", ""),
            confidence=data.get("score", 0.0),
            source=parse_source(data.get("source", "model")),
            review_type=parse_review_type(data.get("review_type", "unreview")),
            review_class=data.get("review_class", "") or data.get("label", ""),
            defect_id=data.get("defect_id"),
            annotation_id=data.get("id"),
            defect_class=data.get("defect_class", ""),
            defect_description=data.get("defect_description", ""),
            model_label=data.get("model_label", data.get("label", "") if data.get("source", "model") == "model" else ""),
        )
        # 同步自增计数器，避免重启后 id 冲突
        if ann.id and ann.id.startswith("ANN_"):
            try:
                num = int(ann.id.split("_")[1])
                Annotation._id_counter = max(Annotation._id_counter, num)
            except (ValueError, IndexError):
                pass
        return ann

    def __repr__(self):
        return (
            f"Annotation(id={self.id}, class={self.class_name}, "
            f"review={self.review_type.value}, source={self.source.value})"
        )


class ImageData:
    """单张图片数据对象.

    对应一张照片及其同名 JSON 结果文件。

    Attributes:
        image_id: 图片唯一标识
        file_path: 图片文件完整路径
        file_name: 图片文件名（如 cam01.jpg）
        width: 图片宽度
        height: 图片高度
        annotations: 标注列表
        json_path: JSON 文件路径
        project_name: 项目名称
        part_id: 零件号
        camera_id: 相机编号
        capture_time: 采集时间
        review_info: 审核信息（用户/时间/状态）
    """

    def __init__(
        self,
        file_path: str = "",
        part_id: str = "",
    ):
        self.file_path = file_path
        self.file_name = os.path.basename(file_path) if file_path else ""
        self.part_id = part_id
        self.image_id = f"{part_id}/{self.file_name}" if part_id else self.file_name

        self.width = 0
        self.height = 0
        self.annotations = []
        self.json_path = self._get_json_path()

        self.project_name = ""
        self.camera_id = ""
        self.capture_time = ""

        # 模型信息（来自 JSON）
        self.model_name = ""
        self.model_version = ""
        self.model_file = ""
        self.infer_time = ""

        # 审核信息
        self.review_user = ""
        self.review_time = ""
        self.review_status_text = "unreviewed"

        # 图片级评价结果
        self.image_status = "unknown"
        self.part_status = "unknown"

    def _get_json_path(self) -> str:
        """获取同名 JSON 路径."""
        if not self.file_path:
            return ""
        stem = os.path.splitext(self.file_path)[0]
        return f"{stem}.json"

    # ------------------------------------------------------------------
    # JSON 序列化（写入）
    # ------------------------------------------------------------------
    def to_json_dict(self) -> dict:
        """转换为完整 JSON 字典（对齐模板.json 结构）."""
        from data.model_info import ModelInfo

        model_info = ModelInfo(
            model_name=self.model_name,
            model_path=self.model_file,
            version=self.model_version,
            infer_time=self.infer_time,
        )

        return {
            "version": "5.3.1",
            "flags": {},
            "imagePath": self.file_name,
            "imageData": None,
            "imageHeight": self.height,
            "imageWidth": self.width,
            "project_info": {
                "project_name": self.project_name,
                "part_id": self.part_id,
                "camera_id": self.camera_id,
                "capture_time": self.capture_time,
            },
            "model_info": model_info.to_dict(),
            "review_info": {
                "review_status": self._compute_review_status(),
                "review_user": self.review_user,
                "review_time": self.review_time,
            },
            "shapes": [ann.to_dict() for ann in self.annotations],
            "evaluation_info": {
                "image_result": {
                    "status": self.image_status,
                    "review_finished": self.is_review_finished(),
                },
                "part_result": {
                    "status": self.part_status,
                    "related_defects": self._get_related_defects(),
                },
            },
        }

    def _get_related_defects(self) -> list:
        """获取关联的缺陷实例 id 列表."""
        defect_ids = []
        for ann in self.annotations:
            if ann.defect_id and ann.defect_id not in defect_ids:
                defect_ids.append(ann.defect_id)
        return defect_ids

    # ------------------------------------------------------------------
    # JSON 解析（读取）
    # ------------------------------------------------------------------
    @classmethod
    def from_json_dict(cls, data: dict, file_path: str = "", part_id: str = "") -> "ImageData":
        """从 JSON 字典创建 ImageData（不直接读取文件）."""
        img = cls(file_path=file_path, part_id=part_id or data.get("project_info", {}).get("part_id", ""))

        img.width = data.get("imageWidth", 0)
        img.height = data.get("imageHeight", 0)

        project_info = data.get("project_info", {})
        img.project_name = project_info.get("project_name", "")
        img.camera_id = project_info.get("camera_id", "")
        img.capture_time = project_info.get("capture_time", "")

        model_info = data.get("model_info", {})
        img.model_name = model_info.get("model_name", "")
        img.model_version = model_info.get("model_version", "")
        img.model_file = model_info.get("model_file", "")
        img.infer_time = model_info.get("infer_time", "")

        review_info = data.get("review_info", {})
        img.review_user = review_info.get("review_user", "")
        img.review_time = review_info.get("review_time", "")
        img.review_status_text = review_info.get("review_status", "unreviewed")

        img.annotations = [
            Annotation.from_dict(shape)
            for shape in data.get("shapes", [])
            if shape.get("shape_type", "rectangle") == "rectangle"
        ]

        eval_info = data.get("evaluation_info", {})
        img.image_status = eval_info.get("image_result", {}).get("status", "unknown")
        img.part_status = eval_info.get("part_result", {}).get("status", "unknown")

        return img

    # ------------------------------------------------------------------
    # 审核状态
    # ------------------------------------------------------------------
    def _compute_review_status(self) -> str:
        """计算审核状态字符串."""
        if not self.annotations:
            # 无标注：已标记审核（人工确认无识别目标）→ finished，否则 unreviewed
            return (
                ReviewStatus.FINISHED.value
                if self.review_user or self.review_time
                else ReviewStatus.UNREVIEWED.value
            )
        if all(ann.review_type == ReviewType.UNREVIEW for ann in self.annotations):
            return ReviewStatus.UNREVIEWED.value
        all_reviewed = all(
            ann.review_type != ReviewType.UNREVIEW for ann in self.annotations
        )
        if not all_reviewed:
            return ReviewStatus.PARTIAL.value
        # 全部已审核，检查是否存在缺陷类结果
        has_defect = any(
            ann.review_type in (ReviewType.MISS, ReviewType.FALSE_POSITIVE, ReviewType.WRONG_CLASS)
            for ann in self.annotations
        )
        return ReviewStatus.HAS_DEFECT.value if has_defect else ReviewStatus.FINISHED.value

    def get_review_status(self) -> ReviewStatus:
        """获取图片审核状态枚举."""
        status_text = self._compute_review_status()
        for status in ReviewStatus:
            if status.value == status_text:
                return status
        return ReviewStatus.UNREVIEWED

    def is_review_finished(self) -> bool:
        """是否已审核完成.

        无标注时，仅当存在人工审核记录（确认无识别目标）才算完成；
        有标注时，所有标注均已审核才算完成。
        """
        if not self.annotations:
            return bool(self.review_user or self.review_time)
        return all(ann.review_type != ReviewType.UNREVIEW for ann in self.annotations)

    def is_ever_reviewed(self) -> bool:
        """是否进行过任何审核.

        Returns:
            True：存在审核人/时间记录，或任一标注已被审核（非"未审核"状态）
        """
        if self.review_user or self.review_time:
            return True
        return any(
            ann.review_type != ReviewType.UNREVIEW for ann in self.annotations
        )

    def has_problem(self) -> bool:
        """是否存在问题（漏报/误报等）."""
        return any(
            ann.review_type in (ReviewType.MISS, ReviewType.FALSE_POSITIVE, ReviewType.WRONG_CLASS)
            for ann in self.annotations
        )

    # ------------------------------------------------------------------
    # 标注操作
    # ------------------------------------------------------------------
    def add_annotation(self, annotation: Annotation):
        """新增标注."""
        self.annotations.append(annotation)

    def remove_annotation(self, annotation: Annotation):
        """移除标注."""
        if annotation in self.annotations:
            self.annotations.remove(annotation)

    def get_annotation(self, ann_id: str):
        """按 id 获取标注."""
        for ann in self.annotations:
            if ann.id == ann_id:
                return ann
        return None

    def __repr__(self):
        return (
            f"ImageData({self.file_name}, part={self.part_id}, "
            f"anns={len(self.annotations)}, status={self.review_status_text})"
        )
