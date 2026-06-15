import cv2
import numpy as np


def preprocess(image_bytes: bytes) -> tuple[bytes, np.ndarray]:
    """
    Returns (enhanced_bytes, clean_binary).
    enhanced_bytes -> drop-in replacement for raw image bytes, send to Claude
    clean_binary   -> use later for segmentation and line detection
    """
    img = cv2.imdecode(np.frombuffer(image_bytes, np.uint8), cv2.IMREAD_COLOR)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # enhance contrast locally, denoise, sharpen
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    denoised = cv2.fastNlMeansDenoising(clahe.apply(gray), h=10)
    gaussian = cv2.GaussianBlur(denoised, (0, 0), 2.0)
    sharpened = cv2.addWeighted(denoised, 1.5, gaussian, -0.5, 0)

    # apply CLAHE to lightness channel of color image
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    lightness, a, b = cv2.split(lab)
    enhanced_color = cv2.cvtColor(
        cv2.merge([clahe.apply(lightness), a, b]), cv2.COLOR_LAB2BGR
    )

    # binary mask: threshold then remove small components (text/noise < 1000px)
    binary = cv2.adaptiveThreshold(
        sharpened, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 13, 2
    )
    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(binary)
    clean = np.zeros_like(binary)
    for i in range(1, num_labels):
        if stats[i, cv2.CC_STAT_AREA] > 1000:
            clean[labels == i] = 255

    _, buffer = cv2.imencode(".png", enhanced_color)
    return buffer.tobytes(), clean
