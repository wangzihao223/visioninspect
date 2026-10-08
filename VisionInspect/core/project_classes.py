"""Project-specific review categories."""

import json
from pathlib import Path

from storage.json_reader import JsonManager

CLASSES_FILENAME = ".visioninspect-classes.json"


def normalize_classes(values):
    return list(dict.fromkeys(value.strip() for value in values if value.strip()))


def load_project_classes(project):
    path = Path(project.root_path) / CLASSES_FILENAME
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        values = data["classes"]
        if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
            raise ValueError("classes 必须是类别名称列表")
        classes = normalize_classes(values)
        if not classes:
            raise ValueError("至少需要一个类别")
        return classes
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ValueError(f"项目类别配置读取失败：{path}\n{exc}") from exc


def detected_classes(project):
    values = []
    for part in project.parts:
        for image in part.images:
            for annotation in image.annotations:
                values.extend((annotation.review_class, annotation.class_name))
    if project.model_info:
        values.extend(project.model_info.classes)
    return normalize_classes(values)


def available_classes(project):
    if project is None:
        return []
    return list(project.review_classes) if project.review_classes is not None else detected_classes(project)


def save_project_classes(project, values):
    classes = normalize_classes(values)
    if not classes:
        raise ValueError("至少填写一个类别，每行一个")
    path = Path(project.root_path) / CLASSES_FILENAME
    if not JsonManager.write_json(str(path), {"version": 1, "classes": classes}):
        raise OSError(f"项目类别保存失败：{path}")
    project.review_classes = classes
