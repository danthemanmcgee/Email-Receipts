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
