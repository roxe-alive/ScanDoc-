# plugins/scanner.py

import os
import cv2
import uuid
import shutil
import numpy as np

from PIL import Image
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader

from pyrogram import filters
from dotsermodz import app


TEMP_DIR = "scanner_temp"
os.makedirs(TEMP_DIR, exist_ok=True)


# ============================================================
# POINT ORDERING
# ============================================================

def order_points(points):
    points = np.array(points, dtype=np.float32)

    rect = np.zeros((4, 2), dtype=np.float32)

    s = points.sum(axis=1)
    d = np.diff(points, axis=1)

    rect[0] = points[np.argmin(s)]   # Top-left
    rect[1] = points[np.argmin(d)]   # Top-right
    rect[2] = points[np.argmax(s)]   # Bottom-right
    rect[3] = points[np.argmax(d)]   # Bottom-left

    return rect


# ============================================================
# PERSPECTIVE TRANSFORM
# ============================================================

def perspective_crop(image, points):

    rect = order_points(points)

    tl, tr, br, bl = rect

    width1 = np.linalg.norm(br - bl)
    width2 = np.linalg.norm(tr - tl)

    height1 = np.linalg.norm(tr - br)
    height2 = np.linalg.norm(tl - bl)

    width = int(max(width1, width2))
    height = int(max(height1, height2))

    width = max(width, 1)
    height = max(height, 1)

    destination = np.array([
        [0, 0],
        [width - 1, 0],
        [width - 1, height - 1],
        [0, height - 1]
    ], dtype=np.float32)

    matrix = cv2.getPerspectiveTransform(
        rect,
        destination
    )

    return cv2.warpPerspective(
        image,
        matrix,
        (width, height)
    )


# ============================================================
# DOCUMENT DETECTION
# ============================================================

def detect_document(image):

    original_h, original_w = image.shape[:2]

    max_width = 1600

    scale = 1.0

    if original_w > max_width:

        scale = max_width / original_w

        small = cv2.resize(
            image,
            None,
            fx=scale,
            fy=scale,
            interpolation=cv2.INTER_AREA
        )

    else:
        small = image.copy()

    gray = cv2.cvtColor(
        small,
        cv2.COLOR_BGR2GRAY
    )

    # Smooth image
    gray = cv2.GaussianBlur(
        gray,
        (5, 5),
        0
    )

    # Edge detection
    edges = cv2.Canny(
        gray,
        50,
        150
    )

    # Close broken edges
    kernel = cv2.getStructuringElement(
        cv2.MORPH_RECT,
        (5, 5)
    )

    edges = cv2.morphologyEx(
        edges,
        cv2.MORPH_CLOSE,
        kernel,
        iterations=2
    )

    contours, _ = cv2.findContours(
        edges,
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_SIMPLE
    )

    image_area = small.shape[0] * small.shape[1]

    candidates = []

    for contour in contours:

        area = cv2.contourArea(contour)

        # Document should occupy a reasonable portion
        if area < image_area * 0.12:
            continue

        perimeter = cv2.arcLength(
            contour,
            True
        )

        approx = cv2.approxPolyDP(
            contour,
            0.02 * perimeter,
            True
        )

        if len(approx) != 4:
            continue

        x, y, w, h = cv2.boundingRect(
            approx
        )

        if w < 150 or h < 150:
            continue

        rectangularity = area / float(w * h)

        if rectangularity < 0.45:
            continue

        candidates.append(
            (
                area,
                approx.reshape(4, 2)
            )
        )

    if not candidates:
        return None

    # Largest rectangle
    candidates.sort(
        key=lambda x: x[0],
        reverse=True
    )

    points = candidates[0][1]

    # Convert coordinates to original image
    if scale != 1.0:
        points = points / scale

    return points.astype(np.float32)


# ============================================================
# SAFE FALLBACK CROP
# ============================================================

def fallback_crop(image):

    h, w = image.shape[:2]

    margin_x = int(w * 0.015)
    margin_y = int(h * 0.015)

    return image[
        margin_y:h - margin_y,
        margin_x:w - margin_x
    ]


# ============================================================
# SCANNER ENHANCEMENT
# ============================================================

def enhance_scan(image):

    # Convert to LAB
    lab = cv2.cvtColor(
        image,
        cv2.COLOR_BGR2LAB
    )

    l, a, b = cv2.split(lab)

    # Improve document contrast
    clahe = cv2.createCLAHE(
        clipLimit=2.0,
        tileGridSize=(8, 8)
    )

    l = clahe.apply(l)

    enhanced = cv2.merge([
        l,
        a,
        b
    ])

    enhanced = cv2.cvtColor(
        enhanced,
        cv2.COLOR_LAB2BGR
    )

    # Slight sharpening
    kernel = np.array([
        [0, -1, 0],
        [-1, 5, -1],
        [0, -1, 0]
    ])

    enhanced = cv2.filter2D(
        enhanced,
        -1,
        kernel
    )

    return enhanced


# ============================================================
# A4 PDF
# ============================================================

def create_pdf(image_path, pdf_path):

    image = Image.open(
        image_path
    ).convert("RGB")

    width, height = image.size

    page_width, page_height = A4

    margin = 18

    available_width = (
        page_width - margin * 2
    )

    available_height = (
        page_height - margin * 2
    )

    scale = min(
        available_width / width,
        available_height / height
    )

    draw_width = width * scale
    draw_height = height * scale

    x = (
        page_width - draw_width
    ) / 2

    y = (
        page_height - draw_height
    ) / 2

    pdf = canvas.Canvas(
        pdf_path,
        pagesize=A4
    )

    pdf.drawImage(
        ImageReader(image),
        x,
        y,
        width=draw_width,
        height=draw_height,
        preserveAspectRatio=True,
        mask="auto"
    )

    pdf.showPage()
    pdf.save()


# ============================================================
# PHOTO HANDLER
# ============================================================

@app.on_message(
    filters.photo
)
async def scan_photo(client, message):

    job_id = uuid.uuid4().hex[:10]

    job_dir = os.path.join(
        TEMP_DIR,
        job_id
    )

    os.makedirs(
        job_dir,
        exist_ok=True
    )

    original = os.path.join(
        job_dir,
        "original.jpg"
    )

    scanned = os.path.join(
        job_dir,
        "scanned.jpg"
    )

    pdf = os.path.join(
        job_dir,
        "scanned.pdf"
    )

    status = await message.reply_text(
        "📄 **Scanning...**\n\n"
        "⬇️ Downloading image..."
    )

    try:

        # ----------------------------------------------------
        # DOWNLOAD
        # ----------------------------------------------------

        await message.download(
            file_name=original
        )

        await status.edit_text(
            "📄 **Scanning...**\n\n"
            "🔍 Detecting document border..."
        )

        # ----------------------------------------------------
        # READ IMAGE
        # ----------------------------------------------------

        image = cv2.imread(
            original
        )

        if image is None:
            raise Exception(
                "Unable to read image."
            )

        # ----------------------------------------------------
        # DETECT DOCUMENT
        # ----------------------------------------------------

        points = detect_document(
            image
        )

        if points is not None:

            await status.edit_text(
                "📄 **Scanning...**\n\n"
                "✂️ Document detected\n"
                "📐 Correcting perspective..."
            )

            result = perspective_crop(
                image,
                points
            )

            detected = True

        else:

            await status.edit_text(
                "📄 **Scanning...**\n\n"
                "⚠️ Border not detected\n"
                "✂️ Applying safe crop..."
            )

            result = fallback_crop(
                image
            )

            detected = False

        # ----------------------------------------------------
        # ENHANCE
        # ----------------------------------------------------

        await status.edit_text(
            "📄 **Scanning...**\n\n"
            "✨ Enhancing document..."
        )

        result = enhance_scan(
            result
        )

        cv2.imwrite(
            scanned,
            result,
            [
                cv2.IMWRITE_JPEG_QUALITY,
                95
            ]
        )

        # ----------------------------------------------------
        # CREATE PDF
        # ----------------------------------------------------

        await status.edit_text(
            "📄 **Scanning...**\n\n"
            "📕 Creating A4 PDF..."
        )

        create_pdf(
            scanned,
            pdf
        )

        # ----------------------------------------------------
        # SEND
        # ----------------------------------------------------

        if detected:

            caption = (
                "📄 **Scanned Document**\n\n"
                "✅ Border detected\n"
                "✂️ Perfect crop\n"
                "📐 Perspective corrected\n"
                "✨ Scanner enhanced\n"
                "📕 A4 PDF"
            )

        else:

            caption = (
                "📄 **Scanned Document**\n\n"
                "⚠️ Document border could not "
                "be detected\n"
                "✂️ Safe crop applied\n"
                "✨ Scanner enhanced\n"
                "📕 A4 PDF"
            )

        await message.reply_document(
            document=pdf,
            caption=caption
        )

        await status.delete()

    except Exception as e:

        print(
            "[SCANNER ERROR]",
            repr(e)
        )

        try:

            await status.edit_text(
                "❌ **Scanner Error**\n\n"
                f"`{str(e)[:1500]}`"
            )

        except Exception:
            pass

    finally:

        # ----------------------------------------------------
        # DELETE TEMP FILES
        # ----------------------------------------------------

        try:

            shutil.rmtree(
                job_dir,
                ignore_errors=True
            )

        except Exception:
            pass