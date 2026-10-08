"""零件级缺陷实例数据对象."""

from datetime import datetime

from utils.logger import get_logger

logger = get_logger(__name__)


class Defect:
    """零件级真实缺陷实例.

    解决"同一真实缺陷被多个相机重复拍摄"的问题：
    一个缺陷实例可绑定多个相机（图片）中的检测框（Annotation）。

    示例：
        Defect DEF_001（线头）
          ├── cam01 的 Annotation（正确）
          ├── cam02 的 Annotation（漏报）
          └── cam04 的 Annotation（正确）
        → 零件级结果：检测成功

    Attributes:
        defect_id: 缺陷实例唯一 id（如 DEF_000001）
        part_id: 所属零件号
        class_name: 缺陷类别名称（如"线头"）
        description: 缺陷描述
        annotation_bindings: 绑定的标注列表 [{image_id, annotation_id, part_id, review_type}]
        create_time: 创建时间
    """

    def __init__(
        self,
        defect_id: str = "",
        part_id: str = "",
        class_name: str = "",
        description: str = "",
    ):
        self.defect_id = defect_id or Defect._generate_id()
        self.part_id = part_id
        self.class_name = class_name
        self.description = description
        self.create_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        # 零件内编号（1, 2, 3...），用于主图标签显示 ① ② ③
        self.index = 0
        # 每个元素: {"part_id", "image_id", "annotation_id", "review_type"}
        self.annotation_bindings = []

    @staticmethod
    def _generate_id() -> str:
        """生成唯一缺陷 id."""
        from datetime import datetime as dt

        ts = dt.now().strftime("%Y%m%d%H%M%S")
        return f"DEF_{ts}"

    # ------------------------------------------------------------------
    # 绑定操作
    # ------------------------------------------------------------------
    def bind_annotation(self, part_id: str, image_id: str, annotation_id: str, review_type: str = "correct"):
        """绑定一个检测框到缺陷实例.

        Args:
            part_id: 零件号
            image_id: 图片标识
            annotation_id: 标注 id
            review_type: 该框审核类型
        """
        for binding in self.annotation_bindings:
            if (
                binding["image_id"] == image_id
                and binding["annotation_id"] == annotation_id
            ):
                binding["review_type"] = review_type
                return
        self.annotation_bindings.append(
            {
                "part_id": part_id,
                "image_id": image_id,
                "annotation_id": annotation_id,
                "review_type": review_type,
            }
        )

    def unbind_annotation(self, image_id: str, annotation_id: str) -> bool:
        """解绑指定检测框."""
        for i, binding in enumerate(self.annotation_bindings):
            if (
                binding["image_id"] == image_id
                and binding["annotation_id"] == annotation_id
            ):
                del self.annotation_bindings[i]
                return True
        return False

    # ------------------------------------------------------------------
    # 结果判定
    # ------------------------------------------------------------------
    def get_part_result(self) -> dict:
        """计算零件级结果.

        规则（对应需求文档第五章）：
            - 至少一个框审核为"正确(correct)" → 检测成功
            - 所有框均为漏报 → 漏检
            - 其他情况按实际判定

        Returns:
            {"status": "detected"/"missed"/"false_positive"/"unknown"|...,
             "correct_count": int, "miss_count": int, ...}
        """
        correct_count = 0
        miss_count = 0
        wrong_count = 0
        fp_count = 0
        overkill_count = 0
        unreview_count = 0

        for binding in self.annotation_bindings:
            rt = binding.get("review_type", "unreview")
            if rt == "correct":
                correct_count += 1
            elif rt == "miss":
                miss_count += 1
            elif rt == "wrong_class":
                wrong_count += 1
            elif rt == "false_positive":
                fp_count += 1
            elif rt == "overkill":
                overkill_count += 1
            else:
                unreview_count += 1

        # 有任意"正确" → 检测成功
        if correct_count > 0:
            status = "detected"
        elif miss_count > 0 and correct_count == 0 and wrong_count == 0 and fp_count == 0:
            status = "missed"
        elif fp_count > 0 and correct_count == 0:
            status = "false_positive"
        elif wrong_count > 0 and correct_count == 0:
            status = "wrong_class"
        elif overkill_count > 0 and correct_count == 0:
            status = "overkill"
        else:
            status = "unknown"

        return {
            "status": status,
            "correct_count": correct_count,
            "miss_count": miss_count,
            "wrong_count": wrong_count,
            "fp_count": fp_count,
            "overkill_count": overkill_count,
            "unreview_count": unreview_count,
        }

    def is_review_finished(self) -> bool:
        """所有绑定框是否均已审核."""
        return all(
            binding.get("review_type", "unreview") != "unreview"
            for binding in self.annotation_bindings
        )

    # ------------------------------------------------------------------
    # 序列化
    # ------------------------------------------------------------------
    def to_dict(self) -> dict:
        """转换为字典（用于内存保存/导出）."""
        return {
            "defect_id": self.defect_id,
            "part_id": self.part_id,
            "class_name": self.class_name,
            "description": self.description,
            "create_time": self.create_time,
            "annotation_bindings": self.annotation_bindings,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Defect":
        """从字典创建 Defect."""
        defect = cls(
            defect_id=data.get("defect_id", ""),
            part_id=data.get("part_id", ""),
            class_name=data.get("class_name", ""),
            description=data.get("description", ""),
        )
        defect.create_time = data.get("create_time", defect.create_time)
        defect.annotation_bindings = list(data.get("annotation_bindings", []))
        return defect

    def __repr__(self):
        return (
            f"Defect({self.defect_id}, part={self.part_id}, "
            f"class={self.class_name}, bindings={len(self.annotation_bindings)})"
        )