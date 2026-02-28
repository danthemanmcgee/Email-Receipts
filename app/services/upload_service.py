"""Upload service: image-to-PDF conversion and content hash utilities."""
import hashlib
import io
import logging

logger = logging.getLogger(__name__)

ALLOWED_CONTENT_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/gif",
    "image/webp",
}

IMAGE_CONTENT_TYPES = {
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/gif",
    "image/webp",
}


def image_bytes_to_pdf(image_bytes: bytes) -> bytes:
    """Convert raw image bytes to a single-page PDF using reportlab.

    The image is placed at full resolution on a canvas sized to match
    the image dimensions.  Supports JPEG, PNG, GIF and WebP via the
    reportlab ImageReader helper (which delegates to Pillow internally).
    """
    from reportlab.pdfgen import canvas
    from reportlab.lib.utils import ImageReader

    img = ImageReader(io.BytesIO(image_bytes))
    img_width, img_height = img.getSize()

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(img_width, img_height))
    c.drawImage(img, 0, 0, width=img_width, height=img_height)
    c.save()
    buf.seek(0)
    return buf.read()


def compute_content_hash(pdf_bytes: bytes) -> str:
    """Return the SHA-256 hex digest of *pdf_bytes*."""
    return hashlib.sha256(pdf_bytes).hexdigest()
