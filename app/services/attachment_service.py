import re
from dataclasses import dataclass
from typing import List, Optional

POSITIVE_KEYWORDS = [
    "receipt",
    "payment receipt",
    "order receipt",
    "purchase receipt",
    "transaction receipt",
]
NEGATIVE_KEYWORDS = ["invoice", "statement", "quote", "estimate", "packing slip", "proforma"]


@dataclass
class AttachmentScore:
    filename: str
    normalized: str
    score: int
    decision: str  # "selected" | "ignored" | "candidate"
    reason: str
    timestamp: Optional[float] = None


def normalize_filename(filename: str) -> str:
    """Lowercase, strip extension, replace _ and - with spaces."""
    name = filename.rsplit(".", 1)[0] if "." in filename else filename
    name = name.lower()
    name = re.sub(r"[_\-]", " ", name)
    return name.strip()


def score_pdf(filename: str, timestamp: Optional[float] = None) -> AttachmentScore:
    """Score a PDF filename for receipt-likelihood."""
    normalized = normalize_filename(filename)
    score = 0
    reasons = []

    # Check positive keywords - whole-word receipt
    if re.search(r"\breceipt\b", normalized):
        score += 100
        reasons.append("+100 whole-word 'receipt'")

    for phrase in POSITIVE_KEYWORDS[1:]:  # skip "receipt" already handled
        if phrase in normalized:
            score += 40
            reasons.append(f"+40 positive phrase '{phrase}'")

    # Check negative keywords
    for neg in NEGATIVE_KEYWORDS:
        if re.search(r"\b" + re.escape(neg) + r"\b", normalized):
            score -= 60
            reasons.append(f"-60 negative keyword '{neg}'")

    return AttachmentScore(
        filename=filename,
        normalized=normalized,
        score=score,
        decision="candidate",
        reason="; ".join(reasons) if reasons else "no keywords matched",
        timestamp=timestamp,
    )


def select_best_pdf(
    attachments: List[dict],
) -> tuple[Optional[AttachmentScore], List[AttachmentScore]]:
    """
    attachments: list of {"filename": str, "timestamp": Optional[float]}
    Returns (selected, all_scores)
    """
    if not attachments:
        return None, []

    scores = [score_pdf(a["filename"], a.get("timestamp")) for a in attachments]

    # Filter to score > 0
    candidates = [s for s in scores if s.score > 0]

    if not candidates:
        for s in scores:
            s.decision = "ignored"
            s.reason = s.reason + " | score <= 0, not a receipt"
        return None, scores

    def sort_key(s: AttachmentScore):
        has_exact = 1 if re.search(r"\breceipt\b", s.normalized) else 0
        ts = s.timestamp or 0.0
        return (-s.score, -has_exact, -ts, s.filename)

    candidates.sort(key=sort_key)
    selected = candidates[0]
    selected.decision = "selected"
    selected.reason = selected.reason + " | selected as best receipt PDF"

    for s in candidates[1:]:
        s.decision = "ignored"
        s.reason = s.reason + " | ignored: lower score/priority than selected"

    for s in scores:
        if s.decision == "candidate":
            s.decision = "ignored"
            s.reason = s.reason + " | score <= 0"

    return selected, scores
