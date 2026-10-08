"""Review operations shared by ImGui controls and keyboard actions."""

import os
from collections import deque
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

from core.annotation_manager import AnnotationManager
from core.project_manager import ProjectManager
from core.review_manager import ReviewManager
from storage.json_reader import JsonManager
from utils.common import ReviewType


class ReviewActions:
    def __init__(self, project, review_manager: ReviewManager):
        self.project = project
        self.review_manager = review_manager
        self._undo_history = deque(maxlen=50)

    @property
    def can_undo(self):
        return bool(self._undo_history)

    @property
    def undo_label(self):
        return self._undo_history[-1][0] if self._undo_history else ""

    @staticmethod
    def _snapshot(image):
        path = Path(image.json_path)
        payload = path.read_bytes() if path.exists() else None
        return image, deepcopy(image.__dict__), payload

    def undo(self):
        if not self._undo_history:
            raise ValueError("没有可撤销的操作")
        label, snapshots = self._undo_history[-1]
        pending = []
        restored = []
        for image, state, payload in snapshots:
            try:
                if payload is None:
                    if os.path.exists(image.json_path):
                        os.unlink(image.json_path)
                elif not JsonManager.write_bytes(image.json_path, payload):
                    raise OSError(image.json_path)
            except OSError:
                pending.append((image, state, payload))
                continue
            image.__dict__.clear()
            image.__dict__.update(deepcopy(state))
            restored.append(image)
        self._rebuild_defects()
        if pending:
            self._undo_history[-1] = (label, pending)
            raise OSError("以下图片撤销失败，历史记录已保留，可重试：\n" + "\n".join(image.json_path for image, state, payload in pending))
        self._undo_history.pop()
        return restored[0]

    def _rebuild_defects(self):
        metadata = {defect.defect_id: (defect.class_name, defect.description)
                    for part in self.project.parts for defect in part.defects}
        for part in self.project.parts:
            part.defects = []
        ProjectManager()._rebuild_defects(self.project)
        for part in self.project.parts:
            for defect in part.defects:
                if defect.defect_id in metadata:
                    defect.class_name, defect.description = metadata[defect.defect_id]

    def _edit(self, images, operation, finalize=True, label="修改标注"):
        prepared = []
        for image in images:
            candidate = deepcopy(image)
            operation(candidate)
            if finalize:
                ReviewManager(self.review_manager.current_user).finalize_image(candidate)
            prepared.append((image, candidate, self._snapshot(image)))
        failures = []
        committed = []
        for image, candidate, snapshot in prepared:
            if JsonManager.save_image_data(candidate):
                image.__dict__.update(candidate.__dict__)
                committed.append(snapshot)
            else:
                failures.append(image.json_path)
        if committed:
            self._undo_history.append((label, committed))
        self._rebuild_defects()
        if failures:
            raise OSError("以下图片保存失败，失败项保留原数据：\n" + "\n".join(failures))

    @staticmethod
    def _annotations(image, annotation_ids):
        annotations = [annotation for annotation in image.annotations if annotation.id in annotation_ids]
        if len(annotations) != len(set(annotation_ids)) or not annotations:
            raise ValueError("请重新选择当前图片中的检测框")
        return annotations

    def review(self, image, annotation_ids, review_type):
        def operation(candidate):
            for annotation in self._annotations(candidate, annotation_ids):
                annotation.set_review(review_type)
        self._edit([image], operation, label=f"审核 {len(annotation_ids)} 个检测框：{review_type.display_name}")

    def change_class(self, image, annotation_ids, class_name):
        class_name = class_name.strip()
        if not class_name:
            raise ValueError("类别不能为空")
        def operation(candidate):
            for annotation in self._annotations(candidate, annotation_ids):
                annotation.change_class(class_name)
        self._edit([image], operation, label="修改类别")

    def add_box(self, image, bbox, class_name):
        left, right = sorted((max(0, min(image.width, bbox[0])), max(0, min(image.width, bbox[2]))))
        top, bottom = sorted((max(0, min(image.height, bbox[1])), max(0, min(image.height, bbox[3]))))
        if right - left < 5 or bottom - top < 5:
            raise ValueError("检测框过小，请在图片内重新框选")
        created = []
        def operation(candidate):
            manager = AnnotationManager()
            manager.set_image(candidate)
            annotation = manager.add_box([left, top, right, bottom], class_name)
            annotation.set_review(ReviewType.MISS)
            created.append(annotation.id)
        self._edit([image], operation, label="新增检测框")
        return created[0]

    def delete_annotations(self, image, annotation_ids):
        def operation(candidate):
            self._annotations(candidate, annotation_ids)
            candidate.annotations = [annotation for annotation in candidate.annotations if annotation.id not in annotation_ids]
        self._edit([image], operation, label=f"删除 {len(annotation_ids)} 个检测框")

    def bind(self, image, annotation_ids, defect_id=None, class_name="", description=""):
        part = self.project.get_part(image.part_id)
        existing = part.get_defect(defect_id) if defect_id else None
        if defect_id and existing is None:
            raise ValueError("缺陷实例不属于当前零件")
        target_id = defect_id or "DEF_" + uuid4().hex
        def operation(candidate):
            for annotation in self._annotations(candidate, annotation_ids):
                if annotation.defect_id and annotation.defect_id != target_id:
                    raise ValueError("检测框已有缺陷关联，请先解除绑定")
                annotation.set_defect(target_id)
                annotation.defect_class = existing.class_name if existing else class_name or annotation.review_class or annotation.class_name
                annotation.defect_description = existing.description if existing else description
        self._edit([image], operation, label="绑定缺陷实例")
        defect = part.get_defect(target_id)
        if not existing:
            defect.description = description
        return target_id

    def unbind(self, image, annotation_ids):
        def operation(candidate):
            for annotation in self._annotations(candidate, annotation_ids):
                annotation.set_defect(None)
        self._edit([image], operation, label="解除缺陷关联")

    def delete_defect(self, part_id, defect_id):
        part = self.project.get_part(part_id)
        if not part or not part.get_defect(defect_id):
            raise ValueError("缺陷实例不存在")
        images = [image for image in part.images if any(annotation.defect_id == defect_id for annotation in image.annotations)]
        def operation(candidate):
            for annotation in candidate.annotations:
                if annotation.defect_id == defect_id:
                    annotation.set_defect(None)
        self._edit(images, operation, label="删除缺陷实例")

    def mark_empty(self, image):
        if image.is_ever_reviewed():
            raise ValueError("该图片已有审核记录，无需重复标记")
        def operation(candidate):
            candidate.annotations = []
            candidate.review_status_text = "finished"
        self._edit([image], operation, label="标记无识别目标")

    def clear_image(self, image):
        snapshot = self._snapshot(image)
        if os.path.exists(image.json_path):
            os.unlink(image.json_path)
        image.annotations = []
        image.review_user = ""
        image.review_time = ""
        image.review_status_text = "unreviewed"
        image.image_status = "unknown"
        image.part_status = "unknown"
        self._undo_history.append(("清空图片审核", [snapshot]))
        self._rebuild_defects()
