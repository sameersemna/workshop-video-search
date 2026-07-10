import pytest

from app.utils.search_query_guard import normalize_search_query


def test_normalize_search_query_trims_and_deduplicates_inputs() -> None:
    normalized = normalize_search_query(
        question="  find this  ",
        video_ids=["video-a", " video-a ", "video-b", "   "],
        top_k=3,
        max_top_k=10,
    )

    assert normalized.question == "find this"
    assert normalized.video_ids == ["video-a", "video-b"]
    assert normalized.top_k == 3


def test_normalize_search_query_uses_default_top_k_when_missing() -> None:
    normalized = normalize_search_query(
        question="what is covered",
        video_ids=None,
        top_k=None,
        max_top_k=20,
    )

    assert normalized.top_k == 5
    assert normalized.video_ids is None


@pytest.mark.parametrize(
    "question,video_ids,top_k,max_top_k,expected_message",
    [
        ("   ", None, 5, 20, "question must not be empty"),
        ("ok", None, 0, 20, "top_k must be greater than 0"),
        ("ok", None, 25, 20, "top_k must be less than or equal to 20"),
        ("ok", [" ", ""], 5, 20, "video_ids must contain at least one non-empty value"),
    ],
)
def test_normalize_search_query_rejects_invalid_input(
    question: str,
    video_ids: list[str] | None,
    top_k: int | None,
    max_top_k: int,
    expected_message: str,
) -> None:
    with pytest.raises(ValueError, match=expected_message):
        normalize_search_query(
            question=question,
            video_ids=video_ids,
            top_k=top_k,
            max_top_k=max_top_k,
        )
