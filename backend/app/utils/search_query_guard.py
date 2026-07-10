from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class NormalizedSearchQuery:
    question: str
    video_ids: Optional[list[str]]
    top_k: int


def normalize_search_query(
    question: str,
    video_ids: Optional[list[str]],
    top_k: Optional[int],
    max_top_k: int,
) -> NormalizedSearchQuery:
    trimmed_question = question.strip()
    if not trimmed_question:
        raise ValueError("question must not be empty")

    if top_k is None:
        normalized_top_k = 5
    else:
        normalized_top_k = top_k

    if normalized_top_k <= 0:
        raise ValueError("top_k must be greater than 0")

    if normalized_top_k > max_top_k:
        raise ValueError(f"top_k must be less than or equal to {max_top_k}")

    normalized_video_ids: Optional[list[str]]
    if video_ids is None:
        normalized_video_ids = None
    else:
        deduped_ids: list[str] = []
        seen_ids: set[str] = set()
        for video_id in video_ids:
            cleaned_id = video_id.strip()
            if not cleaned_id:
                continue
            if cleaned_id not in seen_ids:
                deduped_ids.append(cleaned_id)
                seen_ids.add(cleaned_id)

        if not deduped_ids:
            raise ValueError("video_ids must contain at least one non-empty value")

        normalized_video_ids = deduped_ids

    return NormalizedSearchQuery(
        question=trimmed_question,
        video_ids=normalized_video_ids,
        top_k=normalized_top_k,
    )
