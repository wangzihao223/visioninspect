"""零件级缺陷关联管理模块.

解决同一个真实缺陷被多个相机重复拍摄的问题。
负责缺陷实例的创建、绑定检测框、解绑、零件级结果判定。
"""

from typing import Optional

from data.defect_data import Defect
from data.project_data import PartData, ProjectData
from utils.logger import get_logger

logger = get_logger(__name__)


class DefectManager:
    """零件级缺陷关联管理器.

    管理当前项目的缺陷实例，提供创建、绑定、解绑、查询操作。
    """

    def __init__(self, project: Optional[ProjectData] = None):
        self.project = project
        self.current_defect = None

    # ------------------------------------------------------------------
    # 初始化
    # ------------------------------------------------------------------
    def set_project(self, project: ProjectData):
        """绑定项目."""
        self.project = project

    # ------------------------------------------------------------------
    # 缺陷实例操作
    # ------------------------------------------------------------------
    def create_defect(self, part_id: str, class_name: str, description: str = "") -> Defect:
        """创建新的缺陷实例.

        Args:
            part_id: 零件号
            class_name: 缺陷类别名称
            description: 描述

        Returns:
            Defect
        """
        if not self.project:
            raise ValueError("尚未加载项目")
        part = self.project.get_part(part_id)
        if not part:
            raise ValueError(f"零件不存在: {part_id}")

        defect = Defect(part_id=part_id, class_name=class_name, description=description)
        part.add_defect(defect)
        self.current_defect = defect
        logger.info("创建缺陷实例: %s（零件 %s，类别 %s）", defect.defect_id, part_id, class_name)
        return defect

    def delete_defect(self, part_id: str, defect_id: str) -> bool:
        """删除缺陷实例（同时解绑所有标注）."""
        part = self.project.get_part(part_id) if self.project else None
        if not part:
            return False
        defect = part.get_defect(defect_id)
        if not defect:
            return False

        # 解绑该缺陷关联的所有标注
        for binding in defect.annotation_bindings:
            self._clear_annotation_defect(binding)

        ok = part.remove_defect(defect_id)
        if self.current_defect and self.current_defect.defect_id == defect_id:
            self.current_defect = None
        logger.info("删除缺陷实例: %s", defect_id)
        return ok

    # ------------------------------------------------------------------
    # 绑定操作
    # ------------------------------------------------------------------
    def bind_annotation(self, part_id: str, image, annotation) -> bool:
        """绑定一个检测框到当前缺陷实例.

        Args:
            part_id: 零件号
            image: ImageData
            annotation: Annotation

        Returns:
            bool 是否绑定成功
        """
        if not self.current_defect:
            logger.warning("未选择缺陷实例，无法绑定")
            return False
        if self.current_defect.part_id != part_id:
            # 可跨图片，但必须属于同一零件
            if self.current_defect.part_id != part_id:
                logger.warning("缺陷实例属于零件 %s，无法绑定零件 %s 的标注",
                              self.current_defect.part_id, part_id)
                return False

        # 同一个标注只能属于一个缺陷
        if annotation.defect_id and annotation.defect_id != self.current_defect.defect_id:
            logger.warning("标注 %s 已绑定到缺陷 %s", annotation.id, annotation.defect_id)
            return False

        binding_review_type = annotation.review_type.value
        self.current_defect.bind_annotation(
            part_id=part_id,
            image_id=image.image_id,
            annotation_id=annotation.id,
            review_type=binding_review_type,
        )
        annotation.set_defect(self.current_defect.defect_id)
        logger.debug("绑定标注 %s → 缺陷 %s", annotation.id, self.current_defect.defect_id)
        return True

    def unbind_annotation(self, part_id: str, image, annotation) -> bool:
        """解绑一个检测框与缺陷实例的关联."""
        if not self.current_defect:
            return False
        ok = self.current_defect.unbind_annotation(image.image_id, annotation.id)
        if ok:
            annotation.set_defect(None)
            logger.debug("解绑标注 %s ← 缺陷 %s", annotation.id, self.current_defect.defect_id)
        return ok

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------
    def get_part_defects(self, part_id: str) -> list:
        """获取零件的全部缺陷实例."""
        part = self.project.get_part(part_id) if self.project else None
        return part.defects if part else []

    def get_defect(self, part_id: str, defect_id: str):
        """获取指定缺陷实例."""
        part = self.project.get_part(part_id) if self.project else None
        return part.get_defect(defect_id) if part else None

    def select_defect(self, defect: Optional[Defect]):
        """选择当前缺陷实例."""
        self.current_defect = defect

    # ------------------------------------------------------------------
    # 零件级结果
    # ------------------------------------------------------------------
    def get_part_result(self, part_id: str) -> dict:
        """计算零件级汇总结果.

        统计口径（零件号级去重）：
            已绑定的缺陷实例 → 每个实例 = 1 个缺陷（多相机去重）
            未绑定的检测框 → 每框独立 = 1 个缺陷（不重复实例）

        Returns:
            {
                "part_id": str,
                "total_defects": int,
                "detected": int,
                "missed": int,
                "false_positive": int,
                "wrong_class": int,
                "overkill": int,
                "precision": float|None,
                "recall": float|None,
                "f1": float|None,
            }
        """
        part = self.project.get_part(part_id) if self.project else None
        if not part:
            return {}

        total = 0
        detected = 0
        missed = 0
        fp = 0
        wrong = 0
        overkill = 0

        # 1. 已绑定的缺陷实例（去重后）
        #    过杀按实例内所有"过杀"检测框数量累计（overkill_count），
        #    而非仅按实例最终状态 +1，避免实例内混有其他类型框时过杀框被状态判定吞掉。
        for defect in part.defects:
            result = defect.get_part_result()
            total += 1
            status = result["status"]
            if status == "detected":
                detected += 1
            elif status == "missed":
                missed += 1
            elif status == "false_positive":
                fp += 1
            elif status == "wrong_class":
                wrong += 1
            overkill += result.get("overkill_count", 0)

        # 2. 未绑定的检测框（每框独立计数）
        bound_ann_ids = set()
        for defect in part.defects:
            for binding in defect.annotation_bindings:
                bound_ann_ids.add((binding.get("image_id"), binding.get("annotation_id")))

        for img in part.images:
            for ann in img.annotations:
                key = (img.image_id, ann.id)
                if key in bound_ann_ids:
                    continue  # 已绑定到缺陷实例，跳过
                # 未绑定的框作为独立缺陷实例统计
                total += 1
                status = ann.review_type.value
                if status == "correct":
                    detected += 1
                elif status == "miss":
                    missed += 1
                elif status == "false_positive":
                    fp += 1
                elif status == "wrong_class":
                    wrong += 1
                elif status == "overkill":
                    overkill += 1
                # unreview 不参与零件级结果统计

        precision = None
        recall = None
        f1 = None
        if detected + fp > 0:
            precision = detected / (detected + fp)
        if detected + missed > 0:
            recall = detected / (detected + missed)
        if precision is not None and recall is not None and precision + recall > 0:
            f1 = 2 * precision * recall / (precision + recall)

        return {
            "part_id": part_id,
            "total_defects": total,
            "detected": detected,
            "missed": missed,
            "false_positive": fp,
            "wrong_class": wrong,
            "overkill": overkill,
            "precision": precision,
            "recall": recall,
            "f1": f1,
        }

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------
    def _clear_annotation_defect(self, binding: dict):
        """清除指定绑定关系中标注上的 defect_id."""
        if not self.project:
            return
        part = self.project.get_part(binding.get("part_id", ""))
        if not part:
            return
        img = part.get_image(binding.get("image_id", ""))
        if not img:
            return
        ann = img.get_annotation(binding.get("annotation_id", ""))
        if ann:
            ann.set_defect(None)