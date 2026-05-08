import json
import types

import anthropic
import pytest

import workbuddy.cli as cli_mod
from workbuddy.cli import (
    MAX_HISTORY_ROWS,
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


def test_successful_run_appends_history(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr(cli_mod, "Anthropic", _StubClient)

    rc = main(["task"])

    assert rc == 0
    history_file = tmp_path / "history.jsonl"
    assert history_file.exists()
    rows = [json.loads(line) for line in history_file.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    row = rows[0]
    assert set(row) >= {"ts", "task", "model", "response_chars"}
    assert row["task"] == "task"
    assert row["model"] == "claude-sonnet-4-6"
    assert row["response_chars"] == len("stubbed-claude-reply")


def test_history_appends_across_runs(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr(cli_mod, "Anthropic", _StubClient)

    assert main(["first"]) == 0
    assert main(["second"]) == 0

    rows = [
        json.loads(line)
        for line in (tmp_path / "history.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert len(rows) == 2
    assert rows[0]["task"] == "first"
    assert rows[1]["task"] == "second"


def test_api_error_does_not_create_history(tmp_path, monkeypatch, capsys):
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
    assert not (tmp_path / "history.jsonl").exists()


def test_history_rotation_caps_at_max(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr(cli_mod, "Anthropic", _StubClient)

    history_file = tmp_path / "history.jsonl"
    seed_lines = [json.dumps({"i": i}) + "\n" for i in range(MAX_HISTORY_ROWS)]
    history_file.write_text("".join(seed_lines), encoding="utf-8")

    rc = main(["new task"])

    assert rc == 0
    rows = [
        json.loads(line)
        for line in history_file.read_text(encoding="utf-8").splitlines()
    ]
    assert len(rows) == MAX_HISTORY_ROWS
    assert rows[-1].get("task") == "new task"
    assert rows[-1].get("model") == "claude-sonnet-4-6"


def test_config_silent_when_default_model_absent(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr(cli_mod, "Anthropic", _StubClient)
    (tmp_path / "config.json").write_text(
        json.dumps({"unrelated_key": 7}), encoding="utf-8"
    )

    rc = main(["task"])

    assert rc == 0
    assert _StubClient.last_messages.last_kwargs["model"] == "claude-sonnet-4-6"
    captured = capsys.readouterr()
    assert captured.err == ""


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


def _make_stub_client_returning(text: str):
    class _C:
        last_messages = None

        def __init__(self, **kwargs):
            self.messages = _StubMessages(text)
            type(self).last_messages = self.messages

    return _C


class _SubprocessRecorder:
    def __init__(self, returncode: int = 0):
        self.calls: list[dict] = []
        self.returncode = returncode

    def run(self, *args, **kwargs):
        self.calls.append({"args": args, "kwargs": kwargs})
        return types.SimpleNamespace(returncode=self.returncode)


def _install_subprocess_recorder(monkeypatch, recorder: _SubprocessRecorder) -> None:
    monkeypatch.setattr(cli_mod.subprocess, "run", recorder.run)


def test_exec_runs_after_yes(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr(cli_mod, "Anthropic", _make_stub_client_returning("echo hello"))
    monkeypatch.setattr("builtins.input", lambda *a, **k: "y")
    recorder = _SubprocessRecorder(returncode=0)
    _install_subprocess_recorder(monkeypatch, recorder)

    rc = main(["--exec", "task"])

    assert rc == 0
    assert len(recorder.calls) == 1
    call = recorder.calls[0]
    assert call["args"][0] == ["echo", "hello"]
    assert call["kwargs"].get("shell") is False


def test_exec_aborts_on_n(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr(cli_mod, "Anthropic", _make_stub_client_returning("echo hello"))
    monkeypatch.setattr("builtins.input", lambda *a, **k: "n")
    recorder = _SubprocessRecorder()
    _install_subprocess_recorder(monkeypatch, recorder)

    rc = main(["--exec", "task"])

    assert rc == 0
    assert recorder.calls == []
    captured = capsys.readouterr()
    assert "aborted" in captured.err


def test_exec_aborts_on_empty_input(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr(cli_mod, "Anthropic", _make_stub_client_returning("echo hello"))
    monkeypatch.setattr("builtins.input", lambda *a, **k: "")
    recorder = _SubprocessRecorder()
    _install_subprocess_recorder(monkeypatch, recorder)

    rc = main(["--exec", "task"])

    assert rc == 0
    assert recorder.calls == []
    captured = capsys.readouterr()
    assert "aborted" in captured.err


def test_exec_aborts_on_eof(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr(cli_mod, "Anthropic", _make_stub_client_returning("echo hello"))

    def _raises_eof(*a, **k):
        raise EOFError

    monkeypatch.setattr("builtins.input", _raises_eof)
    recorder = _SubprocessRecorder()
    _install_subprocess_recorder(monkeypatch, recorder)

    rc = main(["--exec", "task"])

    assert rc == 0
    assert recorder.calls == []


@pytest.mark.parametrize("model_text", ["", "   "])
def test_exec_empty_model_response_errors(tmp_path, monkeypatch, capsys, model_text):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr(cli_mod, "Anthropic", _make_stub_client_returning(model_text))
    recorder = _SubprocessRecorder()
    _install_subprocess_recorder(monkeypatch, recorder)

    rc = main(["--exec", "task"])

    assert rc == 3
    assert recorder.calls == []
    captured = capsys.readouterr()
    assert "no command" in captured.err


def test_exec_shell_metacharacters_are_not_expanded(tmp_path, monkeypatch):
    """Safety canary — do NOT delete casually. Asserts shell=False + literal-arg parsing."""
    dangerous = "echo a ; rm -rf /tmp/should-not-exist"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr(cli_mod, "Anthropic", _make_stub_client_returning(dangerous))
    monkeypatch.setattr("builtins.input", lambda *a, **k: "y")
    recorder = _SubprocessRecorder(returncode=0)
    _install_subprocess_recorder(monkeypatch, recorder)

    rc = main(["--exec", "task"])

    assert rc == 0
    assert len(recorder.calls) == 1
    call = recorder.calls[0]
    assert call["args"][0] == ["echo", "a", ";", "rm", "-rf", "/tmp/should-not-exist"]
    assert call["kwargs"].get("shell") is False


def test_exec_history_records_run_decision_and_exit(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr(cli_mod, "Anthropic", _make_stub_client_returning("echo hi"))
    monkeypatch.setattr("builtins.input", lambda *a, **k: "y")
    recorder = _SubprocessRecorder(returncode=7)
    _install_subprocess_recorder(monkeypatch, recorder)

    rc = main(["--exec", "task"])

    assert rc == 7
    rows = [
        json.loads(line)
        for line in (tmp_path / "history.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert len(rows) == 1
    row = rows[0]
    assert row["exec_command"] == "echo hi"
    assert row["exec_decision"] == "run"
    assert row["exec_exit"] == 7


def test_exec_aborted_history_record(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr(cli_mod, "Anthropic", _make_stub_client_returning("echo hi"))
    monkeypatch.setattr("builtins.input", lambda *a, **k: "n")
    recorder = _SubprocessRecorder()
    _install_subprocess_recorder(monkeypatch, recorder)

    rc = main(["--exec", "task"])

    assert rc == 0
    rows = [
        json.loads(line)
        for line in (tmp_path / "history.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert len(rows) == 1
    row = rows[0]
    assert row["exec_command"] == "echo hi"
    assert row["exec_decision"] == "aborted"
    assert "exec_exit" not in row


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
