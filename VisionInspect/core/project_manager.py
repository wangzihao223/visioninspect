"""项目管理模块.

负责打开数据根目录、扫描零件号、加载图片与 JSON。
"""

import os

from data.image_data import ImageData
from data.model_info import ModelInfo
from data.project_data import PartData, ProjectData
from storage.json_reader import JsonManager
from utils.common import IMAGE_EXTENSIONS
from utils.logger import get_logger
from core.project_classes import load_project_classes

logger = get_logger(__name__)


class ProjectManager:
    """项目管理器.

    管理当前打开的检测项目，负责零件号扫描与数据加载。

    Attributes:
        current_project: 当前 ProjectData
    """

    def __init__(self):
        self.current_project = None

    # ------------------------------------------------------------------
    # 项目加载
    # ------------------------------------------------------------------
    def open_project(self, path: str) -> ProjectData:
        """打开数据根目录并加载项目.

        流程：
            1. 创建 ProjectData
            2. 扫描一级目录为零件号
            3. 加载每个零件的图片列表
            4. 读取 JSON 标注信息

        Args:
            path: 数据根目录

        Returns:
            ProjectData
        """
        if not path or not os.path.isdir(path):
            raise ValueError(f"无效的数据目录: {path}")

        project = ProjectData()
        project.root_path = os.path.abspath(path)
        project.project_name = os.path.basename(project.root_path)
        project.review_classes = load_project_classes(project)

        self.scan_parts(project)
        # 从标注的 defect_id 重建缺陷实例（持久化恢复）
        self._rebuild_defects(project)
        self.current_project = project
        logger.info("项目已打开: %s（%d 个零件）", project.project_name, len(project.parts))

        # 选择第一个零件
        if project.parts:
            first_part = project.parts[0]
            project.current_part_id = first_part.part_id
            if first_part.images:
                project.current_image_id = first_part.images[0].image_id

        return project

    def scan_parts(self, project: ProjectData):
        """扫描根目录下的一级子目录作为零件号，并加载图片."""
        if not project or not project.root_path:
            return

        # 清空旧数据
        project.parts = []

        # 扫描一级目录
        for entry in sorted(os.listdir(project.root_path)):
            part_dir = os.path.join(project.root_path, entry)
            if not os.path.isdir(part_dir):
                continue

            part = PartData(part_id=entry)
            self._load_part_images(part, part_dir)
            if part.images:
                project.add_part(part)

        logger.info("扫描完成: %d 个零件", len(project.parts))

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------
    def _load_part_images(self, part: PartData, part_dir: str):
        """加载零件目录下的全部图片及其 JSON."""
        images = []
        for file_name in sorted(os.listdir(part_dir)):
            file_path = os.path.join(part_dir, file_name)
            if not os.path.isfile(file_path):
                continue
            ext = os.path.splitext(file_name)[1].lower()
            if ext not in IMAGE_EXTENSIONS:
                continue

            img = JsonManager.load_image_data(file_path, part_id=part.part_id)
            img.part_id = part.part_id
            images.append(img)

        part.images = images

    # ------------------------------------------------------------------
    # 缺陷实例恢复
    # ------------------------------------------------------------------
    def _rebuild_defects(self, project: ProjectData):
        """从标注的 defect_id 重建缺陷实例列表.

        缺陷实例自身不持久化（仅依赖 JSON 中每个标注的 defect_id 字段）。
        重启程序后，需要扫描所有图片标注，将相同 defect_id 的标注
        合并为一个缺陷实例。

        Args:
            project: 已加载图片数据的项目
        """
        from data.defect_data import Defect

        if not project:
            return

        for part in project.parts:
            # 临时字典: defect_id -> Defect
            defect_map = {}

            for img in part.images:
                for ann in img.annotations:
                    if not ann.defect_id:
                        continue

                    did = ann.defect_id
                    if did not in defect_map:
                        # 首次出现：创建缺陷实例
                        defect = Defect(
                            defect_id=did,
                            part_id=part.part_id,
                            class_name=ann.defect_class or ann.review_class or ann.class_name,
                            description=ann.defect_description,
                        )
                        defect_map[did] = defect

                    # 绑定该标注
                    defect_map[did].bind_annotation(
                        part_id=part.part_id,
                        image_id=img.image_id,
                        annotation_id=ann.id,
                        review_type=ann.review_type.value,
                    )

            # 设置零件内编号并加入零件
            if defect_map:
                for idx, defect in enumerate(defect_map.values(), 1):
                    defect.index = idx
                    part.add_defect(defect)

    # ------------------------------------------------------------------
    # 其他操作
    # ------------------------------------------------------------------
    def close_project(self):
        """关闭当前项目."""
        if self.current_project:
            logger.info("项目已关闭: %s", self.current_project.project_name)
        self.current_project = None

    def reload_project(self):
        """重新加载当前项目（用于 JSON 变化后刷新）."""
        if self.current_project and self.current_project.root_path:
            self.open_project(self.current_project.root_path)
        return self.current_project

    # ------------------------------------------------------------------
    # 静态工具
    # ------------------------------------------------------------------
    @staticmethod
    def get_image_files(part_dir: str) -> list:
        """获取目录下全部图片文件路径."""
        return [
            os.path.join(part_dir, f)
            for f in sorted(os.listdir(part_dir))
            if os.path.isfile(os.path.join(part_dir, f))
            and os.path.splitext(f)[1].lower() in IMAGE_EXTENSIONS
        ]
