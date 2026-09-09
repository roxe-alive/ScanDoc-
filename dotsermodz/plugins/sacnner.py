# plugins/scanner.py

import os
import uuid
import shutil
import cv2
import numpy as np

from PIL import Image, ImageEnhance, ImageFilter
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader

from pyrogram import filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from dotsermodz import app


TEMP_DIR = "scanner_temp"
os.makedirs(TEMP_DIR, exist_ok=True)

# job_id -> scan data
SCAN_JOBS = {}


# ============================================================
# KEYBOARD
# ============================================================

def scan_keyboard(job_id):

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🪄 Auto",
                callback_data=f"scan|auto|{job_id}"
            ),
            InlineKeyboardButton(
                "🎨 Color",
                callback_data=f"scan|color|{job_id}"
            )
        ],
        [
            InlineKeyboardButton(
                "⚫ B&W",
                callback_data=f"scan|bw|{job_id}"
            ),
            InlineKeyboardButton(
                "🌑 Gray",
                callback_data=f"scan|gray|{job_id}"
            )
        ],
        [
            InlineKeyboardButton(
                "✨ Enhance",
                callback_data=f"scan|enhance|{job_id}"
            ),
            InlineKeyboardButton(
                "✂️ Crop",
                callback_data=f"scan|crop|{job_id}"
            )
        ],
        [
            InlineKeyboardButton(
                "📕 Create PDF",
                callback_data=f"scan|pdf|{job_id}"
            )
        ],
        [
            InlineKeyboardButton(
                "❌ Cancel",
                callback_data=f"scan|cancel|{job_id}"
            )
        ]
    ])


# ============================================================
# ORDER FOUR POINTS
# ============================================================

def order_points(points):

    points = np.asarray(
        points,
        dtype=np.float32
    )

    result = np.zeros(
        (4, 2),
        dtype=np.float32
    )

    total = points.sum(axis=1)
    difference = np.diff(
        points,
        axis=1
    ).reshape(-1)

    result[0] = points[np.argmin(total)]       # TL
    result[1] = points[np.argmin(difference)]  # TR
    result[2] = points[np.argmax(total)]       # BR
    result[3] = points[np.argmax(difference)] # BL

    return result


# ============================================================
# FOUR POINT PERSPECTIVE
# ============================================================

def four_point_transform(image, points):

    rect = order_points(points)

    tl, tr, br, bl = rect

    width_a = np.linalg.norm(br - bl)
    width_b = np.linalg.norm(tr - tl)

    height_a = np.linalg.norm(tr - br)
    height_b = np.linalg.norm(tl - bl)

    width = max(
        int(round(width_a)),
        int(round(width_b))
    )

    height = max(
        int(round(height_a)),
        int(round(height_b))
    )

    if width < 10 or height < 10:
        return None

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
        (width, height),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE
    )


# ============================================================
# DOCUMENT DETECTION
# ============================================================

def detect_document(image):

    original = image

    h, w = image.shape[:2]

    # Resize only for detection
    max_width = 1800

    if w > max_width:

        scale = max_width / float(w)

        image = cv2.resize(
            image,
            None,
            fx=scale,
            fy=scale,
            interpolation=cv2.INTER_AREA
        )

    else:

        scale = 1.0

    gray = cv2.cvtColor(
        image,
        cv2.COLOR_BGR2GRAY
    )

    # Improve contrast
    gray = cv2.equalizeHist(gray)

    # Blur
    blur = cv2.GaussianBlur(
        gray,
        (5, 5),
        0
    )

    # Edges
    edges = cv2.Canny(
        blur,
        30,
        150
    )

    # Close broken borders
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
        cv2.RETR_LIST,
        cv2.CHAIN_APPROX_SIMPLE
    )

    image_area = (
        image.shape[0] *
        image.shape[1]
    )

    candidates = []

    # Largest contours first
    contours = sorted(
        contours,
        key=cv2.contourArea,
        reverse=True
    )

    for contour in contours[:100]:

        area = cv2.contourArea(
            contour
        )

        if area < image_area * 0.08:
            continue

        perimeter = cv2.arcLength(
            contour,
            True
        )

        # Try different approximations
        best = None

        for epsilon in (
            0.01,
            0.015,
            0.02,
            0.025,
            0.03,
            0.04,
            0.05
        ):

            approx = cv2.approxPolyDP(
                contour,
                epsilon * perimeter,
                True
            )

            if len(approx) == 4:

                candidate_area = cv2.contourArea(
                    approx
                )

                if candidate_area > 0:
                    best = approx
                    break

        if best is None:
            continue

        points = best.reshape(
            4,
            2
        ).astype(
            np.float32
        )

        # Convex quadrilateral
        if not cv2.isContourConvex(
            best
        ):
            continue

        x, y, cw, ch = cv2.boundingRect(
            best
        )

        if cw < 100 or ch < 100:
            continue

        rect_area = cw * ch

        rectangularity = (
            area / rect_area
            if rect_area
            else 0
        )

        if rectangularity < 0.35:
            continue

        # Don't require A4 ratio.
        # Square, portrait and landscape rectangles
        # are all accepted.

        # Avoid shapes touching the complete image edge
        touches_edges = (
            x <= 2 or
            y <= 2 or
            x + cw >= image.shape[1] - 2 or
            y + ch >= image.shape[0] - 2
        )

        # Slightly reduce score for full-image contour
        edge_penalty = 0.70 if touches_edges else 1.0

        score = (
            area *
            rectangularity *
            edge_penalty
        )

        candidates.append(
            (
                score,
                points
            )
        )

    if not candidates:
        return None

    candidates.sort(
        key=lambda x: x[0],
        reverse=True
    )

    points = candidates[0][1]

    # Convert back to original coordinates
    if scale != 1.0:
        points = points / scale

    # Safety check
    points[:, 0] = np.clip(
        points[:, 0],
        0,
        original.shape[1] - 1
    )

    points[:, 1] = np.clip(
        points[:, 1],
        0,
        original.shape[0] - 1
    )

    return points


# ============================================================
# FALLBACK CROP
# ============================================================

def fallback_crop(image):

    h, w = image.shape[:2]

    margin_x = max(
        int(w * 0.01),
        1
    )

    margin_y = max(
        int(h * 0.01),
        1
    )

    return image[
        margin_y:h - margin_y,
        margin_x:w - margin_x
    ].copy()


# ============================================================
# COLOR FILTER
# ============================================================

def color_filter(image):

    lab = cv2.cvtColor(
        image,
        cv2.COLOR_BGR2LAB
    )

    l, a, b = cv2.split(lab)

    clahe = cv2.createCLAHE(
        clipLimit=1.5,
        tileGridSize=(8, 8)
    )

    l = clahe.apply(l)

    result = cv2.merge([
        l,
        a,
        b
    ])

    result = cv2.cvtColor(
        result,
        cv2.COLOR_LAB2BGR
    )

    return result


# ============================================================
# GRAYSCALE
# ============================================================

def grayscale_filter(image):

    gray = cv2.cvtColor(
        image,
        cv2.COLOR_BGR2GRAY
    )

    clahe = cv2.createCLAHE(
        clipLimit=2.0,
        tileGridSize=(8, 8)
    )

    gray = clahe.apply(gray)

    return cv2.cvtColor(
        gray,
        cv2.COLOR_GRAY2BGR
    )


# ============================================================
# BLACK & WHITE
# ============================================================

def bw_filter(image):

    gray = cv2.cvtColor(
        image,
        cv2.COLOR_BGR2GRAY
    )

    # Normalize uneven lighting
    background = cv2.GaussianBlur(
        gray,
        (0, 0),
        21
    )

    background = np.maximum(
        background,
        1
    )

    normalized = cv2.divide(
        gray,
        background,
        scale=255
    )

    normalized = cv2.normalize(
        normalized,
        None,
        0,
        255,
        cv2.NORM_MINMAX
    )

    bw = cv2.adaptiveThreshold(
        normalized,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        31,
        10
    )

    # Remove small noise
    kernel = np.ones(
        (2, 2),
        np.uint8
    )

    bw = cv2.morphologyEx(
        bw,
        cv2.MORPH_OPEN,
        kernel
    )

    return cv2.cvtColor(
        bw,
        cv2.COLOR_GRAY2BGR
    )


# ============================================================
# ENHANCE
# ============================================================

def enhance_filter(image):

    result = color_filter(
        image
    )

    # Unsharp mask
    blurred = cv2.GaussianBlur(
        result,
        (0, 0),
        2
    )

    result = cv2.addWeighted(
        result,
        1.25,
        blurred,
        -0.25,
        0
    )

    return result


# ============================================================
# SAVE JPEG
# ============================================================

def save_image(image, path):

    success = cv2.imwrite(
        path,
        image,
        [
            cv2.IMWRITE_JPEG_QUALITY,
            95
        ]
    )

    if not success:
        raise RuntimeError(
            "Failed to save processed image."
        )


# ============================================================
# CREATE A4 PDF
# ============================================================

def create_pdf(image_path, pdf_path):

    image = Image.open(
        image_path
    ).convert("RGB")

    width, height = image.size

    page_width, page_height = A4

    margin = 18

    available_width = (
        page_width -
        (margin * 2)
    )

    available_height = (
        page_height -
        (margin * 2)
    )

    scale = min(
        available_width / width,
        available_height / height
    )

    draw_width = width * scale
    draw_height = height * scale

    x = (
        page_width -
        draw_width
    ) / 2

    y = (
        page_height -
        draw_height
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
# PREVIEW IMAGE
# ============================================================

async def send_preview(
    message,
    job,
    caption
):

    # Remove previous preview if possible
    old_message_id = job.get(
        "preview_message_id"
    )

    if old_message_id:

        try:

            await app.delete_messages(
                message.chat.id,
                old_message_id
            )

        except Exception:
            pass

    preview_message = await message.reply_photo(
        photo=job["result_path"],
        caption=caption,
        reply_markup=scan_keyboard(
            job["id"]
        )
    )

    job["preview_message_id"] = (
        preview_message.id
    )


# ============================================================
# PHOTO RECEIVER
# ============================================================

@app.on_message(
    filters.photo
)
async def scanner_photo(
    client,
    message
):

    job_id = uuid.uuid4().hex[:10]

    job_dir = os.path.join(
        TEMP_DIR,
        job_id
    )

    os.makedirs(
        job_dir,
        exist_ok=True
    )

    original_path = os.path.join(
        job_dir,
        "original.jpg"
    )

    result_path = os.path.join(
        job_dir,
        "result.jpg"
    )

    pdf_path = os.path.join(
        job_dir,
        "document.pdf"
    )

    status = None

    try:

        status = await message.reply_text(
            "📄 **Document Scanner**\n\n"
            "⬇️ Downloading image..."
        )

        await message.download(
            file_name=original_path
        )

        image = cv2.imread(
            original_path
        )

        if image is None:
            raise RuntimeError(
                "Could not read the image."
            )

        await status.edit_text(
            "🔍 **Identifying document...**\n\n"
            "Looking for square or rectangular "
            "borders..."
        )

        points = detect_document(
            image
        )

        if points is not None:

            cropped = four_point_transform(
                image,
                points
            )

            if cropped is None:
                cropped = fallback_crop(
                    image
                )

                detected = False

            else:
                detected = True

        else:

            cropped = fallback_crop(
                image
            )

            detected = False

        # Initial Auto filter
        result = color_filter(
            cropped
        )

        save_image(
            result,
            result_path
        )

        SCAN_JOBS[job_id] = {
            "id": job_id,
            "user_id": (
                message.from_user.id
                if message.from_user
                else 0
            ),
            "chat_id": message.chat.id,
            "original": image,
            "cropped": cropped,
            "result": result,
            "result_path": result_path,
            "pdf_path": pdf_path,
            "detected": detected,
            "filter": "auto",
            "preview_message_id": None,
            "directory": job_dir
        }

        detection_text = (
            "✅ Square/rectangle detected"
            if detected
            else
            "⚠️ Border not confidently detected"
        )

        await status.delete()

        caption = (
            "📄 **Document Identified**\n\n"
            f"{detection_text}\n"
            "📐 Perspective corrected\n"
            "✂️ Automatic crop applied\n\n"
            "Choose a filter or enhancement:"
        )

        await send_preview(
            message,
            SCAN_JOBS[job_id],
            caption
        )

    except Exception as e:

        print(
            "[SCANNER PHOTO ERROR]",
            repr(e)
        )

        if status:

            try:

                await status.edit_text(
                    "❌ **Scanner Error**\n\n"
                    f"`{str(e)[:1500]}`"
                )

            except Exception:
                pass

        shutil.rmtree(
            job_dir,
            ignore_errors=True
        )


# ============================================================
# CALLBACK
# ============================================================

@app.on_callback_query(
    filters.regex(r"^scan\|")
)
async def scanner_callback(
    client,
    callback_query
):

    try:

        parts = callback_query.data.split(
            "|"
        )

        if len(parts) != 3:
            await callback_query.answer(
                "Invalid scanner action.",
                show_alert=True
            )
            return

        _, action, job_id = parts

        job = SCAN_JOBS.get(
            job_id
        )

        if not job:

            await callback_query.answer(
                "This scan has expired.",
                show_alert=True
            )

            return

        user_id = (
            callback_query.from_user.id
            if callback_query.from_user
            else 0
        )

        if user_id != job["user_id"]:

            await callback_query.answer(
                "This scan belongs to another user.",
                show_alert=True
            )

            return

        # ----------------------------------------------------
        # CANCEL
        # ----------------------------------------------------

        if action == "cancel":

            await callback_query.answer(
                "Scan cancelled."
            )

            try:
                await callback_query.message.delete()
            except Exception:
                pass

            shutil.rmtree(
                job["directory"],
                ignore_errors=True
            )

            SCAN_JOBS.pop(
                job_id,
                None
            )

            return

        # ----------------------------------------------------
        # PDF
        # ----------------------------------------------------

        if action == "pdf":

            await callback_query.answer(
                "Creating PDF..."
            )

            await callback_query.message.edit_caption(
                caption="📕 **Creating PDF...**"
            )

            create_pdf(
                job["result_path"],
                job["pdf_path"]
            )

            await callback_query.message.reply_document(
                document=job["pdf_path"],
                caption=(
                    "📄 **Scanned PDF**\n\n"
                    "✅ Document identified\n"
                    "✂️ Border crop\n"
                    "📐 Perspective correction\n"
                    f"🎨 Filter: {job['filter'].title()}\n"
                    "📕 A4 PDF"
                )
            )

            try:
                await callback_query.message.delete()
            except Exception:
                pass

            shutil.rmtree(
                job["directory"],
                ignore_errors=True
            )

            SCAN_JOBS.pop(
                job_id,
                None
            )

            return

        # ----------------------------------------------------
        # CROP
        # ----------------------------------------------------

        if action == "crop":

            if job["detected"]:

                cropped = job["cropped"].copy()

            else:

                cropped = fallback_crop(
                    job["original"]
                )

            job["cropped"] = cropped
            job["result"] = cropped.copy()
            job["filter"] = "crop"

            save_image(
                job["result"],
                job["result_path"]
            )

            await callback_query.answer(
                "Crop applied."
            )

            caption = (
                "✂️ **Crop Applied**\n\n"
                "✅ Document border processed\n"
                "📐 Perspective corrected\n\n"
                "Choose another filter or create PDF:"
            )

            await callback_query.message.delete()

            await send_preview(
                callback_query.message,
                job,
                caption
            )

            return

        # ----------------------------------------------------
        # FILTER
        # ----------------------------------------------------

        base = job["cropped"]

        if action == "auto":

            result = color_filter(
                base
            )

        elif action == "color":

            result = color_filter(
                base
            )

        elif action == "gray":

            result = grayscale_filter(
                base
            )

        elif action == "bw":

            result = bw_filter(
                base
            )

        elif action == "enhance":

            result = enhance_filter(
                base
            )

        else:

            await callback_query.answer(
                "Unknown filter.",
                show_alert=True
            )

            return

        job["result"] = result
        job["filter"] = action

        save_image(
            result,
            job["result_path"]
        )

        await callback_query.answer(
            f"{action.title()} applied."
        )

        try:
            await callback_query.message.delete()
        except Exception:
            pass

        caption = (
            "📄 **Scan Preview**\n\n"
            "✅ Border identified\n"
            "✂️ Perspective crop\n"
            f"🎨 Filter: **{action.title()}**\n\n"
            "Select another filter or create PDF:"
        )

        await send_preview(
            callback_query.message,
            job,
            caption
        )

    except Exception as e:

        print(
            "[SCANNER CALLBACK ERROR]",
            repr(e)
        )

        try:

            await callback_query.answer(
                "Processing failed.",
                show_alert=True
            )

        except Exception:
            pass