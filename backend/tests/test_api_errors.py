import json

from app.utils.api_errors import build_error_payload, build_error_response


def test_build_error_payload_without_details() -> None:
    payload = build_error_payload(code="INVALID_QUERY", message="question must not be empty")

    assert payload == {
        "error": {
            "code": "INVALID_QUERY",
            "message": "question must not be empty",
        }
    }


def test_build_error_payload_with_details() -> None:
    payload = build_error_payload(
        code="VALIDATION_ERROR",
        message="Request validation failed",
        details=[{"loc": ["body", "topK"], "msg": "Input should be a valid integer"}],
    )

    assert payload == {
        "error": {
            "code": "VALIDATION_ERROR",
            "message": "Request validation failed",
            "details": [{"loc": ["body", "topK"], "msg": "Input should be a valid integer"}],
        }
    }


def test_build_error_response_returns_json_response() -> None:
    response = build_error_response(
        status_code=422,
        code="INVALID_QUERY",
        message="top_k must be greater than 0",
    )

    assert response.status_code == 422
    payload = json.loads(response.body)
    assert payload == {
        "error": {
            "code": "INVALID_QUERY",
            "message": "top_k must be greater than 0",
        }
    }
