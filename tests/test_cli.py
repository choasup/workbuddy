import types

import pytest

import workbuddy.cli as cli_mod
from workbuddy.cli import main


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
    assert _StubClient.last_init_kwargs == {"api_key": "sk-test"}
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


def test_main_missing_argument_exits_nonzero(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main([])
    assert excinfo.value.code != 0
    captured = capsys.readouterr()
    assert captured.err


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
