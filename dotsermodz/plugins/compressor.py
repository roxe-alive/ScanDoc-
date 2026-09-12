import os
import re
import math
import time
import asyncio
import subprocess

from pyrogram import filters
from pyrogram.types import ForceReply
from pyrogram.errors import MessageNotModified

from dotsermodz import app


# ---------------------------------------------------------
# SETTINGS
# ---------------------------------------------------------

DOWNLOAD_DIR = "downloads/compressor"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# Maximum target size Telegram-style, adjust if needed.
MAX_TARGET_MB = 2000


# ---------------------------------------------------------
# HELPERS
# ---------------------------------------------------------

def parse_size(text: str):
    """
    Convert:
        50
        50MB
        1GB
        1.5GB
    into bytes.
    """

    text = text.strip().upper().replace(" ", "")

    match = re.fullmatch(r"(\d+(?:\.\d+)?)(KB|MB|GB|KIB|MIB|GIB)?", text)

    if not match:
        return None

    number = float(match.group(1))
    unit = match.group(2) or "MB"

    multipliers = {
        "KB": 1000,
        "MB": 1000 ** 2,
        "GB": 1000 ** 3,
        "KIB": 1024,
        "MIB": 1024 ** 2,
        "GIB": 1024 ** 3,
    }

    return int(number * multipliers[unit])


def format_size(size):
    if size < 1024 ** 2:
        return f"{size / 1024:.1f} KB"

    if size < 1024 ** 3:
        return f"{size / (1024 ** 2):.1f} MB"

    return f"{size / (1024 ** 3):.2f} GB"


def get_duration(file):
    command = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        file
    ]

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True
        )

        return float(result.stdout.strip())
    except Exception:
        return 0


def get_video_info(file):
    command = [
        "ffprobe",
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries",
        "stream=width,height",
        "-of",
        "csv=s=x:p=0",
        file
    ]

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True
        )

        return result.stdout.strip()
    except Exception:
        return "Unknown"


def progress_bar(current, total, length=15):
    if total <= 0:
        return "░" * length

    percentage = current / total
    filled = int(length * percentage)

    return "█" * filled + "░" * (length - filled)


# ---------------------------------------------------------
# /COMPRESS
# ---------------------------------------------------------

@app.on_message(filters.command("compress"))
async def compress_command(client, message):

    await message.reply(
        "🎬 **Video Compressor**\n\n"
        "Send me the **target file size**.\n\n"
        "Examples:\n"
        "• `50MB`\n"
        "• `100MB`\n"
        "• `500MB`\n"
        "• `1GB`\n\n"
        "I will automatically calculate the required "
        "bitrate to make the video as close as possible "
        "to that size.",
        reply_markup=ForceReply(
            placeholder="Example: 100MB"
        )
    )


# ---------------------------------------------------------
# TARGET SIZE HANDLER
# ---------------------------------------------------------

@app.on_message(
    filters.private &
    filters.text &
    ~filters.command(["compress", "start", "help"])
)
async def receive_size(client, message):

    # Only process messages that are replies to /compress.
    if not message.reply_to_message:
        return

    target = parse_size(message.text)

    if not target:
        return await message.reply(
            "❌ Invalid size.\n\n"
            "Use something like `50MB`, `100MB`, or `1GB`."
        )

    if target < 5 * 1024 * 1024:
        return await message.reply(
            "❌ Target size must be at least **5 MB**."
        )

    if target > MAX_TARGET_MB * 1024 ** 2:
        return await message.reply(
            f"❌ Maximum target size is **{MAX_TARGET_MB} MB**."
        )

    # Save target size temporarily in user session-like storage.
    # We use message.reply_to_message.id as the reference.
    message._compress_target = target

    await message.reply(
        f"✅ Target size: **{format_size(target)}**\n\n"
        "Now **send the video** you want to compress."
    )


# ---------------------------------------------------------
# VIDEO HANDLER
# ---------------------------------------------------------

@app.on_message(
    filters.private &
    (filters.video | filters.document)
)
async def video_compressor(client, message):

    # Make sure it is actually a video/document video.
    if message.document:
        mime = message.document.mime_type or ""

        if not mime.startswith("video/"):
            return

    # Ask target size.
    target_message = await message.reply(
        "📦 **Target size?**\n\n"
        "Reply with something like:\n"
        "`50MB`\n"
        "`100MB`\n"
        "`500MB`",
        reply_markup=ForceReply(
            placeholder="100MB"
        )
    )

    # Wait for user's reply.
    try:
        response = await client.listen(
            message.chat.id,
            filters=filters.text,
            timeout=120
        )

    except asyncio.TimeoutError:
        return await target_message.edit(
            "⌛ **Timed out.**\n\n"
            "Send `/compress` to try again."
        )

    target = parse_size(response.text)

    if not target:
        return await response.reply(
            "❌ Invalid size.\n\n"
            "Example: `100MB`"
        )

    if target < 5 * 1024 * 1024:
        return await response.reply(
            "❌ Target size must be at least **5 MB**."
        )

    if target > MAX_TARGET_MB * 1024 ** 2:
        return await response.reply(
            f"❌ Target size cannot exceed "
            f"**{MAX_TARGET_MB} MB**."
        )

    # -----------------------------------------------------
    # FILE PATHS
    # -----------------------------------------------------

    user_id = message.from_user.id

    timestamp = int(time.time())

    input_file = os.path.join(
        DOWNLOAD_DIR,
        f"{user_id}_{timestamp}_input"
    )

    output_file = os.path.join(
        DOWNLOAD_DIR,
        f"{user_id}_{timestamp}_compressed.mp4"
    )

    status = await response.reply(
        "⬇️ **Downloading video...**"
    )

    # -----------------------------------------------------
    # DOWNLOAD
    # -----------------------------------------------------

    try:

        async def download_progress(current, total):
            now = time.time()

            # Limit Telegram message updates.
            if not hasattr(download_progress, "last"):
                download_progress.last = 0

            if now - download_progress.last < 2:
                return

            download_progress.last = now

            percent = current * 100 / total

            try:
                await status.edit(
                    f"⬇️ **Downloading...**\n\n"
                    f"{progress_bar(current, total)} "
                    f"`{percent:.1f}%`\n\n"
                    f"{format_size(current)} / "
                    f"{format_size(total)}"
                )
            except MessageNotModified:
                pass
            except Exception:
                pass

        await message.download(
            file_name=input_file,
            progress=download_progress
        )

    except Exception as e:

        if os.path.exists(input_file):
            os.remove(input_file)

        return await status.edit(
            f"❌ Download failed.\n\n`{str(e)[:300]}`"
        )

    # -----------------------------------------------------
    # CHECK ORIGINAL SIZE
    # -----------------------------------------------------

    original_size = os.path.getsize(input_file)

    if original_size <= target:

        try:
            await status.edit(
                "✅ **Already under target size.**\n\n"
                f"Original: `{format_size(original_size)}`\n"
                f"Target: `{format_size(target)}`\n\n"
                "No compression was necessary."
            )

            await message.reply_video(
                input_file,
                caption=(
                    f"🎬 **Original Video**\n\n"
                    f"Size: `{format_size(original_size)}`"
                ),
                supports_streaming=True
            )

        finally:

            if os.path.exists(input_file):
                os.remove(input_file)

        return

    # -----------------------------------------------------
    # VIDEO DURATION
    # -----------------------------------------------------

    duration = get_duration(input_file)

    if duration <= 0:

        if os.path.exists(input_file):
            os.remove(input_file)

        return await status.edit(
            "❌ Could not detect video duration."
        )

    # -----------------------------------------------------
    # BITRATE CALCULATION
    # -----------------------------------------------------

    # Leave some space for MP4 container overhead.
    target_bits = target * 8 * 0.94

    total_bitrate = target_bits / duration

    # Audio bitrate.
    audio_bitrate = 96_000

    video_bitrate = total_bitrate - audio_bitrate

    # Minimum practical bitrate.
    if video_bitrate < 50_000:

        if os.path.exists(input_file):
            os.remove(input_file)

        return await status.edit(
            "❌ This target size is too small for this video "
            "duration.\n\n"
            "Please choose a larger target size."
        )

    video_kbps = int(video_bitrate / 1000)

    # -----------------------------------------------------
    # COMPRESS
    # -----------------------------------------------------

    await status.edit(
        "⚙️ **Compressing video...**\n\n"
        f"🎯 Target: `{format_size(target)}`\n"
        f"🎞 Resolution: `{get_video_info(input_file)}`\n"
        f"⏱ Duration: `{int(duration)} sec`\n"
        f"📊 Video bitrate: `{video_kbps} kbps`"
    )

    command = [
        "ffmpeg",
        "-y",

        "-i", input_file,

        # Video
        "-c:v", "libx264",
        "-preset", "medium",
        "-b:v", f"{video_kbps}k",

        # Use two-pass-like quality control through bitrate.
        "-maxrate", f"{int(video_kbps * 1.15)}k",
        "-bufsize", f"{int(video_kbps * 2)}k",

        # Audio
        "-c:a", "aac",
        "-b:a", "96k",

        # Fast start
        "-movflags", "+faststart",

        output_file
    ]

    process = None

    try:

        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        while True:

            line = await process.stderr.readline()

            if not line:
                break

            line = line.decode(
                errors="ignore"
            )

            # FFmpeg progress.
            if "time=" in line:

                match = re.search(
                    r"time=(\d+):(\d+):(\d+(?:\.\d+)?)",
                    line
                )

                if match:

                    h = int(match.group(1))
                    m = int(match.group(2))
                    s = float(match.group(3))

                    current_time = (
                        h * 3600 +
                        m * 60 +
                        s
                    )

                    percent = min(
                        100,
                        current_time / duration * 100
                    )

                    try:

                        await status.edit(
                            f"⚙️ **Compressing...**\n\n"
                            f"{progress_bar(percent, 100)} "
                            f"`{percent:.1f}%`\n\n"
                            f"🎯 Target: `{format_size(target)}`"
                        )

                    except Exception:
                        pass

        await process.wait()

    except Exception as e:

        if os.path.exists(input_file):
            os.remove(input_file)

        if os.path.exists(output_file):
            os.remove(output_file)

        return await status.edit(
            f"❌ FFmpeg error.\n\n`{str(e)[:500]}`"
        )

    # -----------------------------------------------------
    # CHECK OUTPUT
    # -----------------------------------------------------

    if process.returncode != 0 or not os.path.exists(output_file):

        if os.path.exists(input_file):
            os.remove(input_file)

        if os.path.exists(output_file):
            os.remove(output_file)

        return await status.edit(
            "❌ **Compression failed.**\n\n"
            "FFmpeg could not create the compressed video."
        )

    compressed_size = os.path.getsize(output_file)

    # -----------------------------------------------------
    # SEND
    # -----------------------------------------------------

    await status.edit(
        "⬆️ **Uploading compressed video...**"
    )

    try:

        async def upload_progress(current, total):

            now = time.time()

            if not hasattr(upload_progress, "last"):
                upload_progress.last = 0

            if now - upload_progress.last < 2:
                return

            upload_progress.last = now

            percent = current * 100 / total

            try:

                await status.edit(
                    f"⬆️ **Uploading...**\n\n"
                    f"{progress_bar(current, total)} "
                    f"`{percent:.1f}%`\n\n"
                    f"{format_size(current)} / "
                    f"{format_size(total)}"
                )

            except Exception:
                pass

        await message.reply_video(
            output_file,
            caption=(
                "🎬 **Compressed Video**\n\n"
                f"📦 Original: `{format_size(original_size)}`\n"
                f"📦 Compressed: `{format_size(compressed_size)}`\n"
                f"🎯 Target: `{format_size(target)}`\n"
                f"📉 Reduced: "
                f"`{100 - (compressed_size / original_size * 100):.1f}%`"
            ),
            supports_streaming=True,
            progress=upload_progress
        )

        await status.delete()

    except Exception as e:

        await status.edit(
            f"❌ Upload failed.\n\n`{str(e)[:400]}`"
        )

    finally:

        if os.path.exists(input_file):
            os.remove(input_file)

        if os.path.exists(output_file):
            os.remove(output_file)