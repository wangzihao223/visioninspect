"""JSON 读写模块.

负责 ImageData 与 JSON 文件之间的转换读写。
"""

import json
import os
import tempfile
from datetime import datetime
from typing import Optional

from data.image_data import ImageData
from utils.logger import get_logger

logger = get_logger(__name__)


class JsonManager:
    """JSON 文件读写管理器.

    JSON 是唯一的持久化数据源。
    每张图片对应一个同名 JSON 文件（image.jpg → image.json）。
    """

    # ------------------------------------------------------------------
    # 读取
    # ------------------------------------------------------------------
    @staticmethod
    def read_json(path: str) -> Optional[dict]:
        """读取 JSON 文件为字典.

        Returns:
            dict 或 None（文件不存在/解析失败）
        """
        if not path or not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.error("读取 JSON 失败 [%s]: %s", path, e)
            return None

    @staticmethod
    def write_json(path: str, data: dict) -> bool:
        """写入 JSON 文件（确保目录存在）.

        Returns:
            bool 是否写入成功
        """
        try:
            payload = json.dumps(data, ensure_ascii=False, indent=4).encode("utf-8")
        except (TypeError, ValueError) as exc:
            logger.error("序列化 JSON 失败 [%s]: %s", path, exc)
            return False
        return JsonManager.write_bytes(path, payload)

    @staticmethod
    def write_bytes(path: str, payload: bytes) -> bool:
        """Atomically replace a file, preserving exact bytes for undo."""
        temporary_path = None
        try:
            directory = os.path.dirname(os.path.abspath(path))
            os.makedirs(directory, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode="wb", dir=directory, delete=False) as temporary:
                temporary_path = temporary.name
                temporary.write(payload)
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_path, path)
            return True
        except (OSError, TypeError) as e:
            logger.error("写入 JSON 失败 [%s]: %s", path, e)
            return False
        finally:
            if temporary_path and os.path.exists(temporary_path):
                try:
                    os.unlink(temporary_path)
                except OSError as exc:
                    logger.warning("临时文件清理失败 [%s]: %s", temporary_path, exc)

    # ------------------------------------------------------------------
    # ImageData 转换
    # ------------------------------------------------------------------
    @staticmethod
    def load_image_data(file_path: str, part_id: str = "") -> ImageData:
        """从图片路径加载 ImageData.

        如果存在同名 JSON，则读取标注/审核信息；
        否则创建空 ImageData（无标注）。

        Args:
            file_path: 图片文件路径
            part_id: 零件号

        Returns:
            ImageData 实例
        """
        img = ImageData(file_path=file_path, part_id=part_id)
        json_path = img.json_path

        data = JsonManager.read_json(json_path)
        if data is not None:
            loaded = ImageData.from_json_dict(data, file_path=file_path, part_id=part_id)
            # 保留图片尺寸（JSON 为空时用 cv2 获取）
            if loaded.width > 0 and loaded.height > 0:
                return loaded
            img = loaded

        # 尝试从图片文件获取尺寸（优先 PIL，兼容中文路径；备选 cv2）
        try:
            from PIL import Image

            with Image.open(file_path) as pil_img:
                img.width, img.height = pil_img.size
        except ImportError:
            try:
                import cv2

                cv_img = cv2.imread(file_path)
                if cv_img is not None:
                    h, w = cv_img.shape[:2]
                    img.width = w
                    img.height = h
            except Exception as e:
                logger.debug("读取图片尺寸失败（cv2）[%s]: %s", file_path, e)
        except Exception as e:
            logger.debug("读取图片尺寸失败（PIL）[%s]: %s", file_path, e)

        return img

    @staticmethod
    def save_image_data(img: ImageData) -> bool:
        """保存 ImageData 到其同名 JSON 文件.

        Args:
            img: ImageData 实例

        Returns:
            bool 是否保存成功
        """
        if not img.json_path:
            return False
        data = img.to_json_dict()
        ok = JsonManager.write_json(img.json_path, data)
        if ok:
            logger.debug("已保存 JSON: %s", img.json_path)
        return ok

    @staticmethod
    def create_json(img: ImageData) -> bool:
        """创建初始 JSON（用于模型推理后首次保存）."""
        return JsonManager.save_image_data(img)

    @staticmethod
    def json_exists(img: ImageData) -> bool:
        """检查图片的同名 JSON 是否已存在."""
        return bool(img.json_path) and os.path.exists(img.json_path)
