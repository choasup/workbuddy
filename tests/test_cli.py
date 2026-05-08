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


def _make_async_returning(tools):
    async def _fake(server_argv):
        return tools

    return _fake


async def _fake_async_raises_boom(server_argv):
    raise RuntimeError("boom")


def test_mcp_list_tools_happy_path(monkeypatch, capsys):
    tools = [
        types.SimpleNamespace(name="echo", description="echo the input"),
        types.SimpleNamespace(name="add", description="add two numbers"),
    ]
    monkeypatch.setattr(cli_mod, "_async_list_tools", _make_async_returning(tools))

    rc = main(["--mcp-list-tools", "--mcp-server", "fake-server-cmd", "task"])

    assert rc == 0
    captured = capsys.readouterr()
    assert "echo: echo the input" in captured.out
    assert "add: add two numbers" in captured.out


def test_mcp_list_tools_handles_empty_description(monkeypatch, capsys):
    tools = [types.SimpleNamespace(name="solo", description=None)]
    monkeypatch.setattr(cli_mod, "_async_list_tools", _make_async_returning(tools))

    rc = main(["--mcp-list-tools", "--mcp-server", "fake", "task"])

    assert rc == 0
    captured = capsys.readouterr()
    assert "solo: " in captured.out


def test_mcp_list_tools_requires_mcp_server(capsys):
    rc = main(["--mcp-list-tools", "task"])

    assert rc == 5
    captured = capsys.readouterr()
    assert "requires --mcp-server" in captured.err


def test_mcp_server_alone_requires_list_tools(capsys):
    rc = main(["--mcp-server", "fake", "task"])

    assert rc == 5
    captured = capsys.readouterr()
    assert "only meaningful with --mcp-list-tools" in captured.err


def test_mcp_list_tools_protocol_error(monkeypatch, capsys):
    monkeypatch.setattr(cli_mod, "_async_list_tools", _fake_async_raises_boom)

    rc = main(["--mcp-list-tools", "--mcp-server", "fake", "task"])

    assert rc == 5
    captured = capsys.readouterr()
    assert "MCP error:" in captured.err
    assert "boom" in captured.err
    # NOT a Python traceback dump
    assert "Traceback" not in captured.err


async def _fake_async_timeout(server_argv):
    raise TimeoutError()


def test_mcp_list_tools_timeout(monkeypatch, capsys):
    """Patch _async_list_tools to raise TimeoutError on its first await — production
    code's `except (asyncio.TimeoutError, TimeoutError)` catches it and exits 6.
    Cleaner than intercepting asyncio.run because the real asyncio plumbing runs."""
    monkeypatch.setattr(cli_mod, "_async_list_tools", _fake_async_timeout)

    rc = main(["--mcp-list-tools", "--mcp-server", "fake", "task"])

    assert rc == 6
    captured = capsys.readouterr()
    assert "did not respond within" in captured.err


def test_mcp_mutually_exclusive_with_exec(capsys):
    with pytest.raises(SystemExit) as ei:
        main(["--mcp-list-tools", "--exec", "task"])
    assert ei.value.code != 0
    captured = capsys.readouterr()
    assert ("not allowed with" in captured.err) or ("--mcp" in captured.err)


def test_mcp_mutually_exclusive_with_git(capsys):
    with pytest.raises(SystemExit) as ei:
        main(["--mcp-list-tools", "--git", "task"])
    assert ei.value.code != 0
    captured = capsys.readouterr()
    assert ("not allowed with" in captured.err) or ("--mcp" in captured.err)


def test_mcp_list_tools_ignores_task_arg(monkeypatch, capsys):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    tools = [types.SimpleNamespace(name="x", description="y")]
    monkeypatch.setattr(cli_mod, "_async_list_tools", _make_async_returning(tools))

    rc = main(["--mcp-list-tools", "--mcp-server", "fake", "please summarize"])

    assert rc == 0
    captured = capsys.readouterr()
    assert "ignores the task argument" in captured.err
    assert "x: y" in captured.out


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
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = ""):
        self.calls: list[dict] = []
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr

    def run(self, *args, **kwargs):
        self.calls.append({"args": args, "kwargs": kwargs})
        return types.SimpleNamespace(
            returncode=self.returncode, stdout=self.stdout, stderr=self.stderr
        )


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


_GIT_CONTEXT_CALL_COUNT = 3  # branch, status, log


def _input_must_not_be_called(*a, **k):
    raise AssertionError("input() should not be called for rejected/cold paths")


def _setup_git_test(monkeypatch, model_text: str, recorder: _SubprocessRecorder):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr(cli_mod, "Anthropic", _make_stub_client_returning(model_text))
    _install_subprocess_recorder(monkeypatch, recorder)


def test_git_runs_status_after_yes(tmp_path, monkeypatch):
    recorder = _SubprocessRecorder(returncode=0, stdout="main\n")
    _setup_git_test(monkeypatch, "git status", recorder)
    monkeypatch.setattr("builtins.input", lambda *a, **k: "y")

    rc = main(["--git", "task"])

    assert rc == 0
    assert len(recorder.calls) == _GIT_CONTEXT_CALL_COUNT + 1
    # context calls
    assert recorder.calls[0]["args"][0] == ["git", "rev-parse", "--abbrev-ref", "HEAD"]
    assert recorder.calls[1]["args"][0] == ["git", "status", "--porcelain=v1"]
    assert recorder.calls[2]["args"][0] == ["git", "log", "--oneline", "-10"]
    # user-confirmed call
    user_call = recorder.calls[_GIT_CONTEXT_CALL_COUNT]
    assert user_call["args"][0] == ["git", "status"]
    assert user_call["kwargs"].get("shell") is False


def test_git_rejects_non_git_argv0(tmp_path, monkeypatch, capsys):
    recorder = _SubprocessRecorder(returncode=0)
    _setup_git_test(monkeypatch, "rm -rf /", recorder)
    monkeypatch.setattr("builtins.input", _input_must_not_be_called)

    rc = main(["--git", "task"])

    assert rc == 4
    assert len(recorder.calls) == _GIT_CONTEXT_CALL_COUNT  # only context, no rm
    captured = capsys.readouterr()
    assert "start with `git`" in captured.err
    assert "Run this command?" not in captured.err


def test_git_rejects_write_subcommand_commit(tmp_path, monkeypatch, capsys):
    recorder = _SubprocessRecorder(returncode=0)
    _setup_git_test(monkeypatch, "git commit -m foo", recorder)
    monkeypatch.setattr("builtins.input", _input_must_not_be_called)

    rc = main(["--git", "task"])

    assert rc == 4
    assert len(recorder.calls) == _GIT_CONTEXT_CALL_COUNT
    captured = capsys.readouterr()
    assert "rejects subcommand `commit`" in captured.err
    assert "Run this command?" not in captured.err


def test_git_rejects_write_subcommand_push(tmp_path, monkeypatch, capsys):
    recorder = _SubprocessRecorder(returncode=0)
    _setup_git_test(monkeypatch, "git push origin main", recorder)
    monkeypatch.setattr("builtins.input", _input_must_not_be_called)

    rc = main(["--git", "task"])

    assert rc == 4
    assert len(recorder.calls) == _GIT_CONTEXT_CALL_COUNT
    captured = capsys.readouterr()
    assert "rejects subcommand `push`" in captured.err


def test_git_rejects_write_subcommand_reset(tmp_path, monkeypatch, capsys):
    recorder = _SubprocessRecorder(returncode=0)
    _setup_git_test(monkeypatch, "git reset --hard HEAD~", recorder)
    monkeypatch.setattr("builtins.input", _input_must_not_be_called)

    rc = main(["--git", "task"])

    assert rc == 4
    assert len(recorder.calls) == _GIT_CONTEXT_CALL_COUNT
    captured = capsys.readouterr()
    assert "rejects subcommand `reset`" in captured.err


def test_git_rejects_argv0_path_variant(tmp_path, monkeypatch, capsys):
    """Literal-equality on argv[0] rejects /usr/bin/git, ./git, GIT, etc."""
    recorder = _SubprocessRecorder(returncode=0)
    _setup_git_test(monkeypatch, "/usr/bin/git status", recorder)
    monkeypatch.setattr("builtins.input", _input_must_not_be_called)

    rc = main(["--git", "task"])

    assert rc == 4
    assert len(recorder.calls) == _GIT_CONTEXT_CALL_COUNT
    captured = capsys.readouterr()
    assert "start with `git`" in captured.err


def test_git_and_exec_mutually_exclusive(monkeypatch, capsys):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    with pytest.raises(SystemExit) as ei:
        main(["--git", "--exec", "task"])
    assert ei.value.code != 0
    captured = capsys.readouterr()
    assert ("not allowed with" in captured.err) or ("--git" in captured.err)


def test_git_aborts_on_n_with_history(tmp_path, monkeypatch, capsys):
    recorder = _SubprocessRecorder(returncode=0)
    _setup_git_test(monkeypatch, "git status", recorder)
    monkeypatch.setattr("builtins.input", lambda *a, **k: "n")

    rc = main(["--git", "task"])

    assert rc == 0
    captured = capsys.readouterr()
    assert "aborted" in captured.err
    rows = [
        json.loads(line)
        for line in (tmp_path / "history.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert len(rows) == 1
    assert rows[0]["git_decision"] == "aborted"
    assert "git_exit" not in rows[0]


def test_git_rejection_writes_history_record(tmp_path, monkeypatch):
    recorder = _SubprocessRecorder(returncode=0)
    _setup_git_test(monkeypatch, "git commit -m x", recorder)
    monkeypatch.setattr("builtins.input", _input_must_not_be_called)

    rc = main(["--git", "task"])

    assert rc == 4
    rows = [
        json.loads(line)
        for line in (tmp_path / "history.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert len(rows) == 1
    assert rows[0]["git_decision"] == "rejected"
    assert "git_rejection_reason" in rows[0]
    assert "commit" in rows[0]["git_rejection_reason"]


def test_git_branch_d_is_cold_rejected(tmp_path, monkeypatch, capsys):
    recorder = _SubprocessRecorder(returncode=0)
    _setup_git_test(monkeypatch, "git branch -d feature", recorder)
    monkeypatch.setattr("builtins.input", _input_must_not_be_called)

    rc = main(["--git", "task"])

    assert rc == 4
    assert len(recorder.calls) == _GIT_CONTEXT_CALL_COUNT
    captured = capsys.readouterr()
    assert "rejects subcommand `branch`" in captured.err
    rows = [
        json.loads(line)
        for line in (tmp_path / "history.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert rows[0]["git_decision"] == "rejected"


def test_git_branch_D_force_is_cold_rejected(tmp_path, monkeypatch, capsys):
    recorder = _SubprocessRecorder(returncode=0)
    _setup_git_test(monkeypatch, "git branch -D feature", recorder)
    monkeypatch.setattr("builtins.input", _input_must_not_be_called)

    rc = main(["--git", "task"])

    assert rc == 4
    assert len(recorder.calls) == _GIT_CONTEXT_CALL_COUNT
    captured = capsys.readouterr()
    assert "rejects subcommand `branch`" in captured.err


def test_git_branch_m_rename_is_cold_rejected(tmp_path, monkeypatch, capsys):
    recorder = _SubprocessRecorder(returncode=0)
    _setup_git_test(monkeypatch, "git branch -m oldname newname", recorder)
    monkeypatch.setattr("builtins.input", _input_must_not_be_called)

    rc = main(["--git", "task"])

    assert rc == 4
    assert len(recorder.calls) == _GIT_CONTEXT_CALL_COUNT
    captured = capsys.readouterr()
    assert "rejects subcommand `branch`" in captured.err


def test_git_branch_list_is_now_cold_rejected(tmp_path, monkeypatch, capsys):
    """Strategy-A trade-off: read-only `git branch` (plain listing) is no longer reachable
    via --git, because `branch` was dropped from the allowlist to block its write variants
    (-d/-D/-m/-c). Users wanting a read-only branch listing should fall back to --exec.
    Do NOT 'fix' this rejection by re-adding `branch` to the allowlist without also
    adding flag-level write rejection."""
    recorder = _SubprocessRecorder(returncode=0)
    _setup_git_test(monkeypatch, "git branch", recorder)
    monkeypatch.setattr("builtins.input", _input_must_not_be_called)

    rc = main(["--git", "task"])

    assert rc == 4
    assert len(recorder.calls) == _GIT_CONTEXT_CALL_COUNT
    captured = capsys.readouterr()
    assert "rejects subcommand `branch`" in captured.err


def test_git_reflog_expire_is_cold_rejected(tmp_path, monkeypatch, capsys):
    recorder = _SubprocessRecorder(returncode=0)
    _setup_git_test(monkeypatch, "git reflog expire --expire=0 --all", recorder)
    monkeypatch.setattr("builtins.input", _input_must_not_be_called)

    rc = main(["--git", "task"])

    assert rc == 4
    assert len(recorder.calls) == _GIT_CONTEXT_CALL_COUNT
    captured = capsys.readouterr()
    assert "rejects subcommand `reflog`" in captured.err


def test_git_reflog_show_is_now_cold_rejected(tmp_path, monkeypatch, capsys):
    """Strategy-A trade-off: read-only `git reflog show` is no longer reachable via --git,
    because `reflog` was dropped from the allowlist to block its write variants
    (`reflog expire`, `reflog delete`). Users wanting reflog inspection should fall back
    to --exec. Do NOT 'fix' this rejection by re-adding `reflog` to the allowlist without
    also adding subcommand-level write rejection."""
    recorder = _SubprocessRecorder(returncode=0)
    _setup_git_test(monkeypatch, "git reflog show HEAD", recorder)
    monkeypatch.setattr("builtins.input", _input_must_not_be_called)

    rc = main(["--git", "task"])

    assert rc == 4
    assert len(recorder.calls) == _GIT_CONTEXT_CALL_COUNT
    captured = capsys.readouterr()
    assert "rejects subcommand `reflog`" in captured.err


def test_git_context_failure_warns_and_continues(tmp_path, monkeypatch, capsys):
    """If the branch query fails (not a git repo), warn and still proceed to API."""
    recorder = _SubprocessRecorder(returncode=128, stdout="", stderr="not a git repo")
    _setup_git_test(monkeypatch, "git status", recorder)
    monkeypatch.setattr("builtins.input", lambda *a, **k: "y")

    rc = main(["--git", "task"])

    captured = capsys.readouterr()
    # Warning was emitted AND main proceeded all the way through to the user-confirmed
    # subprocess call (rc reflects the recorder's stub returncode for that call).
    assert "warning: git context unavailable" in captured.err
    assert rc == 128
    # Single failed context call (returns early on first failure) + the user-confirmed call
    assert any(call["args"][0] == ["git", "status"] for call in recorder.calls)


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
