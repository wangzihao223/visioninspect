"""模型管理模块.

负责 YOLO 模型的加载、卸载、类别获取。
"""

import os
from typing import Optional

from data.model_info import ModelInfo
from utils.logger import get_logger

logger = get_logger(__name__)


class ModelManager:
    """模型管理器.

    管理当前加载的 YOLO 模型。

    Attributes:
        current_model: ultralytics YOLO 模型实例（未加载时为 None）
        current_info: ModelInfo 信息对象
    """

    def __init__(self):
        self.current_model = None
        self.current_info = None

    # ------------------------------------------------------------------
    # 模型加载
    # ------------------------------------------------------------------
    def load_model(self, model_path: str) -> ModelInfo:
        """加载 YOLO .pt 模型.

        Args:
            model_path: 模型文件路径（.pt）

        Returns:
            ModelInfo
        """
        if not model_path or not os.path.exists(model_path):
            raise FileNotFoundError(f"模型文件不存在: {model_path}")

        try:
            logger.info('开始导入yolo库')
            from ultralytics import YOLO
        except ImportError as e:
            raise RuntimeError("未安装 ultralytics 库，无法加载模型") from e

        logger.info("正在加载模型: %s", model_path)
        model = YOLO(model_path)

        # 获取类别信息
        names = getattr(model, "names", None)
        if isinstance(names, dict):
            classes = [names[i] for i in sorted(names.keys())]
        elif isinstance(names, (list, tuple)):
            classes = list(names)
        else:
            classes = []

        info = ModelInfo(
            model_name=os.path.splitext(os.path.basename(model_path))[0],
            model_path=model_path,
            model_type="YOLO",
            version=getattr(model, "version", "") or "",
            classes=classes,
        )
        info.load_names()

        self.current_model = model
        self.current_info = info
        logger.info("模型加载完成: %s（%d 个类别）", info.model_name, len(classes))
        return info

    def unload_model(self):
        """卸载当前模型."""
        if self.current_model is not None:
            logger.info("卸载模型: %s", self.current_info.model_name if self.current_info else "未知")
        self.current_model = None
        self.current_info = None

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------
    def is_loaded(self) -> bool:
        """模型是否已加载."""
        return self.current_model is not None

    def get_classes(self) -> list:
        """获取当前模型类别列表."""
        return self.current_info.classes if self.current_info else []

    def get_model_info(self) -> Optional[ModelInfo]:
        """获取当前模型信息."""
        return self.current_info