"""配置管理模块."""

import json
import os
from copy import deepcopy

from utils.logger import get_logger
from utils.runtime_paths import data_directory

logger = get_logger(__name__)

# 项目根目录
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = str(data_directory() / "config")

DEFAULT_CONFIG = {
    "app": {
        "app_name": "VisionInspect",
        "app_version": "V2.0",
        "language": "zh_CN",
    },
    "window": {"width": 1440, "height": 900},
    "review": {"default_user": "admin", "auto_save": True},
    "paths": {"last_project": "", "last_model": ""},
    "thumbnail": {"size": 160, "spacing": 8},
    "inference": {
        "confidence_threshold": 0.25,
        "iou_threshold": 0.45,
        "device": "auto",
        "batch_size": 1,
    },
    "excel": {"report_name": "模型评估报告.xlsx"},
}

DEFAULT_CLASSES = {
    "defect_classes": [
        {"name": "线头", "code": "THREAD", "enabled": True},
        {"name": "脏污", "code": "DIRT", "enabled": True},
        {"name": "褶皱", "code": "WRINKLE", "enabled": True},
        {"name": "划伤", "code": "SCRATCH", "enabled": True},
        {"name": "破损", "code": "DAMAGE", "enabled": True},
        {"name": "缝线不良", "code": "SEWING_DEFECT", "enabled": True},
        {"name": "压痕", "code": "DENT", "enabled": True},
        {"name": "异物", "code": "FOREIGN", "enabled": True},
    ],
    "review_types": [
        {"key": "correct", "name": "正确", "color": "#00CC00"},
        {"key": "miss", "name": "漏报", "color": "#FFCC00"},
        {"key": "wrong_class", "name": "错报", "color": "#0066FF"},
        {"key": "false_positive", "name": "误报", "color": "#FF3333"},
        {"key": "overkill", "name": "过杀", "color": "#AA00FF"},
        {"key": "unreview", "name": "未审核", "color": "#999999"},
    ],
}


class ConfigManager:
    """配置管理.

    负责 config.json 与 classes.json 的读写。
    提供类方法，全局共享。
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self.config_path = os.path.join(CONFIG_DIR, "config.json")
        self.classes_path = os.path.join(CONFIG_DIR, "classes.json")
        self.config = self._load_config()
        self.classes_data = self._load_classes()

    # ------------------------------------------------------------------
    # 内部加载
    # ------------------------------------------------------------------
    def _load_config(self) -> dict:
        """加载 config.json."""
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            # 合并默认值（防止缺字段）
            merged = deepcopy(DEFAULT_CONFIG)
            self._deep_merge(merged, data)
            return merged
        except (FileNotFoundError, json.JSONDecodeError) as e:
            logger.warning("加载 config.json 失败: %s，使用默认配置", e)
            return dict(DEFAULT_CONFIG)

    @staticmethod
    def _deep_merge(target: dict, values: dict) -> dict:
        """Merge nested configuration values without dropping defaults."""
        for key, value in values.items():
            if isinstance(value, dict) and isinstance(target.get(key), dict):
                ConfigManager._deep_merge(target[key], value)
            else:
                target[key] = value
        return target

    def _load_classes(self) -> dict:
        """加载 classes.json."""
        try:
            with open(self.classes_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            logger.warning("加载 classes.json 失败: %s，使用默认配置", e)
            return dict(DEFAULT_CLASSES)

    # ------------------------------------------------------------------
    # 对外接口
    # ------------------------------------------------------------------
    def get(self, key: str, default=None):
        """获取全局配置项，支持点路径，如 "app.app_name"."""
        current = self.config
        for part in key.split("."):
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return default
        return current

    def set(self, key: str, value):
        """设置全局配置项并保存."""
        parts = key.split(".")
        current = self.config
        for part in parts[:-1]:
            if part not in current or not isinstance(current[part], dict):
                current[part] = {}
            current = current[part]
        current[parts[-1]] = value
        self.save_config()

    def get_defect_classes(self) -> list:
        """获取启用的缺陷类别名称列表."""
        return [
            item["name"]
            for item in self.classes_data.get("defect_classes", [])
            if item.get("enabled", True)
        ]

    def get_defect_class_codes(self) -> dict:
        """获取类别名称→编码映射."""
        return {
            item["name"]: item.get("code", "")
            for item in self.classes_data.get("defect_classes", [])
        }

    def save_config(self):
        """保存 config.json."""
        try:
            os.makedirs(CONFIG_DIR, exist_ok=True)
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self.config, f, ensure_ascii=False, indent=4)
        except OSError as e:
            logger.error("保存 config.json 失败: %s", e)

    def save_classes(self):
        """保存 classes.json."""
        try:
            os.makedirs(CONFIG_DIR, exist_ok=True)
            with open(self.classes_path, "w", encoding="utf-8") as f:
                json.dump(self.classes_data, f, ensure_ascii=False, indent=4)
        except OSError as e:
            logger.error("保存 classes.json 失败: %s", e)
