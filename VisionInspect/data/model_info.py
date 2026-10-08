"""模型信息数据对象."""

import os
from datetime import datetime

from utils.logger import get_logger

logger = get_logger(__name__)


class ModelInfo:
    """模型信息.

    表示一个 YOLO 模型及其信息，用于推理与追溯。

    Attributes:
        model_name: 模型名称
        model_path: 模型文件路径
        model_type: 模型类型（默认 YOLO）
        version: 模型版本
        classes: 类别名称列表
        infer_time: 推理时间
    """

    def __init__(
        self,
        model_name: str = "",
        model_path: str = "",
        model_type: str = "YOLO",
        version: str = "",
        classes=None,
        infer_time: str = "",
    ):
        self.model_name = model_name or os.path.basename(model_path)
        self.model_path = model_path
        self.model_type = model_type or "YOLO"
        self.version = version
        self.classes = classes or []
        self.infer_time = infer_time or ""

    def load_names(self):
        """从模型文件加载类别名称（由 ModelManager 调用填充）."""
        # 实际类别加载由 ModelManager 通过 ultralytics model.names 完成
        pass

    def to_dict(self) -> dict:
        """转换为 JSON 字典（对齐模板.json 的 model_info 结构）."""
        return {
            "model_name": self.model_name,
            "model_type": self.model_type,
            "model_version": self.version,
            "model_file": os.path.basename(self.model_path) if self.model_path else "",
            "infer_time": self.infer_time,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ModelInfo":
        """从 JSON 字典创建 ModelInfo."""
        if not data:
            return cls()
        return cls(
            model_name=data.get("model_name", ""),
            model_path=data.get("model_file", ""),
            model_type=data.get("model_type", "YOLO"),
            version=data.get("model_version", ""),
            classes=[],
            infer_time=data.get("infer_time", ""),
        )

    def __repr__(self):
        return f"ModelInfo(name={self.model_name}, version={self.version})"