"""Unit tests for storage functionality."""

import pytest
from unittest.mock import Mock, patch
import sys
from pathlib import Path
from urllib.parse import urlsplit

# Add the project root to the path so we can import modules
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))


def test_database_url_default(monkeypatch):
    """Test that local fallback URLs are ignored in favor of the configured Turso host."""
    from backend.services import storage

    def fallback_local_url(setting):
        return "sqlite:///previous.db" if setting == "DATABASE_URL" else None

    monkeypatch.setattr(storage, "dotenv_values", lambda _path: {})
    with patch.object(storage, "read_setting", side_effect=fallback_local_url):
        url = storage.database_url()
    assert urlsplit(url).hostname == storage.TURSO_DATABASE_HOST
    assert urlsplit(url).username is None


def test_database_url_accepts_target_from_existing_setting():
    from backend.services import storage

    target_url = "libsql://auth-token@my-learning-apecet-pzazz55.aws-us-east-1.turso.io"
    with patch.object(storage, "read_setting", side_effect=lambda key: target_url if key == "DATABASE_URL" else None):
        assert storage.database_url() == target_url


def test_database_url_ignores_local_environment_and_uses_target_dotenv(monkeypatch):
    from backend.services import storage

    target_url = "libsql://auth-token@my-learning-apecet-pzazz55.aws-us-east-1.turso.io"
    monkeypatch.setattr(
        storage,
        "read_setting",
        lambda key: "sqlite:///previous.db" if key == "DATABASE_URL" else None,
    )
    monkeypatch.setattr(storage, "dotenv_values", lambda _path: {"DATABASE_URL": target_url})

    assert storage.database_url() == target_url


def test_turso_client_uses_pipeline_endpoint(monkeypatch):
    from backend.services import storage

    monkeypatch.setattr(
        storage,
        "database_url",
        lambda: "libsql://test-token@my-learning-apecet-pzazz55.aws-us-east-1.turso.io",
    )

    http_url, auth_token = storage._get_turso_http_client()

    assert http_url == "https://my-learning-apecet-pzazz55.aws-us-east-1.turso.io/v2/pipeline"
    assert auth_token == "test-token"


def test_turso_execute_sends_pipeline_and_normalizes_typed_rows(monkeypatch):
    from backend.services import storage

    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "results": [
                    {
                        "type": "ok",
                        "response": {
                            "type": "execute",
                            "result": {
                                "cols": [{"name": "value"}],
                                "rows": [[{"type": "integer", "value": "7"}]],
                                "affected_row_count": 0,
                                "last_insert_rowid": None,
                            },
                        },
                    },
                    {"type": "ok", "response": {"type": "close"}},
                ]
            }

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return FakeResponse()

    monkeypatch.setattr(
        storage,
        "_get_turso_http_client",
        lambda: ("https://example.turso.io/v2/pipeline", "test-token"),
    )
    monkeypatch.setattr(storage.requests, "post", fake_post)

    result = storage._turso_execute("SELECT ? AS value", [7])

    assert captured["url"] == "https://example.turso.io/v2/pipeline"
    assert captured["headers"]["Authorization"] == "Bearer test-token"
    assert captured["json"]["requests"][0]["stmt"]["args"] == [
        {"type": "integer", "value": "7"}
    ]
    assert result["results"][0]["columns"] == ["value"]
    assert result["results"][0]["rows"] == [[7]]


def test_turso_unauthorized_response_has_actionable_message(monkeypatch):
    from backend.services import storage

    class UnauthorizedResponse:
        status_code = 401

        def raise_for_status(self):
            import requests

            raise requests.HTTPError("401 Unauthorized")

    monkeypatch.setattr(
        storage,
        "_get_turso_http_client",
        lambda: ("https://example.turso.io/v2/pipeline", "test-token"),
    )
    monkeypatch.setattr(storage.requests, "post", lambda *_args, **_kwargs: UnauthorizedResponse())

    with pytest.raises(RuntimeError, match="Turso rejected the auth token for my-learning-apecet"):
        storage._turso_execute("SELECT 1")


def test_storage_backend_label():
    """Test that backend label is generated correctly."""
    from backend.services.storage import backend_label
    label = backend_label()
    assert isinstance(label, str)
    assert len(label) > 0