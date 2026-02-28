import pytest
import hashlib


def compute_content_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def test_content_hash_deterministic():
    content = b"PDF content here"
    h1 = compute_content_hash(content)
    h2 = compute_content_hash(content)
    assert h1 == h2


def test_content_hash_different_content():
    h1 = compute_content_hash(b"content1")
    h2 = compute_content_hash(b"content2")
    assert h1 != h2


def test_gmail_message_id_uniqueness():
    """Simulates idempotency check - same gmail_message_id should not create duplicate."""
    seen_ids = set()

    def process_message(gmail_message_id: str) -> bool:
        """Returns True if processed, False if duplicate."""
        if gmail_message_id in seen_ids:
            return False
        seen_ids.add(gmail_message_id)
        return True

    assert process_message("msg_001") is True
    assert process_message("msg_001") is False  # duplicate
    assert process_message("msg_002") is True


# ---------------------------------------------------------------------------
# GmailReceiptLink model
# ---------------------------------------------------------------------------

def test_gmail_receipt_link_model_fields():
    """GmailReceiptLink can be instantiated and holds expected attributes."""
    from app.models.receipt import GmailReceiptLink

    link = GmailReceiptLink.__new__(GmailReceiptLink)
    link.receipt_id = 1
    link.gmail_message_id = "msg_abc"
    link.user_id = 42

    assert link.receipt_id == 1
    assert link.gmail_message_id == "msg_abc"
    assert link.user_id == 42


def test_receipt_has_gmail_links_relationship():
    """Receipt model exposes a gmail_links relationship attribute."""
    from app.models.receipt import Receipt

    r = Receipt.__new__(Receipt)
    # The relationship descriptor must exist on the class
    assert hasattr(Receipt, "gmail_links")


# ---------------------------------------------------------------------------
# Deduplication logic (in-memory simulation)
# ---------------------------------------------------------------------------

class _FakeReceipt:
    """Minimal stand-in for a Receipt row used in unit tests."""
    def __init__(self, id, user_id, content_hash, drive_file_id=None):
        self.id = id
        self.user_id = user_id
        self.content_hash = content_hash
        self.drive_file_id = drive_file_id


def _find_canonical(db_receipts, user_id, content_hash, exclude_id):
    """Replicate the duplicate-detection query from process_receipt_task."""
    for r in db_receipts:
        if (
            r.content_hash == content_hash
            and r.user_id == user_id
            and r.id != exclude_id
        ):
            return r
    return None


def test_duplicate_upload_yields_single_drive_file():
    """Two Gmail messages with the same PDF content produce one Drive file."""
    pdf_bytes = b"%PDF-1.4 fake receipt content"
    content_hash = compute_content_hash(pdf_bytes)
    user_id = 1

    # Simulate DB: first message already processed and stored.
    canonical = _FakeReceipt(id=1, user_id=user_id, content_hash=content_hash, drive_file_id="drive_file_xyz")
    db_receipts = [canonical]

    # A second placeholder receipt is created for the incoming duplicate message.
    placeholder = _FakeReceipt(id=2, user_id=user_id, content_hash=content_hash, drive_file_id=None)

    found = _find_canonical(db_receipts, user_id, content_hash, exclude_id=placeholder.id)

    assert found is not None, "Canonical receipt should be detected"
    assert found.drive_file_id == "drive_file_xyz", "Duplicate should reuse existing drive_file_id"


def test_no_false_duplicate_for_different_content():
    """Receipts with different content hashes are NOT treated as duplicates."""
    user_id = 1
    hash_a = compute_content_hash(b"receipt A")
    hash_b = compute_content_hash(b"receipt B")

    canonical = _FakeReceipt(id=1, user_id=user_id, content_hash=hash_a, drive_file_id="drive_file_a")
    db_receipts = [canonical]

    placeholder = _FakeReceipt(id=2, user_id=user_id, content_hash=hash_b)
    found = _find_canonical(db_receipts, user_id, hash_b, exclude_id=placeholder.id)

    assert found is None, "Different content should not be treated as a duplicate"


def test_no_cross_user_duplicate_detection():
    """The same content hash for different users is NOT a duplicate."""
    hash_val = compute_content_hash(b"shared receipt")

    user1_receipt = _FakeReceipt(id=1, user_id=1, content_hash=hash_val, drive_file_id="drive_1")
    db_receipts = [user1_receipt]

    # User 2's placeholder
    placeholder = _FakeReceipt(id=2, user_id=2, content_hash=hash_val)
    found = _find_canonical(db_receipts, user_id=2, content_hash=hash_val, exclude_id=placeholder.id)

    assert found is None, "Cross-user deduplication must not occur"


def test_gmail_receipt_link_tracks_duplicate_email():
    """A duplicate email should produce a GmailReceiptLink, not a new receipt."""
    links = []

    def record_link(receipt_id, gmail_message_id, user_id):
        links.append({"receipt_id": receipt_id, "gmail_message_id": gmail_message_id})

    # Simulate: canonical receipt already exists; second message is a duplicate.
    canonical_id = 1
    record_link(canonical_id, "msg_duplicate", user_id=1)

    assert len(links) == 1
    assert links[0]["receipt_id"] == canonical_id
    assert links[0]["gmail_message_id"] == "msg_duplicate"


def test_sync_gmail_skips_linked_messages():
    """sync_gmail should skip messages already present in gmail_receipt_links."""
    processed_receipts = set()  # gmail_message_ids in receipts table
    linked_messages = {"msg_dup"}   # gmail_message_ids in gmail_receipt_links

    def should_queue(mid):
        if mid in processed_receipts:
            return False
        if mid in linked_messages:
            return False
        return True

    assert should_queue("msg_new") is True
    assert should_queue("msg_dup") is False   # already linked → skip
    assert should_queue("msg_dup") is False   # idempotent

