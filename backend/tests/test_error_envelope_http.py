from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.utils.exception_handlers import register_exception_handlers


class _Payload(BaseModel):
    name: str


def _build_test_app() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)

    @app.post("/validate")
    def validate(payload: _Payload):
        return payload

    @app.get("/http-string")
    def http_string():
        raise HTTPException(status_code=404, detail="not found")

    @app.get("/http-wrapped")
    def http_wrapped():
        raise HTTPException(
            status_code=422,
            detail={
                "error": {
                    "code": "INVALID_QUERY",
                    "message": "question must not be empty",
                }
            },
        )

    @app.get("/boom")
    def boom():
        raise RuntimeError("unexpected")

    return app


def test_validation_error_envelope() -> None:
    client = TestClient(_build_test_app(), raise_server_exceptions=False)

    response = client.post("/validate", json={"invalid": "value"})

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["message"] == "Request validation failed"
    assert isinstance(body["error"]["details"], list)


def test_http_exception_string_detail_envelope() -> None:
    client = TestClient(_build_test_app(), raise_server_exceptions=False)

    response = client.get("/http-string")

    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "HTTP_404",
            "message": "not found",
        }
    }


def test_http_exception_pre_wrapped_detail_passthrough() -> None:
    client = TestClient(_build_test_app(), raise_server_exceptions=False)

    response = client.get("/http-wrapped")

    assert response.status_code == 422
    assert response.json() == {
        "error": {
            "code": "INVALID_QUERY",
            "message": "question must not be empty",
        }
    }


def test_unhandled_exception_envelope() -> None:
    client = TestClient(_build_test_app(), raise_server_exceptions=False)

    response = client.get("/boom")

    assert response.status_code == 500
    assert response.json() == {
        "error": {
            "code": "INTERNAL_SERVER_ERROR",
            "message": "An unexpected error occurred",
        }
    }
