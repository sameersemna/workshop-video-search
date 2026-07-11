import hashlib


def build_segment_id(video_id: str, index: int, start: float, end: float, text: str) -> str:
    """
    Create deterministic segment IDs so reprocessing does not create duplicate
    entries. `index` (the segment's position in the transcript) is included so
    that two segments sharing identical start/end/text - which some Whisper
    backends legitimately produce, e.g. repeated phrases or silence - still get
    distinct IDs instead of colliding in the vector store.
    """
    normalized_text = " ".join((text or "").strip().split())
    raw = f"{video_id}|{index}|{start:.3f}|{end:.3f}|{normalized_text}".encode("utf-8")
    digest = hashlib.sha1(raw).hexdigest()[:16]
    return f"{video_id}_{digest}"
