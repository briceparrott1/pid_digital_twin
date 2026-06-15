import logging

import cv2
import numpy as np

logger = logging.getLogger(__name__)


def _get_color(i: int) -> tuple[tuple[int, int, int], str]:
    hue = int((i * 137.508) % 180)
    sat = 200 + (i % 3) * 27
    val = 180 + (i % 2) * 50
    hsv = np.uint8([[[hue, sat, val]]])
    bgr = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)[0][0]
    return (int(bgr[0]), int(bgr[1]), int(bgr[2])), f"line_{i}"


def _merge_collinear(paths: list[tuple], delta: float) -> list[tuple]:
    """
    Merge segments that are truly collinear: same orientation, same axis
    position (within perp_tol), and overlapping or close along their length
    (within gap_tol). Avoids merging distinct parallel pipes.
    """
    perp_tol = 8  # how close perpendicular (same row/column)
    gap_tol = 30  # max gap along the line direction to bridge

    def orient(p):
        (x1, y1), (x2, y2) = p
        return "h" if abs(x2 - x1) >= abs(y2 - y1) else "v"

    segs = list(paths)
    changed = True
    while changed:
        changed = False
        out = []
        used = [False] * len(segs)
        for i in range(len(segs)):
            if used[i]:
                continue
            (x1s, y1s), (x1e, y1e) = segs[i]
            oi = orient(segs[i])
            for j in range(i + 1, len(segs)):
                if used[j]:
                    continue
                if orient(segs[j]) != oi:
                    continue
                (x2s, y2s), (x2e, y2e) = segs[j]
                if oi == "h":
                    if abs(((y1s + y1e) / 2) - ((y2s + y2e) / 2)) > perp_tol:
                        continue
                    a_lo, a_hi = min(x1s, x1e), max(x1s, x1e)
                    b_lo, b_hi = min(x2s, x2e), max(x2s, x2e)
                    if b_lo > a_hi + gap_tol or a_lo > b_hi + gap_tol:
                        continue
                    y = (y1s + y1e + y2s + y2e) // 4
                    segs[i] = ((min(a_lo, b_lo), y), (max(a_hi, b_hi), y))
                else:
                    if abs(((x1s + x1e) / 2) - ((x2s + x2e) / 2)) > perp_tol:
                        continue
                    a_lo, a_hi = min(y1s, y1e), max(y1s, y1e)
                    b_lo, b_hi = min(y2s, y2e), max(y2s, y2e)
                    if b_lo > a_hi + gap_tol or a_lo > b_hi + gap_tol:
                        continue
                    x = (x1s + x1e + x2s + x2e) // 4
                    segs[i] = ((x, min(a_lo, b_lo)), (x, max(a_hi, b_hi)))
                (x1s, y1s), (x1e, y1e) = segs[i]
                used[j] = True
                changed = True
            out.append(segs[i])
            used[i] = True
        segs = out
    return segs


def _is_pipe_angle(start, end, tol=8) -> bool:
    x1, y1 = start
    x2, y2 = end
    angle = abs(np.degrees(np.arctan2(y2 - y1, x2 - x1))) % 180
    return angle < tol or angle > (180 - tol) or abs(angle - 90) < tol


def _snap_to_axis(start, end):
    """Force a near-H or near-V line to be perfectly H or V."""
    x1, y1 = start
    x2, y2 = end
    if abs(x2 - x1) > abs(y2 - y1):  # horizontal — flatten y
        y_avg = (y1 + y2) // 2
        return (x1, y_avg), (x2, y_avg)
    else:  # vertical — flatten x
        x_avg = (x1 + x2) // 2
        return (x_avg, y1), (x_avg, y2)


def colorize_lines(
    enhanced_bytes: bytes, clean_binary: np.ndarray
) -> tuple[bytes, list[dict]]:
    """
    Pipe line detection: directional morphology to isolate pipes,
    HoughLinesP to extract segments, merge collinear, draw unique colors.
    Returns (color_coded_bytes, line_registry).
    """
    img = cv2.imdecode(np.frombuffer(enhanced_bytes, np.uint8), cv2.IMREAD_COLOR)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape

    # crop border (2%) and title block (bottom 5%)
    mx, my = int(w * 0.02), int(h * 0.02)
    img = img[my : int(h * 0.95), mx : w - mx]
    clean_binary = clean_binary[my : int(h * 0.95), mx : w - mx]
    ch, cw = clean_binary.shape

    # isolate horizontal + vertical pipe runs via directional morphology
    horiz_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 1))
    vert_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 15))
    horiz = cv2.morphologyEx(clean_binary, cv2.MORPH_OPEN, horiz_kernel)
    vert = cv2.morphologyEx(clean_binary, cv2.MORPH_OPEN, vert_kernel)
    line_mask = cv2.bitwise_or(horiz, vert)

    # extract line segments — mask is clean pipes so no false positives
    delta = 0.05 * min(ch, cw)
    raw_lines = cv2.HoughLinesP(
        line_mask,
        rho=1,
        theta=np.pi / 180,
        threshold=30,
        minLineLength=20,
        maxLineGap=15,
    )

    if raw_lines is None:
        _, buf = cv2.imencode(".png", img)
        return buf.tobytes(), []

    paths = [((ln[0][0], ln[0][1]), (ln[0][2], ln[0][3])) for ln in raw_lines]
    logger.debug("line detection — hough: %d", len(paths))

    # merge collinear segments, then keep horizontal/vertical only
    paths = _merge_collinear(paths, delta)
    logger.debug("line detection — after merge: %d", len(paths))
    paths = [p for p in paths if _is_pipe_angle(p[0], p[1])]
    logger.debug("line detection — after angle filter: %d", len(paths))

    if not paths:
        _, buf = cv2.imencode(".png", img)
        return buf.tobytes(), []

    # draw and register
    # draw and register
    line_registry = []
    for i, (start, end) in enumerate(paths):
        start, end = _snap_to_axis(start, end)
        color_bgr, color_name = _get_color(i)
        cv2.line(img, start, end, color_bgr, 2)
        mx = (start[0] + end[0]) // 2
        my = (start[1] + end[1]) // 2
        cv2.putText(
            img, color_name, (mx, my), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color_bgr, 1
        )
        line_registry.append(
            {
                "color_name": color_name,
                "color_bgr": color_bgr,
                "x1": int(start[0]),
                "y1": int(start[1]),
                "x2": int(end[0]),
                "y2": int(end[1]),
            }
        )

    _, buf = cv2.imencode(".png", img)
    return buf.tobytes(), line_registry
