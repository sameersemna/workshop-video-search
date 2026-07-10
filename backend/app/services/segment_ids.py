import hashlib


def build_segment_id(video_id: str, start: float, end: float, text: str) -> str:
    """Create deterministic segment IDs so reprocessing does not create duplicate entries."""
    normalized_text = " ".join((text or "").strip().split())
    raw = f"{video_id}|{start:.3f}|{end:.3f}|{normalized_text}".encode("utf-8")
    digest = hashlib.sha1(raw).hexdigest()[:16]
    return f"{video_id}_{digest}"
