"""YOLO 推理引擎模块.

负责批量执行 YOLO 模型识别，并将结果统一转换为 Annotation 对象。
不使用 ONNX，直接调用 .pt 模型。
"""

import os
from datetime import datetime
from typing import Optional

from data.image_data import Annotation, ImageData
from data.model_info import ModelInfo
from data.project_data import ProjectData
from storage.json_reader import JsonManager
from utils.common import AnnotationSource, ReviewType
from utils.logger import get_logger

logger = get_logger(__name__)


class YOLOEngine:
    """YOLO 推理引擎.

    对图片批量推理，将 YOLO 结果（bbox/类别/置信度）
    转换为 Annotation 列表，并保存到同名 JSON。

    Attributes:
        model: ultralytics YOLO 模型实例
        model_info: 模型信息
    """

    def __init__(self, model=None, model_info: Optional[ModelInfo] = None):
        self.model = model
        self.model_info = model_info
        self.conf_thres = 0.25
        self.iou_thres = 0.45
        self.device = '0'

    # ------------------------------------------------------------------
    # 配置
    # ------------------------------------------------------------------
    def configure(self, conf_thres: float = 0.25, iou_thres: float = 0.45, device: str = "0"):
        """设置推理参数."""
        self.conf_thres = conf_thres
        self.iou_thres = iou_thres
        self.device = device

    def set_model(self, model, model_info: ModelInfo):
        """设置推理模型."""
        self.model = model
        self.model_info = model_info

    # ------------------------------------------------------------------
    # 推理
    # ------------------------------------------------------------------
    def predict(self, image_path: str) -> list:
        """单张图片推理，返回 Annotation 列表.

        Args:
            image_path: 图片文件路径

        Returns:
            list[Annotation]
        """
        if self.model is None:
            raise RuntimeError("未加载模型，请先加载 .pt 模型")

        results = self.model.predict(
            source=image_path,
            conf=self.conf_thres,
            iou=self.iou_thres,
            device=self.device,
            verbose=False,
        )

        annotations = []
        if results:
            result = results[0]
            boxes = result.boxes
            if boxes is not None and len(boxes) > 0:
                for box in boxes:
                    x1, y1, x2, y2 = box.xyxy[0].tolist()
                    conf = float(box.conf[0])
                    cls_id = int(box.cls[0])
                    cls_name = self._get_class_name(cls_id)

                    ann = Annotation(
                        bbox=[x1, y1, x2, y2],
                        class_id=cls_id,
                        class_name=cls_name,
                        confidence=conf,
                        source=AnnotationSource.MODEL,
                        review_type=ReviewType.UNREVIEW,
                    )
                    annotations.append(ann)
        return annotations

    def predict_folder(self, project: ProjectData, force: bool = False, progress_callback=None) -> dict:
        """批量推理整个项目（全部零件全部图片）.

        流程：
            1. 遍历所有零件图片
            2. 如果 JSON 已存在且不强制 → 跳过
            3. 执行推理 → 转换为 Annotation
            4. 保存到同名 JSON

        Args:
            project: 项目数据
            force: 是否强制重新识别（忽略已有 JSON）
            progress_callback: 进度回调函数(current, total, message)

        Returns:
            {"processed": int, "skipped": int, "failed": int}
        """
        if self.model is None:
            raise RuntimeError("未加载模型，请先加载 .pt 模型")

        # 收集全部图片
        all_images = []
        for part in project.parts:
            all_images.extend(part.images)

        total = len(all_images)
        processed = 0
        skipped = 0
        failed = 0

        infer_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        for idx, img in enumerate(all_images):
            # 检查 JSON 是否已存在
            if JsonManager.json_exists(img) and not force:
                skipped += 1
                if progress_callback:
                    progress_callback(idx + 1, total, f"跳过（已有结果）: {img.file_name}")
                continue

            if progress_callback:
                progress_callback(idx + 1, total, f"识别中: {img.part_id}/{img.file_name}")

            original_state = img.__dict__.copy()
            try:
                annotations = self.predict(img.file_path)

                # 更新图片信息
                img.annotations = annotations
                img.project_name = project.project_name
                img.camera_id = os.path.splitext(img.file_name)[0]
                img.capture_time = datetime.fromtimestamp(
                    os.path.getmtime(img.file_path)
                ).strftime("%Y-%m-%d %H:%M:%S")

                # 模型信息
                if self.model_info:
                    img.model_name = self.model_info.model_name
                    img.model_version = self.model_info.version
                    img.model_file = os.path.basename(self.model_info.model_path)
                    img.infer_time = infer_time

                # 重置审核信息（新推理结果需要重新审核）
                img.review_user = ""
                img.review_time = ""
                img.review_status_text = "unreviewed"
                img.image_status = "unknown"
                img.part_status = "unknown"

                # 保存 JSON
                if not JsonManager.save_image_data(img):
                    raise OSError(f"无法保存推理结果: {img.json_path}")
                processed += 1

            except Exception as e:
                img.__dict__.clear()
                img.__dict__.update(original_state)
                logger.error("推理失败 [%s]: %s", img.file_path, e)
                failed += 1

        logger.info("批量推理完成: 处理 %d 张，跳过 %d 张，失败 %d 张", processed, skipped, failed)
        return {"processed": processed, "skipped": skipped, "failed": failed}

    # ------------------------------------------------------------------
    # 结果转换
    # ------------------------------------------------------------------
    def convert_result(self, yolo_result, image_width: int = 0, image_height: int = 0) -> list:
        """将 YOLO Result 对象转换为 Annotation 列表.

        Args:
            yolo_result: ultralytics 推理结果
            image_width: 图片宽度
            image_height: 图片高度

        Returns:
            list[Annotation]
        """
        annotations = []
        if yolo_result is None:
            return annotations

        boxes = getattr(yolo_result, "boxes", None)
        if boxes is None or len(boxes) == 0:
            return annotations

        for box in boxes:
            x1, y1, x2, y2 = box.xyxy[0].tolist()
            conf = float(box.conf[0])
            cls_id = int(box.cls[0])

            ann = Annotation(
                bbox=[x1, y1, x2, y2],
                class_id=cls_id,
                class_name=self._get_class_name(cls_id),
                confidence=conf,
                source=AnnotationSource.MODEL,
                review_type=ReviewType.UNREVIEW,
            )
            annotations.append(ann)
        return annotations

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------
    def _get_class_name(self, class_id: int) -> str:
        """根据类别 id 获取中文类别名称."""
        if self.model_info and self.model_info.classes:
            classes = self.model_info.classes
            if 0 <= class_id < len(classes):
                return str(classes[class_id])
        # 尝试从模型本身获取
        if self.model is not None:
            try:
                names = getattr(self.model, "names", None)
                if isinstance(names, dict) and class_id in names:
                    return str(names[class_id])
                if isinstance(names, (list, tuple)) and 0 <= class_id < len(names):
                    return str(names[class_id])
            except AttributeError:
                pass
        return f"class_{class_id}"
