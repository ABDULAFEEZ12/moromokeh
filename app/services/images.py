"""Product image upload pipeline.

Every uploaded image is re-encoded from decoded pixel data - never saved as
the raw uploaded bytes - which both strips EXIF metadata and neutralizes a
file that merely has an image-looking extension but isn't actually a valid
image. Three sizes are generated as WebP so listing pages never ship a
full-resolution photo to a phone that's displaying a 300px-wide card.
"""

import io
import os
import uuid

from PIL import Image

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
SIZES = {
    "thumb": 400,
    "medium": 900,
    "large": 1600,
}
WEBP_QUALITY = 82


class ImageValidationError(Exception):
    pass


def allowed_filename(filename):
    return bool(filename) and "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def process_and_save(file_storage, upload_root):
    """Validate, resize, and persist an uploaded product photo.

    Returns a dict {"thumb": url, "medium": url, "large": url, "alt": ""}
    with paths relative to /static, suitable for storing straight on the
    product document.
    """
    if not allowed_filename(file_storage.filename):
        raise ImageValidationError("Unsupported file type. Use JPG, PNG, or WebP.")

    raw = file_storage.read()
    if not raw:
        raise ImageValidationError("The uploaded file is empty.")

    try:
        img = Image.open(io.BytesIO(raw))
        img.verify()
        img = Image.open(io.BytesIO(raw))  # verify() consumes the parser; reopen to actually use it
        img = img.convert("RGB")
    except Exception:
        # Pillow raises different exception types (OSError, SyntaxError, ValueError, ...)
        # depending on exactly how a file is malformed - anything here means "not a
        # usable image", which is a validation error, not a server error.
        raise ImageValidationError("That file isn't a valid image.")

    folder_name = uuid.uuid4().hex
    folder_path = os.path.join(upload_root, "products", folder_name)
    os.makedirs(folder_path, exist_ok=True)

    urls = {}
    for label, max_dim in SIZES.items():
        resized = img.copy()
        if max(resized.size) > max_dim:
            resized.thumbnail((max_dim, max_dim), Image.LANCZOS)
        out_path = os.path.join(folder_path, f"{label}.webp")
        resized.save(out_path, format="WEBP", quality=WEBP_QUALITY, method=6)
        urls[label] = f"/static/uploads/products/{folder_name}/{label}.webp"

    urls["alt"] = ""
    return urls


def delete_image_files(image_entry, upload_root):
    for key in ("thumb", "medium", "large"):
        url = image_entry.get(key)
        if not url or not url.startswith("/static/uploads/"):
            continue
        rel = url[len("/static/uploads/"):]
        path = os.path.join(upload_root, rel)
        if os.path.isfile(path):
            try:
                os.remove(path)
            except OSError:
                pass
