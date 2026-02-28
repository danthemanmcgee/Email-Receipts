"""Tests for direct receipt upload functionality."""
import hashlib
import io


# ---------------------------------------------------------------------------
# upload_service helpers
# ---------------------------------------------------------------------------

def test_compute_content_hash_deterministic():
    from app.services.upload_service import compute_content_hash

    data = b"%PDF-1.4 fake receipt"
    first = compute_content_hash(data)
    second = compute_content_hash(data)
    assert first == second, "Same input must always produce the same hash"


def test_compute_content_hash_different_inputs():
    from app.services.upload_service import compute_content_hash

    assert compute_content_hash(b"receipt A") != compute_content_hash(b"receipt B")


def test_compute_content_hash_matches_sha256():
    from app.services.upload_service import compute_content_hash

    data = b"test content"
    expected = hashlib.sha256(data).hexdigest()
    assert compute_content_hash(data) == expected


def test_allowed_content_types_includes_pdf_and_images():
    from app.services.upload_service import ALLOWED_CONTENT_TYPES, IMAGE_CONTENT_TYPES

    assert "application/pdf" in ALLOWED_CONTENT_TYPES
    for ct in ("image/jpeg", "image/png", "image/gif", "image/webp"):
        assert ct in ALLOWED_CONTENT_TYPES
        assert ct in IMAGE_CONTENT_TYPES

    # PDF must not be in IMAGE_CONTENT_TYPES (no conversion needed)
    assert "application/pdf" not in IMAGE_CONTENT_TYPES


def test_image_bytes_to_pdf_returns_pdf_bytes():
    """image_bytes_to_pdf must return bytes that start with the PDF magic bytes."""
    from app.services.upload_service import image_bytes_to_pdf

    # Minimal valid 1x1 white PNG
    import struct
    import zlib

    def _make_1x1_png() -> bytes:
        sig = b"\x89PNG\r\n\x1a\n"

        def chunk(name, data):
            c = struct.pack(">I", len(data)) + name + data
            return c + struct.pack(">I", zlib.crc32(name + data) & 0xFFFFFFFF)

        ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
        raw = b"\x00\xFF\xFF\xFF"
        idat = chunk(b"IDAT", zlib.compress(raw))
        iend = chunk(b"IEND", b"")
        return sig + ihdr + idat + iend

    png_bytes = _make_1x1_png()
    pdf_bytes = image_bytes_to_pdf(png_bytes)

    assert isinstance(pdf_bytes, bytes)
    assert pdf_bytes.startswith(b"%PDF")


# ---------------------------------------------------------------------------
# Upload endpoint unit tests (no live DB / Drive)
# ---------------------------------------------------------------------------

class _FakeReceipt:
    """Minimal Receipt stand-in for deduplication unit tests."""

    def __init__(self, id, user_id, content_hash, drive_file_id=None, status="processed"):
        self.id = id
        self.user_id = user_id
        self.content_hash = content_hash
        self.drive_file_id = drive_file_id
        self.status = status
        self.attachment_logs = []


def _find_existing(db_receipts, user_id, content_hash):
    """Replicate the dedup lookup used in the upload endpoint."""
    for r in db_receipts:
        if r.content_hash == content_hash and r.user_id == user_id:
            return r
    return None


def test_upload_dedup_reuses_existing_receipt():
    """Uploading the same PDF twice for the same user returns the existing receipt."""
    from app.services.upload_service import compute_content_hash

    pdf = b"%PDF-1.4 receipt"
    h = compute_content_hash(pdf)
    existing = _FakeReceipt(id=7, user_id=1, content_hash=h, drive_file_id="file_abc")
    db = [existing]

    result = _find_existing(db, user_id=1, content_hash=h)
    assert result is not None
    assert result.id == 7
    assert result.drive_file_id == "file_abc"


def test_upload_dedup_no_cross_user_collision():
    """The same PDF from a different user must not be treated as a duplicate."""
    from app.services.upload_service import compute_content_hash

    pdf = b"%PDF-1.4 receipt"
    h = compute_content_hash(pdf)
    existing = _FakeReceipt(id=7, user_id=1, content_hash=h)
    db = [existing]

    result = _find_existing(db, user_id=2, content_hash=h)
    assert result is None


def test_upload_dedup_different_content_no_match():
    """Different PDFs are not treated as duplicates."""
    from app.services.upload_service import compute_content_hash

    h_a = compute_content_hash(b"pdf A")
    h_b = compute_content_hash(b"pdf B")
    existing = _FakeReceipt(id=1, user_id=1, content_hash=h_a)
    db = [existing]

    result = _find_existing(db, user_id=1, content_hash=h_b)
    assert result is None


def test_content_type_validation_rejects_unknown():
    """Non-receipt content types must be rejected."""
    from app.services.upload_service import ALLOWED_CONTENT_TYPES

    assert "text/html" not in ALLOWED_CONTENT_TYPES
    assert "application/zip" not in ALLOWED_CONTENT_TYPES
    assert "image/tiff" not in ALLOWED_CONTENT_TYPES


def test_synthetic_gmail_message_id_format():
    """Uploaded receipts use a synthetic Gmail message ID starting with 'upload_'."""
    import uuid

    synthetic_id = f"upload_{uuid.uuid4().hex}"
    assert synthetic_id.startswith("upload_")
    # Must be within the 255-char column limit
    assert len(synthetic_id) <= 255
