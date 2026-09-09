# plugins/scanner.py

import os
import cv2
import uuid
import shutil
import asyncio
import numpy as np


from PIL import Image
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader

from pyrogram import filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from dotsermodz import app


TEMP_DIR = "scanner_temp"
os.makedirs(TEMP_DIR, exist_ok=True)

# Active scanning jobs
SCAN_JOBS = {}


# ============================================================
# POINT ORDERING
# ============================================================

def order_points(points):

    points = np.array(points, dtype=np.float32)

    rect = np.zeros((4, 2), dtype=np.float32)

    s = points.sum(axis=1)
    d = np.diff(points, axis=1)

    rect[0] = points[np.argmin(s)]      # TL
    rect[1] = points[np.argmin(d)]      # TR
    rect[2] = points[np.argmax(s)]      # BR
    rect[3] = points[np.argmax(d)]      # BL

    return rect


# ============================================================
# PERSPECTIVE CROP
# ============================================================

def perspective_crop(image, points):

    rect = order_points(points)

    tl, tr, br, bl = rect

    width_a = np.linalg.norm(br - bl)
    width_b = np.linalg.norm(tr - tl)

    height_a = np.linalg.norm(tr - br)
    height_b = np.linalg.norm(tl - bl)

    width = int(max(width_a, width_b))
    height = int(max(height_a, height_b))

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

    max_width = 1800

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

    # Noise reduction
    blur = cv2.GaussianBlur(
        gray,
        (5, 5),
        0
    )

    # Strong edges
    edges = cv2.Canny(
        blur,
        40,
        150
    )

    # Connect border gaps
    kernel = cv2.getStructuringElement(
        cv2.MORPH_RECT,
        (7, 7)
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

    image_area = small.shape[0] * small.shape[1]

    candidates = []

    for contour in contours:

        area = cv2.contourArea(contour)

        # Allow both small-ish and large documents
        if area < image_area * 0.08:
            continue

        perimeter = cv2.arcLength(
            contour,
            True
        )

        # Try several approximation levels
        found = None

        for epsilon_factor in (
            0.01,
            0.015,
            0.02,
            0.025,
            0.03,
            0.04
        ):

            approx = cv2.approxPolyDP(
                contour,
                epsilon_factor * perimeter,
                True
            )

            if len(approx) == 4:
                found = approx
                break

        if found is None:
            continue

        points = found.reshape(4, 2)

        x, y, w, h = cv2.boundingRect(
            found
        )

        if w < 100 or h < 100:
            continue

        rectangularity = area / float(
            max(w * h, 1)
        )

        if rectangularity < 0.40:
            continue

        # Check whether the shape is reasonably quadrilateral.
        # This allows square and arbitrary rectangle ratios.
        sides = []

        ordered = order_points(points)

        for i in range(4):

            p1 = ordered[i]
            p2 = ordered[(i + 1) % 4]

            sides.append(
                np.linalg.norm(p2 - p1)
            )

        if min(sides) < 50:
            continue

        # Score:
        # larger area = better
        # rectangularity = better
        score = (
            area *
            (0.5 + rectangularity)
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

    if scale != 1.0:
        points = points / scale

    return points.astype(
        np.float32
    )


# ============================================================
# FALLBACK CROP
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
# FILTERS
# ============================================================

def filter_original(image):

    return image


def filter_color(image):

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

    return cv2.cvtColor(
        result,
        cv2.COLOR_LAB2BGR
    )


def filter_grayscale(image):

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


def filter_bw(image):

    gray = cv2.cvtColor(
        image,
        cv2.COLOR_BGR2GRAY
    )

    # Normalize lighting
    background = cv2.GaussianBlur(
        gray,
        (0, 0),
        21
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

    # Remove tiny noise
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
# ENHANCEMENT
# ============================================================

def enhance_image(image):

    # Work in LAB
    lab = cv2.cvtColor(
        image,
        cv2.COLOR_BGR2LAB
    )

    l, a, b = cv2.split(lab)

    clahe = cv2.createCLAHE(
        clipLimit=2.5,
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

    # Mild sharpening
    kernel = np.array([
        [0, -1, 0],
        [-1, 5, -1],
        [0, -1, 0]
    ])

    result = cv2.filter2D(
        result,
        -1,
        kernel
    )

    return result


# ============================================================
# IMAGE SAVE
# ============================================================

def save_image(image, path):

    cv2.imwrite(
        path,
        image,
        [
            cv2.IMWRITE_JPEG_QUALITY,
            95
        ]
    )


# ============================================================
# PDF
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
# FILTER KEYBOARD
# ============================================================

def filter_keyboard():

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🪄 Auto",
                callback_data="scan:auto"
            ),
            InlineKeyboardButton(
                "🎨 Color",
                callback_data="scan:color"
            )
        ],
        [
            InlineKeyboardButton(
                "⚫ B&W",
                callback_data="scan:bw"
            ),
            InlineKeyboardButton(
                "🌑 Gray",
                callback_data="scan:gray"
            )
        ],
        [
            InlineKeyboardButton(
                "✨ Enhance",
                callback_data="scan:enhance"
            ),
            InlineKeyboardButton(
                "✂️ Crop",
                callback_data="scan:crop"
            )
        ],
        [
            InlineKeyboardButton(
                "📕 Create PDF",
                callback_data="scan:pdf"
            )
        ],
        [
            InlineKeyboardButton(
                "❌ Cancel",
                callback_data="scan:cancel"
            )
        ]
    ])


# ============================================================
# PHOTO HANDLER
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

    processed_path = os.path.join(
        job_dir,
        "processed.jpg"
    )

    pdf_path = os.path.join(
        job_dir,
        "document.pdf"
    )

    try:

        status = await message.reply_text(
            "📄 **Preparing scanner...**\n\n"
            "⬇️ Downloading image..."
        )

        await message.download(
            file_name=original_path
        )

        image = cv2.imread(
            original_path
        )

        if image is None:
            raise Exception(
                "Unable to read the image."
            )

        await status.edit_text(
            "🔍 **Identifying document...**\n\n"
            "Searching for square / rectangular borders..."
        )

        points = detect_document(
            image
        )

        if points is not None:

            cropped = perspective_crop(
                image,
                points
            )

            detection = (
                "✅ Square/rectangle border detected"
            )

        else:

            cropped = fallback_crop(
                image
            )

            detection = (
                "⚠️ Border not confidently detected"
            )

        # Save initial auto result
        save_image(
            cropped,
            processed_path
        )

        # Store job
        SCAN_JOBS[job_id] = {
            "user_id": message.from_user.id,
            "chat_id": message.chat.id,
            "original": image,
            "cropped": cropped,
            "result": cropped.copy(),
            "path": processed_path,
            "pdf": pdf_path,
            "detected": points is not None,
            "filter": "auto"
        }

        await status.edit_text(
            f"📄 **Document identified**\n\n"
            f"{detection}\n"
            f"✂️ Perspective crop ready\n\n"
            f"**Choose a filter or enhancement:**",
            reply_markup=filter_keyboard()
        )

    except Exception as e:

        print(
            "[SCANNER ERROR]",
            repr(e)
        )

        await message.reply_text(
            "❌ Scanner error:\n\n"
            f"`{str(e)[:1500]}`"
        )

        shutil.rmtree(
            job_dir,
            ignore_errors=True
        )


# ============================================================
# CALLBACK HANDLER
# ============================================================

@app.on_callback_query(
    filters.regex(r"^scan:")
)
async def scanner_callback(
    client,
    callback_query
):

    data = callback_query.data

    action = data.split(
        ":",
        1
    )[1]

    # Find user's job
    job_id = None

    for jid, job in SCAN_JOBS.items():

        if (
            job["user_id"]
            == callback_query.from_user.id
            and job["chat_id"]
            == callback_query.message.chat.id
        ):
            job_id = jid
            break

    if not job_id:

        await callback_query.answer(
            "This scan has expired.",
            show_alert=True
        )

        return

    job = SCAN_JOBS[job_id]

    try:

        # ----------------------------------------------------
        # CANCEL
        # ----------------------------------------------------

        if action == "cancel":

            await callback_query.message.edit_text(
                "❌ **Scan cancelled.**"
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

                job["result"] = job["cropped"].copy()

                await callback_query.answer(
                    "Automatic border crop applied."
                )

            else:

                job["result"] = fallback_crop(
                    job["original"]
                )

                await callback_query.answer(
                    "Safe crop applied."
                )

            save_image(
                job["result"],
                job["path"]
            )

            await callback_query.message.edit_text(
                "✂️ **Crop applied**\n\n"
                "The document border has been cropped "
                "and perspective corrected.\n\n"
                "Choose another filter or create PDF:",
                reply_markup=filter_keyboard()
            )

            return

        # ----------------------------------------------------
        # FILTER
        # ----------------------------------------------------

        if action == "auto":

            result = job["cropped"].copy()

        elif action == "color":

            result = filter_color(
                job["cropped"]
            )

        elif action == "gray":

            result = filter_grayscale(
                job["cropped"]
            )

        elif action == "bw":

            result = filter_bw(
                job["cropped"]
            )

        elif action == "enhance":

            result = enhance_image(
                job["cropped"]
            )

        # ----------------------------------------------------
        # PDF
        # ----------------------------------------------------

        elif action == "pdf":

            save_image(
                job["result"],
                job["path"]
            )

            await callback_query.message.edit_text(
                "📕 **Creating PDF...**"
            )

            create_pdf(
                job["path"],
                job["pdf"]
            )

            await callback_query.message.reply_document(
                document=job["pdf"],
                caption=(
                    "📄 **Scanned Document**\n\n"
                    "✅ Border identification\n"
                    "✂️ Perspective crop\n"
                    "✨ Selected filter applied\n"
                    "📕 A4 PDF"
                )
            )

            await callback_query.message.delete()

            # Cleanup
            shutil.rmtree(
                os.path.dirname(job["path"]),
                ignore_errors=True
            )

            SCAN_JOBS.pop(
                job_id,
                None
            )

            return

        else:
            return

        # ----------------------------------------------------
        # SAVE RESULT
        # ----------------------------------------------------

        job["result"] = result
        job["filter"] = action

        save_image(
            result,
            job["path"]
        )

        await callback_query.answer(
            f"{action.title()} applied."
        )

        await callback_query.message.edit_text(
            "📄 **Scan Preview Ready**\n\n"
            f"🔍 {(
                'Border detected'
                if job['detected']
                else 'Safe crop used'
            )}\n"
            f"✂️ Perspective corrected\n"
            f"🎨 Filter: **{action.title()}**\n\n"
            "Choose another option or create PDF:",
            reply_markup=filter_keyboard()
        )

    except Exception as e:

        print(
            "[SCANNER CALLBACK ERROR]",
            repr(e)
        )

        await callback_query.answer(
            "Processing failed.",
            show_alert=True
        )