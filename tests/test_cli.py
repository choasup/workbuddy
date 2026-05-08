import json
import types

import anthropic
import pytest

import workbuddy.cli as cli_mod
from workbuddy.cli import (
    MAX_LOGGED_RESPONSE_CHARS,
    _extract_text,
    _log_run,
    main,
)


class _FakeAPIError(anthropic.APIError):
    def __init__(self, msg: str = "boom"):
        Exception.__init__(self, msg)


@pytest.fixture(autouse=True)
def _isolate_workbuddy_home(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKBUDDY_HOME", str(tmp_path))


class _StubMessages:
    def __init__(self, text: str):
        self._text = text
        self.last_kwargs: dict | None = None

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        block = types.SimpleNamespace(text=self._text)
        return types.SimpleNamespace(content=[block])


class _StubClient:
    last_init_kwargs: dict | None = None
    last_messages: _StubMessages | None = None

    def __init__(self, **kwargs):
        type(self).last_init_kwargs = kwargs
        self.messages = _StubMessages("stubbed-claude-reply")
        type(self).last_messages = self.messages


def test_main_calls_anthropic_and_prints_response(monkeypatch, capsys):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr(cli_mod, "Anthropic", _StubClient)

    rc = main(["please summarize"])

    assert rc == 0
    captured = capsys.readouterr()
    assert "stubbed-claude-reply" in captured.out
    assert _StubClient.last_init_kwargs is not None
    assert _StubClient.last_init_kwargs["api_key"] == "sk-test"
    assert _StubClient.last_init_kwargs.get("timeout") == 60.0
    assert _StubClient.last_messages is not None
    sent = _StubClient.last_messages.last_kwargs
    assert sent is not None
    assert sent["model"] == "claude-sonnet-4-6"
    assert sent["messages"] == [{"role": "user", "content": "please summarize"}]


def test_main_missing_api_key_exits_nonzero(monkeypatch, capsys):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(cli_mod, "Anthropic", _StubClient)

    rc = main(["please summarize"])

    assert rc != 0
    captured = capsys.readouterr()
    assert "ANTHROPIC_API_KEY" in captured.err


def test_main_empty_api_key_exits_nonzero(monkeypatch, capsys):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setattr(cli_mod, "Anthropic", _StubClient)

    rc = main(["please summarize"])

    assert rc != 0
    captured = capsys.readouterr()
    assert "ANTHROPIC_API_KEY" in captured.err


def test_main_model_flag_overrides_default(monkeypatch, capsys):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr(cli_mod, "Anthropic", _StubClient)

    rc = main(["--model", "claude-opus-4-7", "do something"])

    assert rc == 0
    sent = _StubClient.last_messages.last_kwargs
    assert sent is not None
    assert sent["model"] == "claude-opus-4-7"


def test_main_uses_default_model_from_config(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr(cli_mod, "Anthropic", _StubClient)
    (tmp_path / "config.json").write_text(
        json.dumps({"default_model": "claude-opus-4-7"}), encoding="utf-8"
    )

    rc = main(["task"])

    assert rc == 0
    assert _StubClient.last_messages.last_kwargs["model"] == "claude-opus-4-7"


def test_main_explicit_model_flag_overrides_config(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr(cli_mod, "Anthropic", _StubClient)
    (tmp_path / "config.json").write_text(
        json.dumps({"default_model": "claude-opus-4-7"}), encoding="utf-8"
    )

    rc = main(["--model", "claude-haiku-4-5", "task"])

    assert rc == 0
    assert _StubClient.last_messages.last_kwargs["model"] == "claude-haiku-4-5"


def test_main_malformed_config_falls_back_and_warns(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr(cli_mod, "Anthropic", _StubClient)
    (tmp_path / "config.json").write_text("not json {", encoding="utf-8")

    rc = main(["task"])

    assert rc == 0
    assert _StubClient.last_messages.last_kwargs["model"] == "claude-sonnet-4-6"
    captured = capsys.readouterr()
    assert "warning" in captured.err


def test_main_api_error_exits_nonzero_and_does_not_log(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")

    class _RaisingMessages:
        def create(self, **kwargs):
            raise _FakeAPIError("network is on fire")

    class _RaisingClient:
        def __init__(self, **kwargs):
            self.messages = _RaisingMessages()

    monkeypatch.setattr(cli_mod, "Anthropic", _RaisingClient)

    rc = main(["task"])

    assert rc != 0
    captured = capsys.readouterr()
    assert "API call failed" in captured.err
    assert "_FakeAPIError" in captured.err
    assert not (tmp_path / "log.md").exists()


def test_main_missing_argument_exits_nonzero(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main([])
    assert excinfo.value.code != 0
    captured = capsys.readouterr()
    assert captured.err


def _resp(*texts):
    blocks = [types.SimpleNamespace(text=t) for t in texts]
    return types.SimpleNamespace(content=blocks)


def test_extract_text_concatenates_multiple_blocks():
    response = _resp("hello ", "world", "!")
    assert _extract_text(response) == "hello world!"


def test_extract_text_skips_blocks_without_text():
    response = types.SimpleNamespace(
        content=[
            types.SimpleNamespace(text="keep"),
            types.SimpleNamespace(),  # no .text attribute
            types.SimpleNamespace(text=None),  # .text is None
            types.SimpleNamespace(text="end"),
        ]
    )
    assert _extract_text(response) == "keepend"


def test_extract_text_empty_content_list():
    assert _extract_text(types.SimpleNamespace(content=[])) == ""


def test_extract_text_none_content():
    assert _extract_text(types.SimpleNamespace(content=None)) == ""


def test_log_run_truncates_long_response(tmp_path):
    long_text = "x" * (MAX_LOGGED_RESPONSE_CHARS + 100)
    tail_marker = "TAIL_MARKER_SHOULD_NOT_APPEAR"
    long_text_with_tail = long_text + tail_marker

    _log_run("t", long_text_with_tail)

    contents = (tmp_path / "log.md").read_text(encoding="utf-8")
    assert "... [truncated]" in contents
    assert tail_marker not in contents


def test_log_run_creates_nested_directories(tmp_path, monkeypatch):
    nested = tmp_path / "deep" / "nested" / "wb"
    monkeypatch.setenv("WORKBUDDY_HOME", str(nested))

    _log_run("nested-task", "nested-response")

    log_file = nested / "log.md"
    assert log_file.exists()
    contents = log_file.read_text(encoding="utf-8")
    assert "nested-task" in contents
    assert "nested-response" in contents


def test_log_run_handles_oserror_without_raising(tmp_path, monkeypatch, capsys):
    blocking_file = tmp_path / "imafile"
    blocking_file.write_text("not a directory", encoding="utf-8")
    monkeypatch.setenv("WORKBUDDY_HOME", str(blocking_file))

    result = _log_run("t", "r")

    assert result is None
    captured = capsys.readouterr()
    assert "warning" in captured.err


def test_successful_run_appends_log(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr(cli_mod, "Anthropic", _StubClient)

    rc = main(["hello"])

    assert rc == 0
    log_file = tmp_path / "log.md"
    assert log_file.exists()
    contents = log_file.read_text(encoding="utf-8")
    assert "hello" in contents
    assert "stubbed-claude-reply" in contents


def test_log_appends_across_runs(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr(cli_mod, "Anthropic", _StubClient)

    assert main(["first task"]) == 0
    assert main(["second task"]) == 0

    contents = (tmp_path / "log.md").read_text(encoding="utf-8")
    assert contents.count("## ") == 2
    assert "first task" in contents
    assert "second task" in contents


def test_missing_api_key_does_not_create_log(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(cli_mod, "Anthropic", _StubClient)

    rc = main(["hello"])

    assert rc != 0
    assert not (tmp_path / "log.md").exists()
