import cv2
import numpy as np
from sklearn.cluster import KMeans


def _iou(a: list[int], b: list[int]) -> float:
    x0, y0 = max(a[0], b[0]), max(a[1], b[1])
    x1, y1 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0, x1 - x0) * max(0, y1 - y0)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union else 0.0


def _merge_boxes(boxes: list[list[int]], thresh: float = 0.3) -> list[list[int]]:
    """Iteratively merge boxes with IoU > thresh until no pair overlaps."""
    boxes = [list(b) for b in boxes]
    i = 0
    while i < len(boxes):
        for j in range(i + 1, len(boxes)):
            if _iou(boxes[i], boxes[j]) > thresh:
                a, b = boxes[i], boxes.pop(j)
                boxes[i] = [
                    min(a[0], b[0]),
                    min(a[1], b[1]),
                    max(a[2], b[2]),
                    max(a[3], b[3]),
                ]
                i = -1
                break
        i += 1
    return boxes


def segment(enhanced_bytes: bytes, clean_binary: np.ndarray, k: int = 5) -> list[bytes]:
    """Split the diagram into k regions clustered around areas of high
    structural detail (corners in the cleaned binary mask)."""
    h, w = clean_binary.shape

    contours, _ = cv2.findContours(clean_binary, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    points = []
    for c in contours:
        approx = cv2.approxPolyDP(c, 0.02 * cv2.arcLength(c, True), True)
        points.extend(approx.reshape(-1, 2))

    roi_mask = np.zeros_like(clean_binary)
    for x, y in points:
        x0, x1 = max(0, x - 30), min(w, x + 31)
        y0, y1 = max(0, y - 30), min(h, y + 31)
        roi_mask[y0:y1, x0:x1] = clean_binary[y0:y1, x0:x1]

    roi_contours, _ = cv2.findContours(
        roi_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    roi_contours = sorted(roi_contours, key=cv2.contourArea, reverse=True)[:100]

    pad = 200
    boxes = []
    for c in roi_contours:
        x, y, bw, bh = cv2.boundingRect(c)
        boxes.append(
            [
                max(0, x - pad),
                max(0, y - pad),
                min(w, x + bw + pad),
                min(h, y + bh + pad),
            ]
        )

    if not boxes:
        return [enhanced_bytes]

    boxes = _merge_boxes(boxes)

    centroids = np.array([[(b[0] + b[2]) / 2, (b[1] + b[3]) / 2] for b in boxes])
    n_clusters = min(k, len(boxes))
    labels = KMeans(n_clusters=n_clusters, n_init=10, random_state=0).fit_predict(
        centroids
    )

    img = cv2.imdecode(np.frombuffer(enhanced_bytes, np.uint8), cv2.IMREAD_COLOR)
    regions = []
    for cluster in range(n_clusters):
        cluster_boxes = [b for b, lab in zip(boxes, labels) if lab == cluster]
        x0 = min(b[0] for b in cluster_boxes)
        y0 = min(b[1] for b in cluster_boxes)
        x1 = max(b[2] for b in cluster_boxes)
        y1 = max(b[3] for b in cluster_boxes)
        _, buf = cv2.imencode(".png", img[y0:y1, x0:x1])
        regions.append(buf.tobytes())

    return regions
