"""统计分析模块.

负责：
    1. 图片级统计（审核结果、缺陷类别）
    2. 零件号级统计（Precision / Recall / F1）
    3. 图表生成（柱状图、饼状图、混淆矩阵）
    4. 报表导出（Excel）
"""

from typing import Optional

from data.project_data import ProjectData
from storage.excel_export import ExcelExporter
from utils.common import ReviewType
from utils.logger import get_logger

logger = get_logger(__name__)


class StatisticsManager:
    """统计管理器.

    基于项目数据计算各类统计指标并生成图表/报表。
    """

    def __init__(self, project: Optional[ProjectData] = None):
        self.project = project

    # ------------------------------------------------------------------
    # 初始化
    # ------------------------------------------------------------------
    def set_project(self, project: ProjectData):
        """绑定项目."""
        self.project = project

    # ------------------------------------------------------------------
    # 图片级统计
    # ------------------------------------------------------------------
    def image_statistics(self) -> dict:
        """图片级统计.

        Returns:
            {
                "total_images": int,
                "reviewed_images": int,
                "correct_count": int,
                "miss_count": int,
                "wrong_class_count": int,
                "false_positive_count": int,
                "overkill_count": int,
                "unreviewed_count": int,
                "by_class": {类别名称: {各审核类型计数}},
            }
        """
        if not self.project:
            return {}

        stats = {
            "total_images": self.project.get_total_images(),
            "reviewed_images": self.project.get_reviewed_images(),
            "correct_count": 0,
            "miss_count": 0,
            "wrong_class_count": 0,
            "false_positive_count": 0,
            "overkill_count": 0,
            "unreviewed_count": 0,
            "by_class": {},
        }

        for part in self.project.parts:
            for img in part.images:
                for ann in img.annotations:
                    cls_name = ann.class_name or "未知"
                    if cls_name not in stats["by_class"]:
                        stats["by_class"][cls_name] = {
                            "correct": 0,
                            "miss": 0,
                            "wrong_class": 0,
                            "false_positive": 0,
                            "overkill": 0,
                            "unreview": 0,
                        }

                    rt = ann.review_type
                    if rt == ReviewType.CORRECT:
                        stats["correct_count"] += 1
                        stats["by_class"][cls_name]["correct"] += 1
                    elif rt == ReviewType.MISS:
                        stats["miss_count"] += 1
                        stats["by_class"][cls_name]["miss"] += 1
                    elif rt == ReviewType.WRONG_CLASS:
                        stats["wrong_class_count"] += 1
                        stats["by_class"][cls_name]["wrong_class"] += 1
                    elif rt == ReviewType.FALSE_POSITIVE:
                        stats["false_positive_count"] += 1
                        stats["by_class"][cls_name]["false_positive"] += 1
                    elif rt == ReviewType.OVERKILL:
                        stats["overkill_count"] += 1
                        stats["by_class"][cls_name]["overkill"] += 1
                    else:
                        stats["unreviewed_count"] += 1
                        stats["by_class"][cls_name]["unreview"] += 1

        return stats

    # ------------------------------------------------------------------
    # 零件级统计
    # ------------------------------------------------------------------
    def part_statistics(self) -> dict:
        """零件号级统计（按缺陷实例口径）.

        Returns:
            {
                "total_parts": int,
                "total_defects": int,
                "detected": int,
                "missed": int,
                "false_positive": int,
                "wrong_class": int,
                "overkill": int,
                "precision": float|None,
                "recall": float|None,
                "f1": float|None,
                "per_part": [PartData级别统计...],
            }
        """
        if not self.project:
            return {}

        from core.defect_manager import DefectManager

        defect_mgr = DefectManager(self.project)

        per_part = []
        total_defects = 0
        detected = 0
        missed = 0
        fp = 0
        wrong = 0
        overkill = 0

        for part in self.project.parts:
            result = defect_mgr.get_part_result(part.part_id)
            result["part_id"] = part.part_id
            per_part.append(result)
            total_defects += result["total_defects"]
            detected += result["detected"]
            missed += result["missed"]
            fp += result["false_positive"]
            wrong += result["wrong_class"]
            overkill += result["overkill"]

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
            "total_parts": len(self.project.parts),
            "total_defects": total_defects,
            "detected": detected,
            "missed": missed,
            "false_positive": fp,
            "wrong_class": wrong,
            "overkill": overkill,
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "per_part": per_part,
        }

    def calculate_precision(self):
        """计算整体 Precision."""
        stats = self.part_statistics()
        return stats.get("precision")

    def calculate_recall(self):
        """计算整体 Recall."""
        stats = self.part_statistics()
        return stats.get("recall")

    def calculate_f1(self):
        """计算整体 F1 Score."""
        stats = self.part_statistics()
        return stats.get("f1")

    # ------------------------------------------------------------------
    # 报表导出
    # ------------------------------------------------------------------
    def export_report(self, output_dir: str = "") -> str:
        """导出 Excel 模型评估报告.

        Args:
            output_dir: 输出目录（默认项目根目录）

        Returns:
            文件路径
        """
        if not self.project:
            raise ValueError("尚未加载项目，无法导出报告")
        return ExcelExporter.export_report(self.project, output_dir)