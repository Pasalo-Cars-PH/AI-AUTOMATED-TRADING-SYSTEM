from unittest.mock import Mock, patch

import app.main as app_main


def _response(status, body):
    response = Mock(status_code=status)
    response.json.return_value = body
    return response


def test_telegram_sender_reports_success(monkeypatch):
    monkeypatch.setattr(app_main, "TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setattr(app_main, "TELEGRAM_CHAT_ID", "test-chat")
    with patch("app.main.requests.post", return_value=_response(200, {"ok": True})) as post:
        assert app_main.send_telegram_msg("test alert") is True
    post.assert_called_once()


def test_telegram_sender_retries_plain_text_after_markdown_rejection(monkeypatch):
    monkeypatch.setattr(app_main, "TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setattr(app_main, "TELEGRAM_CHAT_ID", "test-chat")
    with patch("app.main.requests.post", side_effect=[
        _response(400, {"ok": False, "description": "can't parse entities"}),
        _response(200, {"ok": True}),
    ]) as post:
        assert app_main.send_telegram_msg("*invalid markdown*") is True
    assert post.call_count == 2
    assert "parse_mode" not in post.call_args.kwargs["json"]


def test_telegram_sender_fails_closed_when_credentials_missing(monkeypatch):
    monkeypatch.setattr(app_main, "TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setattr(app_main, "TELEGRAM_CHAT_ID", "test-chat")
    with patch("app.main.requests.post") as post:
        assert app_main.send_telegram_msg("test alert") is False
    post.assert_not_called()
