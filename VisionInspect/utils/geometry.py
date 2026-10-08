"""几何工具：bbox 转换、IOU 计算等."""


def points_to_bbox(points) -> list:
    """将 LabelMe 格式的点列表 [[x1,y1],[x2,y2]] 转换为 [x1,y1,x2,y2].

    Args:
        points: 两个点 [[x1,y1],[x2,y2]]

    Returns:
        [x1, y1, x2, y2] （自动归一化为左上/右下）
    """
    if not points or len(points) < 2:
        return [0, 0, 0, 0]
    x1, y1 = points[0]
    x2, y2 = points[1]
    return [min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)]


def bbox_to_points(bbox) -> list:
    """将 [x1,y1,x2,y2] 转换为 LabelMe 点格式 [[x1,y1],[x2,y2]].

    Args:
        bbox: [x1, y1, x2, y2]

    Returns:
        [[x1,y1],[x2,y2]]
    """
    if not bbox or len(bbox) < 4:
        return [[0, 0], [0, 0]]
    return [[bbox[0], bbox[1]], [bbox[2], bbox[3]]]


def bbox_area(bbox) -> float:
    """计算 bbox 面积."""
    if not bbox or len(bbox) < 4:
        return 0.0
    w = max(0.0, bbox[2] - bbox[0])
    h = max(0.0, bbox[3] - bbox[1])
    return w * h


def bbox_iou(box1, box2) -> float:
    """计算两个 bbox 的 IoU（Intersection over Union）.

    Args:
        box1: [x1,y1,x2,y2]
        box2: [x1,y1,x2,y2]

    Returns:
        IoU 值 0.0~1.0
    """
    if not box1 or not box2 or len(box1) < 4 or len(box2) < 4:
        return 0.0

    x1 = max(box1[0], box2[0])
    y1 = max(box1[1], box2[1])
    x2 = min(box1[2], box2[2])
    y2 = min(box1[3], box2[3])

    inter_w = max(0.0, x2 - x1)
    inter_h = max(0.0, y2 - y1)
    inter_area = inter_w * inter_h

    area1 = bbox_area(box1)
    area2 = bbox_area(box2)
    union = area1 + area2 - inter_area
    if union <= 0:
        return 0.0
    return inter_area / union


# 兼容别名
bb_intersection_over_union = bbox_iou


def clamp_bbox(bbox, width, height):
    """将 bbox 限制在图片范围内.

    Returns:
        [x1,y1,x2,y2] 或 None（无效框）
    """
    x1 = max(0, int(bbox[0]))
    y1 = max(0, int(bbox[1]))
    x2 = min(width, int(bbox[2]))
    y2 = min(height, int(bbox[3]))
    if x2 <= x1 or y2 <= y1:
        return None
    return [x1, y1, x2, y2]