from app.services.segment_ids import build_segment_id


def test_segment_id_is_deterministic() -> None:
    segment_id_a = build_segment_id("video-1", 0, 1.23456, 4.56789, "Hello world")
    segment_id_b = build_segment_id("video-1", 0, 1.23456, 4.56789, "Hello world")
    assert segment_id_a == segment_id_b


def test_segment_id_changes_when_content_changes() -> None:
    segment_id_a = build_segment_id("video-1", 0, 1.0, 2.0, "Hello world")
    segment_id_b = build_segment_id("video-1", 0, 1.0, 2.0, "Hello world!")
    assert segment_id_a != segment_id_b


def test_segment_id_normalizes_whitespace() -> None:
    segment_id_a = build_segment_id("video-1", 0, 1.0, 2.0, "Hello   world")
    segment_id_b = build_segment_id("video-1", 0, 1.0, 2.0, "Hello world")
    assert segment_id_a == segment_id_b


def test_segment_id_changes_when_index_changes_for_identical_content() -> None:
    # Some Whisper backends can legitimately emit segments with identical
    # start/end/text (e.g. repeated phrases or silence); the index keeps
    # their IDs from colliding in the vector store.
    segment_id_a = build_segment_id("video-1", 0, 1.0, 2.0, "Hello world")
    segment_id_b = build_segment_id("video-1", 1, 1.0, 2.0, "Hello world")
    assert segment_id_a != segment_id_b
