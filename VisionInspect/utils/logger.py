"""日志工具模块."""

import logging
import os
import sys
from datetime import datetime
from utils.runtime_paths import data_directory

# 日志格式
LOG_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def get_log_file_path() -> str:
    """获取日志文件路径（项目目录下 logs/visioninspect.log）."""
    base_dir = str(data_directory())
    log_dir = os.path.join(base_dir, "logs")
    os.makedirs(log_dir, exist_ok=True)
    return os.path.join(log_dir, "visioninspect.log")


def setup_logger(name: str = "VisionInspect", level: int = logging.INFO) -> logging.Logger:
    """初始化并返回全局日志器.

    Args:
        name: 日志器名称
        level: 日志级别

    Returns:
        logging.Logger 实例
    """
    logger = logging.getLogger(name)
    if logger.handlers:
        # 已初始化过，直接返回
        return logger

    logger.setLevel(level)

    # 控制台输出
    if sys.stdout is not None:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(level)
        console_handler.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))
        logger.addHandler(console_handler)

    # 文件输出
    try:
        file_handler = logging.FileHandler(get_log_file_path(), encoding="utf-8")
        file_handler.setLevel(level)
        file_handler.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))
        logger.addHandler(file_handler)
    except OSError:
        # 日志目录不可写时仅使用控制台
        pass

    return logger


def get_logger(name: str = "VisionInspect") -> logging.Logger:
    """获取指定名称的日志器（自动初始化）."""
    return setup_logger(name)
