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


def _make_async_call_tool_returning(text: str, is_error: bool = False, attr: str = "isError"):
    async def _fake(server_argv, tool_name, tool_args):
        block = types.SimpleNamespace(text=text)
        return types.SimpleNamespace(content=[block], **{attr: is_error})

    return _fake


async def _async_call_tool_must_not_be_called(*a, **k):
    raise AssertionError("_async_call_tool should not be called when aborted/cold-rejected")


async def _async_call_tool_raises_timeout(*a, **k):
    raise TimeoutError()


async def _async_call_tool_raises_boom(*a, **k):
    raise RuntimeError("boom")


_FAKE_LAST_CALL: dict = {}


async def _fake_async_call_tool_recording(server_argv, tool_name, tool_args):
    _FAKE_LAST_CALL["server_argv"] = server_argv
    _FAKE_LAST_CALL["tool_name"] = tool_name
    _FAKE_LAST_CALL["tool_args"] = tool_args
    block = types.SimpleNamespace(text="42")
    return types.SimpleNamespace(content=[block], isError=False)


def test_mcp_call_tool_runs_after_yes(tmp_path, monkeypatch, capsys):
    _FAKE_LAST_CALL.clear()
    monkeypatch.setattr(cli_mod, "_async_call_tool", _fake_async_call_tool_recording)
    monkeypatch.setattr("builtins.input", lambda *a, **k: "y")

    rc = main(
        [
            "--mcp-call-tool",
            "echo",
            "--mcp-tool-args",
            '{"x": 1}',
            "--mcp-server",
            "fake",
            "task",
        ]
    )

    assert rc == 0
    captured = capsys.readouterr()
    assert "42" in captured.out
    assert _FAKE_LAST_CALL == {
        "server_argv": ["fake"],
        "tool_name": "echo",
        "tool_args": {"x": 1},
    }
    rows = [
        json.loads(line)
        for line in (tmp_path / "history.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert rows[0]["mcp_tool_name"] == "echo"
    assert rows[0]["mcp_tool_args"] == {"x": 1}
    assert rows[0]["mcp_decision"] == "run"
    assert rows[0]["mcp_is_error"] is False


def test_mcp_call_tool_aborts_on_n(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli_mod, "_async_call_tool", _async_call_tool_must_not_be_called)
    monkeypatch.setattr("builtins.input", lambda *a, **k: "n")

    rc = main(
        [
            "--mcp-call-tool",
            "echo",
            "--mcp-server",
            "fake",
            "task",
        ]
    )

    assert rc == 0
    captured = capsys.readouterr()
    assert "aborted" in captured.err
    rows = [
        json.loads(line)
        for line in (tmp_path / "history.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert rows[0]["mcp_decision"] == "aborted"
    assert "mcp_is_error" not in rows[0]


def test_mcp_call_tool_invalid_json_args_is_cold_rejected(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli_mod, "_async_call_tool", _async_call_tool_must_not_be_called)
    monkeypatch.setattr("builtins.input", _input_must_not_be_called)

    rc = main(
        [
            "--mcp-call-tool",
            "echo",
            "--mcp-tool-args",
            "not json",
            "--mcp-server",
            "fake",
            "task",
        ]
    )

    assert rc == 5
    captured = capsys.readouterr()
    assert "must be a JSON object" in captured.err
    assert not (tmp_path / "history.jsonl").exists()


def test_mcp_call_tool_args_must_be_dict_not_array(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli_mod, "_async_call_tool", _async_call_tool_must_not_be_called)
    monkeypatch.setattr("builtins.input", _input_must_not_be_called)

    rc = main(
        [
            "--mcp-call-tool",
            "echo",
            "--mcp-tool-args",
            "[1, 2, 3]",
            "--mcp-server",
            "fake",
            "task",
        ]
    )

    assert rc == 5
    captured = capsys.readouterr()
    assert "must be a JSON object" in captured.err
    assert not (tmp_path / "history.jsonl").exists()


def test_mcp_call_tool_requires_mcp_server(capsys):
    rc = main(["--mcp-call-tool", "echo", "task"])

    assert rc == 5
    captured = capsys.readouterr()
    assert "requires --mcp-server" in captured.err


def test_mcp_tool_args_alone_errors(capsys):
    rc = main(["--mcp-tool-args", '{"x": 1}', "task"])

    assert rc == 5
    captured = capsys.readouterr()
    assert "only meaningful with --mcp-call-tool" in captured.err


def test_mcp_call_tool_is_error_returns_5(tmp_path, monkeypatch, capsys):
    fake = _make_async_call_tool_returning("failed: bad input", is_error=True)
    monkeypatch.setattr(cli_mod, "_async_call_tool", fake)
    monkeypatch.setattr("builtins.input", lambda *a, **k: "y")

    rc = main(["--mcp-call-tool", "echo", "--mcp-server", "fake", "task"])

    assert rc == 5
    captured = capsys.readouterr()
    assert "failed: bad input" in captured.out
    rows = [
        json.loads(line)
        for line in (tmp_path / "history.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert rows[0]["mcp_is_error"] is True
    assert rows[0]["mcp_decision"] == "run"


def test_mcp_call_tool_timeout(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli_mod, "_async_call_tool", _async_call_tool_raises_timeout)
    monkeypatch.setattr("builtins.input", lambda *a, **k: "y")

    rc = main(["--mcp-call-tool", "echo", "--mcp-server", "fake", "task"])

    assert rc == 6
    captured = capsys.readouterr()
    assert "did not respond within" in captured.err
    assert not (tmp_path / "history.jsonl").exists()


def test_mcp_call_tool_protocol_error(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli_mod, "_async_call_tool", _async_call_tool_raises_boom)
    monkeypatch.setattr("builtins.input", lambda *a, **k: "y")

    rc = main(["--mcp-call-tool", "echo", "--mcp-server", "fake", "task"])

    assert rc == 5
    captured = capsys.readouterr()
    assert "MCP error:" in captured.err
    assert "boom" in captured.err
    assert "Traceback" not in captured.err
    assert not (tmp_path / "history.jsonl").exists()


def test_mcp_call_tool_default_args_is_empty_dict(tmp_path, monkeypatch):
    _FAKE_LAST_CALL.clear()
    monkeypatch.setattr(cli_mod, "_async_call_tool", _fake_async_call_tool_recording)
    monkeypatch.setattr("builtins.input", lambda *a, **k: "y")

    rc = main(["--mcp-call-tool", "echo", "--mcp-server", "fake", "task"])

    assert rc == 0
    assert _FAKE_LAST_CALL["tool_args"] == {}


def test_mcp_call_tool_mutually_exclusive_with_list_tools(capsys):
    with pytest.raises(SystemExit) as ei:
        main(["--mcp-call-tool", "x", "--mcp-list-tools", "task"])
    assert ei.value.code != 0


def test_mcp_call_tool_mutually_exclusive_with_exec_and_git(capsys):
    with pytest.raises(SystemExit):
        main(["--mcp-call-tool", "x", "--exec", "task"])
    with pytest.raises(SystemExit):
        main(["--mcp-call-tool", "x", "--git", "task"])


def _make_anthropic_with_blocks(blocks):
    class _StubMessages:
        def __init__(self):
            self.last_kwargs: dict | None = None

        def create(self, **kwargs):
            self.last_kwargs = kwargs
            return types.SimpleNamespace(content=blocks)

    class _StubClientWithToolUse:
        last_messages = None

        def __init__(self, **kwargs):
            self.messages = _StubMessages()
            type(self).last_messages = self.messages

    return _StubClientWithToolUse


def _text_block(text: str):
    return types.SimpleNamespace(type="text", text=text)


def _tool_use_block(name: str, input_dict: dict):
    return types.SimpleNamespace(type="tool_use", name=name, input=input_dict)


async def _fake_list_returning(tools_list):
    async def _fake(server_argv):
        return tools_list

    return _fake


_LAST_CLAUDE_CALL_TOOL: dict = {}


async def _fake_async_call_tool_for_claude(server_argv, tool_name, tool_args):
    _LAST_CLAUDE_CALL_TOOL["server_argv"] = server_argv
    _LAST_CLAUDE_CALL_TOOL["tool_name"] = tool_name
    _LAST_CLAUDE_CALL_TOOL["tool_args"] = tool_args
    return types.SimpleNamespace(
        content=[types.SimpleNamespace(text="echoed: 1")], isError=False
    )


def test_mcp_claude_runs_tool_after_yes(tmp_path, monkeypatch, capsys):
    _LAST_CLAUDE_CALL_TOOL.clear()
    server_tools = [
        types.SimpleNamespace(name="echo", description="echo input", inputSchema={})
    ]

    async def _fake_list(server_argv):
        return server_tools

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr(cli_mod, "_async_list_tools", _fake_list)
    monkeypatch.setattr(
        cli_mod,
        "Anthropic",
        _make_anthropic_with_blocks(
            [_text_block("I'll echo that"), _tool_use_block("echo", {"x": 1})]
        ),
    )
    monkeypatch.setattr(cli_mod, "_async_call_tool", _fake_async_call_tool_for_claude)
    monkeypatch.setattr("builtins.input", lambda *a, **k: "y")

    rc = main(["--mcp-claude", "--mcp-server", "fake", "echo hi"])

    assert rc == 0
    captured = capsys.readouterr()
    assert "Claude: I'll echo that" in captured.out
    assert "echoed: 1" in captured.out
    assert _LAST_CLAUDE_CALL_TOOL["tool_name"] == "echo"
    assert _LAST_CLAUDE_CALL_TOOL["tool_args"] == {"x": 1}
    rows = [
        json.loads(line)
        for line in (tmp_path / "history.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert rows[0]["mcp_decision"] == "run"
    assert rows[0]["mcp_proposed_by"] == "claude"
    assert "echo" in rows[0]["claude_reasoning"]


def test_mcp_claude_no_tool_use_prints_text_only(tmp_path, monkeypatch, capsys):
    server_tools = [types.SimpleNamespace(name="echo", description="", inputSchema={})]

    async def _fake_list(server_argv):
        return server_tools

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr(cli_mod, "_async_list_tools", _fake_list)
    monkeypatch.setattr(
        cli_mod,
        "Anthropic",
        _make_anthropic_with_blocks([_text_block("Just a thought, no tool needed.")]),
    )
    monkeypatch.setattr(
        cli_mod, "_async_call_tool", _async_call_tool_must_not_be_called
    )

    rc = main(["--mcp-claude", "--mcp-server", "fake", "task"])

    assert rc == 0
    captured = capsys.readouterr()
    assert "Just a thought, no tool needed." in captured.out
    rows = [
        json.loads(line)
        for line in (tmp_path / "history.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert rows[0]["mcp_decision"] == "text-only"
    assert rows[0]["mcp_proposed_by"] == "claude"


def test_mcp_claude_multi_tool_use_is_cold_rejected(tmp_path, monkeypatch, capsys):
    server_tools = [types.SimpleNamespace(name="echo", description="", inputSchema={})]

    async def _fake_list(server_argv):
        return server_tools

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr(cli_mod, "_async_list_tools", _fake_list)
    monkeypatch.setattr(
        cli_mod,
        "Anthropic",
        _make_anthropic_with_blocks(
            [
                _tool_use_block("echo", {"x": 1}),
                _tool_use_block("echo", {"x": 2}),
            ]
        ),
    )
    monkeypatch.setattr(
        cli_mod, "_async_call_tool", _async_call_tool_must_not_be_called
    )
    monkeypatch.setattr("builtins.input", _input_must_not_be_called)

    rc = main(["--mcp-claude", "--mcp-server", "fake", "task"])

    assert rc == 5
    captured = capsys.readouterr()
    assert "Claude proposed 2 tool calls" in captured.err
    rows = [
        json.loads(line)
        for line in (tmp_path / "history.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert rows[0]["mcp_decision"] == "rejected"
    assert rows[0]["mcp_rejection_reason"] == "multi-tool"


def test_mcp_claude_hallucinated_tool_is_cold_rejected(tmp_path, monkeypatch, capsys):
    server_tools = [types.SimpleNamespace(name="echo", description="", inputSchema={})]

    async def _fake_list(server_argv):
        return server_tools

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr(cli_mod, "_async_list_tools", _fake_list)
    monkeypatch.setattr(
        cli_mod,
        "Anthropic",
        _make_anthropic_with_blocks([_tool_use_block("rm", {"path": "/"})]),
    )
    monkeypatch.setattr(
        cli_mod, "_async_call_tool", _async_call_tool_must_not_be_called
    )
    monkeypatch.setattr("builtins.input", _input_must_not_be_called)

    rc = main(["--mcp-claude", "--mcp-server", "fake", "task"])

    assert rc == 5
    captured = capsys.readouterr()
    assert "hallucination" in captured.err
    assert "'rm'" in captured.err
    rows = [
        json.loads(line)
        for line in (tmp_path / "history.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert rows[0]["mcp_decision"] == "rejected"
    assert rows[0]["mcp_rejection_reason"] == "hallucinated-tool"


def test_mcp_claude_aborts_on_n(tmp_path, monkeypatch, capsys):
    server_tools = [types.SimpleNamespace(name="echo", description="", inputSchema={})]

    async def _fake_list(server_argv):
        return server_tools

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr(cli_mod, "_async_list_tools", _fake_list)
    monkeypatch.setattr(
        cli_mod,
        "Anthropic",
        _make_anthropic_with_blocks([_tool_use_block("echo", {"x": 1})]),
    )
    monkeypatch.setattr(
        cli_mod, "_async_call_tool", _async_call_tool_must_not_be_called
    )
    monkeypatch.setattr("builtins.input", lambda *a, **k: "n")

    rc = main(["--mcp-claude", "--mcp-server", "fake", "task"])

    assert rc == 0
    captured = capsys.readouterr()
    assert "aborted" in captured.err
    rows = [
        json.loads(line)
        for line in (tmp_path / "history.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert rows[0]["mcp_decision"] == "aborted"
    assert rows[0]["mcp_proposed_by"] == "claude"


def test_mcp_claude_requires_mcp_server(monkeypatch, capsys):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    rc = main(["--mcp-claude", "task"])
    assert rc == 5
    captured = capsys.readouterr()
    assert "requires --mcp-server" in captured.err


def test_mcp_claude_requires_api_key(monkeypatch, capsys):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    rc = main(["--mcp-claude", "--mcp-server", "fake", "task"])
    assert rc == 1
    captured = capsys.readouterr()
    assert "ANTHROPIC_API_KEY" in captured.err


def test_mcp_claude_mutually_exclusive_with_other_modes(capsys):
    for other in ("--exec", "--git", "--mcp-list-tools"):
        with pytest.raises(SystemExit):
            main(["--mcp-claude", other, "task"])
    with pytest.raises(SystemExit):
        main(["--mcp-claude", "--mcp-call-tool", "x", "task"])


def test_mcp_claude_tool_isError_returns_5(tmp_path, monkeypatch, capsys):
    server_tools = [types.SimpleNamespace(name="echo", description="", inputSchema={})]

    async def _fake_list(server_argv):
        return server_tools

    async def _fake_call(server_argv, tool_name, tool_args):
        return types.SimpleNamespace(
            content=[types.SimpleNamespace(text="tool failed")], isError=True
        )

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr(cli_mod, "_async_list_tools", _fake_list)
    monkeypatch.setattr(
        cli_mod,
        "Anthropic",
        _make_anthropic_with_blocks([_tool_use_block("echo", {"x": 1})]),
    )
    monkeypatch.setattr(cli_mod, "_async_call_tool", _fake_call)
    monkeypatch.setattr("builtins.input", lambda *a, **k: "y")

    rc = main(["--mcp-claude", "--mcp-server", "fake", "task"])

    assert rc == 5
    captured = capsys.readouterr()
    assert "tool failed" in captured.out
    rows = [
        json.loads(line)
        for line in (tmp_path / "history.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert rows[0]["mcp_is_error"] is True


def test_mcp_call_tool_history_now_has_proposed_by_user(tmp_path, monkeypatch):
    """Forward-compat for slice-3 audit queries: slice-2 user-driven calls
    must record mcp_proposed_by="user" so reports can distinguish them from
    Claude-proposed calls."""
    monkeypatch.setattr(cli_mod, "_async_call_tool", _fake_async_call_tool_recording)
    monkeypatch.setattr("builtins.input", lambda *a, **k: "y")

    rc = main(
        ["--mcp-call-tool", "echo", "--mcp-server", "fake", "task"]
    )

    assert rc == 0
    rows = [
        json.loads(line)
        for line in (tmp_path / "history.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert rows[0]["mcp_proposed_by"] == "user"


class _ScriptedMessages:
    """Stub that returns pre-built responses per call to .create()."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.create_calls = []

    def create(self, **kwargs):
        # Snapshot kwargs at call time — the production `messages` list is mutated
        # across turns, so a stored reference would show the final state, not what
        # this specific call observed.
        captured = dict(kwargs)
        if "messages" in captured:
            captured["messages"] = list(captured["messages"])
        self.create_calls.append(captured)
        if not self._responses:
            raise AssertionError("ran out of scripted responses")
        next_response = self._responses.pop(0)
        # Allow tests to inject exceptions at specific call indices by passing
        # an Exception instance in the scripted list.
        if isinstance(next_response, BaseException):
            raise next_response
        return next_response


def _make_scripted_anthropic(responses):
    scripted = _ScriptedMessages(responses)

    class _ScriptedClient:
        def __init__(self, **kwargs):
            self.messages = scripted

    return _ScriptedClient, scripted


def _agent_tool_use_response(name: str, input_dict: dict, tu_id: str = "tu_1"):
    return types.SimpleNamespace(
        content=[
            types.SimpleNamespace(
                type="tool_use", name=name, input=input_dict, id=tu_id
            )
        ]
    )


def _agent_text_response(text: str):
    return types.SimpleNamespace(content=[_text_block(text)])


async def _async_call_tool_returning(text: str, is_error: bool = False):
    async def _fake(server_argv, tool_name, tool_args):
        return types.SimpleNamespace(
            content=[types.SimpleNamespace(text=text)], isError=is_error
        )

    return _fake


def _make_async_call_tool_scripted(scripted_outputs):
    """Returns an async fake that pops one (text, is_error) per call."""
    queue = list(scripted_outputs)

    async def _fake(server_argv, tool_name, tool_args):
        if not queue:
            raise AssertionError("ran out of scripted call_tool outputs")
        text, is_error = queue.pop(0)
        return types.SimpleNamespace(
            content=[types.SimpleNamespace(text=text)], isError=is_error
        )

    return _fake


def _setup_agent_test(monkeypatch, server_tools_names, anthropic_responses, call_tool_text="result"):
    server_tools = [
        types.SimpleNamespace(name=n, description="", inputSchema={})
        for n in server_tools_names
    ]

    async def _fake_list(server_argv):
        return server_tools

    async def _fake_call(server_argv, tool_name, tool_args):
        return types.SimpleNamespace(
            content=[types.SimpleNamespace(text=call_tool_text)], isError=False
        )

    AnthropicCls, scripted = _make_scripted_anthropic(anthropic_responses)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr(cli_mod, "_async_list_tools", _fake_list)
    monkeypatch.setattr(cli_mod, "Anthropic", AnthropicCls)
    monkeypatch.setattr(cli_mod, "_async_call_tool", _fake_call)
    return scripted


def test_mcp_agent_two_turns_then_final(tmp_path, monkeypatch, capsys):
    scripted = _setup_agent_test(
        monkeypatch,
        ["echo"],
        [
            _agent_tool_use_response("echo", {"x": 1}),
            _agent_text_response("all done"),
        ],
        call_tool_text="result1",
    )
    monkeypatch.setattr("builtins.input", lambda *a, **k: "y")

    rc = main(["--mcp-agent", "--mcp-server", "fake", "task"])

    assert rc == 0
    captured = capsys.readouterr()
    assert "Turn 1/3" in captured.err
    assert "result1" in captured.out
    assert "all done" in captured.out
    assert len(scripted.create_calls) == 2
    # Turn 2's messages list should have grown to include the assistant turn + tool_result
    turn2_messages = scripted.create_calls[1]["messages"]
    assert len(turn2_messages) == 3
    assert turn2_messages[1]["role"] == "assistant"
    assert turn2_messages[2]["role"] == "user"
    rows = [
        json.loads(line)
        for line in (tmp_path / "history.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert len(rows) == 2
    assert rows[0]["mcp_decision"] == "run"
    assert rows[0]["turn_index"] == 0
    assert rows[1]["mcp_decision"] == "final-text"
    assert rows[1]["turn_index"] == 1


def test_mcp_agent_user_aborts_mid_loop(tmp_path, monkeypatch, capsys):
    scripted = _setup_agent_test(
        monkeypatch,
        ["echo"],
        [
            _agent_tool_use_response("echo", {"x": 1}),
            _agent_text_response("not reached"),
        ],
    )
    monkeypatch.setattr(cli_mod, "_async_call_tool", _async_call_tool_must_not_be_called)
    monkeypatch.setattr("builtins.input", lambda *a, **k: "n")

    rc = main(["--mcp-agent", "--mcp-server", "fake", "task"])

    assert rc == 0
    captured = capsys.readouterr()
    assert "aborted at turn 1" in captured.err
    # Only first response was consumed
    assert len(scripted.create_calls) == 1
    rows = [
        json.loads(line)
        for line in (tmp_path / "history.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert len(rows) == 1
    assert rows[0]["mcp_decision"] == "aborted-mid-loop"


def test_mcp_agent_max_turns_reached(tmp_path, monkeypatch, capsys):
    scripted = _setup_agent_test(
        monkeypatch,
        ["echo"],
        [
            _agent_tool_use_response("echo", {"x": 1}, tu_id="tu_1"),
            _agent_tool_use_response("echo", {"x": 2}, tu_id="tu_2"),
        ],
    )
    monkeypatch.setattr("builtins.input", lambda *a, **k: "y")

    rc = main(
        ["--mcp-agent", "--mcp-agent-max-turns", "2", "--mcp-server", "fake", "task"]
    )

    assert rc == 7
    captured = capsys.readouterr()
    assert "hit max turns (2)" in captured.err
    rows = [
        json.loads(line)
        for line in (tmp_path / "history.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert len(rows) == 3
    assert rows[0]["mcp_decision"] == "run"
    assert rows[1]["mcp_decision"] == "run"
    assert rows[2]["mcp_decision"] == "max-turns-reached"
    assert rows[2]["turn_index"] == 2


def test_mcp_agent_max_turns_above_hard_cap_rejected(monkeypatch, capsys):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    rc = main(
        ["--mcp-agent", "--mcp-agent-max-turns", "99", "--mcp-server", "fake", "task"]
    )
    assert rc == 5
    captured = capsys.readouterr()
    assert "must be between 1 and 5" in captured.err


def test_mcp_agent_max_turns_zero_rejected(monkeypatch, capsys):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    rc = main(
        ["--mcp-agent", "--mcp-agent-max-turns", "0", "--mcp-server", "fake", "task"]
    )
    assert rc == 5
    captured = capsys.readouterr()
    assert "must be between 1 and 5" in captured.err


def test_mcp_agent_max_turns_alone_rejected(monkeypatch, capsys):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    rc = main(["--mcp-agent-max-turns", "2", "task"])
    assert rc == 5
    captured = capsys.readouterr()
    assert "only meaningful with --mcp-agent" in captured.err


def test_mcp_agent_multi_tool_per_turn_cold_rejected(tmp_path, monkeypatch, capsys):
    multi = types.SimpleNamespace(
        content=[
            types.SimpleNamespace(type="tool_use", name="echo", input={"x": 1}, id="t1"),
            types.SimpleNamespace(type="tool_use", name="echo", input={"x": 2}, id="t2"),
        ]
    )
    _setup_agent_test(monkeypatch, ["echo"], [multi])
    monkeypatch.setattr("builtins.input", _input_must_not_be_called)
    monkeypatch.setattr(cli_mod, "_async_call_tool", _async_call_tool_must_not_be_called)

    rc = main(["--mcp-agent", "--mcp-server", "fake", "task"])

    assert rc == 5
    captured = capsys.readouterr()
    assert "multi-tool" in captured.err.lower() or "2 tool calls" in captured.err
    rows = [
        json.loads(line)
        for line in (tmp_path / "history.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert rows[0]["mcp_rejection_reason"] == "multi-tool-per-turn"


def test_mcp_agent_hallucinated_tool_cold_rejected(tmp_path, monkeypatch, capsys):
    _setup_agent_test(
        monkeypatch, ["echo"], [_agent_tool_use_response("rm", {"path": "/"})]
    )
    monkeypatch.setattr("builtins.input", _input_must_not_be_called)
    monkeypatch.setattr(cli_mod, "_async_call_tool", _async_call_tool_must_not_be_called)

    rc = main(["--mcp-agent", "--mcp-server", "fake", "task"])

    assert rc == 5
    captured = capsys.readouterr()
    assert "hallucination" in captured.err
    rows = [
        json.loads(line)
        for line in (tmp_path / "history.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert rows[0]["mcp_rejection_reason"] == "hallucinated-tool"


def test_mcp_agent_requires_mcp_server(monkeypatch, capsys):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    rc = main(["--mcp-agent", "task"])
    assert rc == 5
    captured = capsys.readouterr()
    assert "requires --mcp-server" in captured.err


def test_mcp_agent_mutually_exclusive_with_other_modes(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    for other_args in (
        ["--exec"],
        ["--git"],
        ["--mcp-list-tools"],
        ["--mcp-call-tool", "x"],
        ["--mcp-claude"],
    ):
        with pytest.raises(SystemExit):
            main(["--mcp-agent", *other_args, "task"])


def test_mcp_agent_text_only_first_response_is_final(tmp_path, monkeypatch, capsys):
    scripted = _setup_agent_test(
        monkeypatch, ["echo"], [_agent_text_response("immediate answer")]
    )
    monkeypatch.setattr("builtins.input", _input_must_not_be_called)
    monkeypatch.setattr(cli_mod, "_async_call_tool", _async_call_tool_must_not_be_called)

    rc = main(["--mcp-agent", "--mcp-server", "fake", "task"])

    assert rc == 0
    captured = capsys.readouterr()
    assert "immediate answer" in captured.out
    assert len(scripted.create_calls) == 1
    rows = [
        json.loads(line)
        for line in (tmp_path / "history.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert len(rows) == 1
    assert rows[0]["mcp_decision"] == "final-text"
    assert rows[0]["turn_index"] == 0


def test_mcp_agent_one_error_then_success_continues(tmp_path, monkeypatch, capsys):
    """Single tool error doesn't trip the consecutive-error abort. Counter resets on success."""
    server_tools = [types.SimpleNamespace(name="echo", description="", inputSchema={})]

    async def _fake_list(server_argv):
        return server_tools

    AnthropicCls, scripted = _make_scripted_anthropic(
        [
            _agent_tool_use_response("echo", {"x": 1}, tu_id="t1"),
            _agent_tool_use_response("echo", {"x": 2}, tu_id="t2"),
            _agent_text_response("done"),
        ]
    )
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr(cli_mod, "_async_list_tools", _fake_list)
    monkeypatch.setattr(cli_mod, "Anthropic", AnthropicCls)
    monkeypatch.setattr(
        cli_mod,
        "_async_call_tool",
        _make_async_call_tool_scripted([("err1", True), ("ok2", False)]),
    )
    monkeypatch.setattr("builtins.input", lambda *a, **k: "y")

    rc = main(["--mcp-agent", "--mcp-server", "fake", "task"])

    assert rc == 0
    assert len(scripted.create_calls) == 3
    rows = [
        json.loads(line)
        for line in (tmp_path / "history.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert len(rows) == 3
    assert rows[0]["mcp_is_error"] is True
    assert rows[1]["mcp_is_error"] is False
    assert rows[2]["mcp_decision"] == "final-text"


def test_mcp_agent_two_consecutive_errors_aborts(tmp_path, monkeypatch, capsys):
    server_tools = [types.SimpleNamespace(name="echo", description="", inputSchema={})]

    async def _fake_list(server_argv):
        return server_tools

    AnthropicCls, scripted = _make_scripted_anthropic(
        [
            _agent_tool_use_response("echo", {"x": 1}, tu_id="t1"),
            _agent_tool_use_response("echo", {"x": 2}, tu_id="t2"),
            _agent_text_response("never reached"),
        ]
    )
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr(cli_mod, "_async_list_tools", _fake_list)
    monkeypatch.setattr(cli_mod, "Anthropic", AnthropicCls)
    monkeypatch.setattr(
        cli_mod,
        "_async_call_tool",
        _make_async_call_tool_scripted([("err1", True), ("err2", True)]),
    )
    monkeypatch.setattr("builtins.input", lambda *a, **k: "y")

    rc = main(["--mcp-agent", "--mcp-server", "fake", "task"])

    assert rc == 8
    captured = capsys.readouterr()
    assert "2 consecutive tool errors" in captured.err
    # The third Anthropic response should NEVER be requested
    assert len(scripted.create_calls) == 2
    rows = [
        json.loads(line)
        for line in (tmp_path / "history.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert len(rows) == 3
    assert rows[0]["mcp_decision"] == "run"
    assert rows[0]["mcp_is_error"] is True
    assert rows[1]["mcp_decision"] == "run"
    assert rows[1]["mcp_is_error"] is True
    assert rows[2]["mcp_decision"] == "consecutive-error-abort"
    assert rows[2]["consecutive_errors"] == 2


def test_mcp_agent_error_then_success_then_error_continues(tmp_path, monkeypatch, capsys):
    """Non-consecutive errors don't trip the abort (counter resets on success)."""
    server_tools = [types.SimpleNamespace(name="echo", description="", inputSchema={})]

    async def _fake_list(server_argv):
        return server_tools

    AnthropicCls, scripted = _make_scripted_anthropic(
        [
            _agent_tool_use_response("echo", {"x": 1}, tu_id="t1"),
            _agent_tool_use_response("echo", {"x": 2}, tu_id="t2"),
            _agent_tool_use_response("echo", {"x": 3}, tu_id="t3"),
        ]
    )
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr(cli_mod, "_async_list_tools", _fake_list)
    monkeypatch.setattr(cli_mod, "Anthropic", AnthropicCls)
    monkeypatch.setattr(
        cli_mod,
        "_async_call_tool",
        _make_async_call_tool_scripted([("err1", True), ("ok", False), ("err3", True)]),
    )
    monkeypatch.setattr("builtins.input", lambda *a, **k: "y")

    rc = main(
        ["--mcp-agent", "--mcp-agent-max-turns", "3", "--mcp-server", "fake", "task"]
    )

    # Three tool_use responses + max_turns=3 means after turn 3 we hit max-turns
    assert rc == 7
    rows = [
        json.loads(line)
        for line in (tmp_path / "history.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert len(rows) == 4
    assert rows[0]["mcp_is_error"] is True
    assert rows[1]["mcp_is_error"] is False
    assert rows[2]["mcp_is_error"] is True
    assert rows[3]["mcp_decision"] == "max-turns-reached"


def _setup_agent_dry_run_test(monkeypatch, server_tools_names, anthropic_responses):
    server_tools = [
        types.SimpleNamespace(name=n, description="", inputSchema={})
        for n in server_tools_names
    ]

    async def _fake_list(server_argv):
        return server_tools

    AnthropicCls, scripted = _make_scripted_anthropic(anthropic_responses)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr(cli_mod, "_async_list_tools", _fake_list)
    monkeypatch.setattr(cli_mod, "Anthropic", AnthropicCls)
    monkeypatch.setattr(cli_mod, "_async_call_tool", _async_call_tool_must_not_be_called)
    monkeypatch.setattr("builtins.input", _input_must_not_be_called)
    return scripted


def test_mcp_agent_dry_run_skips_execution(tmp_path, monkeypatch, capsys):
    scripted = _setup_agent_dry_run_test(
        monkeypatch,
        ["echo"],
        [
            _agent_tool_use_response("echo", {"x": 1}, tu_id="t1"),
            _agent_text_response("done"),
        ],
    )

    rc = main(
        ["--mcp-agent", "--mcp-agent-dry-run", "--mcp-server", "fake", "task"]
    )

    assert rc == 0
    captured = capsys.readouterr()
    assert "DRY RUN: would call tool echo" in captured.out
    assert "done" in captured.out
    rows = [
        json.loads(line)
        for line in (tmp_path / "history.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert len(rows) == 2
    assert rows[0]["mcp_decision"] == "dry-run-skipped"
    assert rows[0]["mcp_dry_run"] is True
    assert rows[1]["mcp_decision"] == "final-text"
    assert len(scripted.create_calls) == 2


def test_mcp_agent_dry_run_synthetic_result_passed_to_next_turn(tmp_path, monkeypatch):
    scripted = _setup_agent_dry_run_test(
        monkeypatch,
        ["echo"],
        [
            _agent_tool_use_response("echo", {"x": 1}, tu_id="t1"),
            _agent_tool_use_response("echo", {"x": 2}, tu_id="t2"),
            _agent_text_response("complete"),
        ],
    )

    rc = main(
        ["--mcp-agent", "--mcp-agent-dry-run", "--mcp-server", "fake", "task"]
    )

    assert rc == 0
    assert len(scripted.create_calls) == 3
    turn2_messages = scripted.create_calls[1]["messages"]
    assert len(turn2_messages) == 3
    user_tool_result = turn2_messages[2]
    assert user_tool_result["role"] == "user"
    tool_result_block = user_tool_result["content"][0]
    assert tool_result_block["type"] == "tool_result"
    assert "(dry-run:" in tool_result_block["content"]


def test_mcp_agent_dry_run_no_y_n_prompt_appears(tmp_path, monkeypatch, capsys):
    _setup_agent_dry_run_test(
        monkeypatch,
        ["echo"],
        [
            _agent_tool_use_response("echo", {"x": 1}, tu_id="t1"),
            _agent_text_response("done"),
        ],
    )

    rc = main(
        ["--mcp-agent", "--mcp-agent-dry-run", "--mcp-server", "fake", "task"]
    )

    assert rc == 0
    captured = capsys.readouterr()
    assert "Run this tool? [y/N]:" not in captured.err


def test_mcp_agent_dry_run_still_cold_rejects_hallucination(tmp_path, monkeypatch, capsys):
    scripted = _setup_agent_dry_run_test(
        monkeypatch,
        ["echo"],
        [_agent_tool_use_response("rm", {"path": "/"})],
    )

    rc = main(
        ["--mcp-agent", "--mcp-agent-dry-run", "--mcp-server", "fake", "task"]
    )

    assert rc == 5
    captured = capsys.readouterr()
    assert "hallucination" in captured.err
    assert "DRY RUN: would call" not in captured.out
    rows = [
        json.loads(line)
        for line in (tmp_path / "history.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert rows[0]["mcp_rejection_reason"] == "hallucinated-tool"


def test_mcp_agent_dry_run_still_cold_rejects_multi_tool(tmp_path, monkeypatch, capsys):
    multi = types.SimpleNamespace(
        content=[
            types.SimpleNamespace(type="tool_use", name="echo", input={"x": 1}, id="t1"),
            types.SimpleNamespace(type="tool_use", name="echo", input={"x": 2}, id="t2"),
        ]
    )
    scripted = _setup_agent_dry_run_test(monkeypatch, ["echo"], [multi])

    rc = main(
        ["--mcp-agent", "--mcp-agent-dry-run", "--mcp-server", "fake", "task"]
    )

    assert rc == 5
    captured = capsys.readouterr()
    assert "DRY RUN: would call" not in captured.out
    rows = [
        json.loads(line)
        for line in (tmp_path / "history.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert rows[0]["mcp_rejection_reason"] == "multi-tool-per-turn"


def test_mcp_agent_dry_run_alone_rejected(monkeypatch, capsys):
    rc = main(["--mcp-agent-dry-run", "task"])
    assert rc == 5
    captured = capsys.readouterr()
    assert "only meaningful with --mcp-agent" in captured.err


def test_mcp_agent_dry_run_max_turns_reached(tmp_path, monkeypatch, capsys):
    scripted = _setup_agent_dry_run_test(
        monkeypatch,
        ["echo"],
        [
            _agent_tool_use_response("echo", {"x": 1}, tu_id="t1"),
            _agent_tool_use_response("echo", {"x": 2}, tu_id="t2"),
        ],
    )

    rc = main(
        [
            "--mcp-agent",
            "--mcp-agent-dry-run",
            "--mcp-agent-max-turns",
            "2",
            "--mcp-server",
            "fake",
            "task",
        ]
    )

    assert rc == 7
    rows = [
        json.loads(line)
        for line in (tmp_path / "history.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert len(rows) == 3
    assert rows[0]["mcp_decision"] == "dry-run-skipped"
    assert rows[1]["mcp_decision"] == "dry-run-skipped"
    assert rows[2]["mcp_decision"] == "max-turns-reached"


def _setup_reflect_test(monkeypatch, server_tools_names, anthropic_responses):
    server_tools = [
        types.SimpleNamespace(name=n, description="", inputSchema={})
        for n in server_tools_names
    ]

    async def _fake_list(server_argv):
        return server_tools

    AnthropicCls, scripted = _make_scripted_anthropic(anthropic_responses)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr(cli_mod, "_async_list_tools", _fake_list)
    monkeypatch.setattr(cli_mod, "Anthropic", AnthropicCls)
    return scripted


def test_reflect_after_final_text_run(tmp_path, monkeypatch, capsys):
    scripted = _setup_reflect_test(
        monkeypatch,
        ["echo"],
        [
            _agent_tool_use_response("echo", {"x": 1}, tu_id="t1"),
            _agent_text_response("done"),
            _agent_text_response("yes, the task is complete"),
        ],
    )
    monkeypatch.setattr(
        cli_mod,
        "_async_call_tool",
        _make_async_call_tool_scripted([("ok", False)]),
    )
    monkeypatch.setattr("builtins.input", lambda *a, **k: "y")

    rc = main(["--mcp-agent", "--reflect", "--mcp-server", "fake", "task"])

    assert rc == 0
    captured = capsys.readouterr()
    assert "done" in captured.out
    assert "Reflection: yes, the task is complete" in captured.out
    assert len(scripted.create_calls) == 3
    final_call_messages = scripted.create_calls[2]["messages"]
    assert any(
        msg.get("role") == "user"
        and msg.get("content") == cli_mod.REFLECTION_PROMPT
        for msg in final_call_messages
    )
    rows = [
        json.loads(line)
        for line in (tmp_path / "history.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert any(row.get("mcp_decision") == "reflection" for row in rows)


def test_reflect_after_max_turns(tmp_path, monkeypatch, capsys):
    scripted = _setup_reflect_test(
        monkeypatch,
        ["echo"],
        [
            _agent_tool_use_response("echo", {"x": 1}, tu_id="t1"),
            _agent_tool_use_response("echo", {"x": 2}, tu_id="t2"),
            _agent_text_response("partial — needed more turns"),
        ],
    )
    monkeypatch.setattr(
        cli_mod,
        "_async_call_tool",
        _make_async_call_tool_scripted([("ok1", False), ("ok2", False)]),
    )
    monkeypatch.setattr("builtins.input", lambda *a, **k: "y")

    rc = main(
        [
            "--mcp-agent",
            "--mcp-agent-max-turns",
            "2",
            "--reflect",
            "--mcp-server",
            "fake",
            "task",
        ]
    )

    assert rc == 7  # max-turns-reached unchanged
    captured = capsys.readouterr()
    assert "Reflection: partial — needed more turns" in captured.out
    assert len(scripted.create_calls) == 3
    rows = [
        json.loads(line)
        for line in (tmp_path / "history.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    decisions = [row.get("mcp_decision") for row in rows]
    assert "max-turns-reached" in decisions
    assert "reflection" in decisions


def test_reflect_after_consecutive_errors(tmp_path, monkeypatch, capsys):
    scripted = _setup_reflect_test(
        monkeypatch,
        ["echo"],
        [
            _agent_tool_use_response("echo", {"x": 1}, tu_id="t1"),
            _agent_tool_use_response("echo", {"x": 2}, tu_id="t2"),
            _agent_text_response("no, errors blocked progress"),
        ],
    )
    monkeypatch.setattr(
        cli_mod,
        "_async_call_tool",
        _make_async_call_tool_scripted([("err1", True), ("err2", True)]),
    )
    monkeypatch.setattr("builtins.input", lambda *a, **k: "y")

    rc = main(["--mcp-agent", "--reflect", "--mcp-server", "fake", "task"])

    assert rc == 8
    captured = capsys.readouterr()
    assert "Reflection: no, errors blocked progress" in captured.out
    rows = [
        json.loads(line)
        for line in (tmp_path / "history.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    decisions = [row.get("mcp_decision") for row in rows]
    assert "consecutive-error-abort" in decisions
    assert "reflection" in decisions


def test_reflect_after_user_abort(tmp_path, monkeypatch, capsys):
    scripted = _setup_reflect_test(
        monkeypatch,
        ["echo"],
        [
            _agent_tool_use_response("echo", {"x": 1}, tu_id="t1"),
            _agent_text_response("user stopped me before I could try"),
        ],
    )
    monkeypatch.setattr(cli_mod, "_async_call_tool", _async_call_tool_must_not_be_called)
    monkeypatch.setattr("builtins.input", lambda *a, **k: "n")

    rc = main(["--mcp-agent", "--reflect", "--mcp-server", "fake", "task"])

    assert rc == 0
    captured = capsys.readouterr()
    assert "aborted at turn 1" in captured.err
    assert "Reflection: user stopped me before I could try" in captured.out


def test_reflect_skipped_in_dry_run(tmp_path, monkeypatch, capsys):
    scripted = _setup_reflect_test(
        monkeypatch,
        ["echo"],
        [
            _agent_tool_use_response("echo", {"x": 1}, tu_id="t1"),
            _agent_text_response("done"),
        ],
    )
    monkeypatch.setattr(cli_mod, "_async_call_tool", _async_call_tool_must_not_be_called)
    monkeypatch.setattr("builtins.input", _input_must_not_be_called)

    rc = main(
        [
            "--mcp-agent",
            "--mcp-agent-dry-run",
            "--reflect",
            "--mcp-server",
            "fake",
            "task",
        ]
    )

    assert rc == 0
    captured = capsys.readouterr()
    assert "--reflect skipped in dry-run mode" in captured.err
    assert "Reflection:" not in captured.out
    # The dry-run consumed 2 scripted responses; reflection would be the 3rd, must NOT be called
    assert len(scripted.create_calls) == 2


def test_reflect_alone_rejected(monkeypatch, capsys):
    rc = main(["--reflect", "task"])
    assert rc == 5
    captured = capsys.readouterr()
    assert "only meaningful with --mcp-agent" in captured.err


def test_reflect_skipped_after_hallucination(tmp_path, monkeypatch, capsys):
    scripted = _setup_reflect_test(
        monkeypatch, ["echo"], [_agent_tool_use_response("rm", {"path": "/"})]
    )
    monkeypatch.setattr(cli_mod, "_async_call_tool", _async_call_tool_must_not_be_called)
    monkeypatch.setattr("builtins.input", _input_must_not_be_called)

    rc = main(["--mcp-agent", "--reflect", "--mcp-server", "fake", "task"])

    assert rc == 5
    captured = capsys.readouterr()
    assert "Reflection:" not in captured.out
    assert len(scripted.create_calls) == 1


def test_reflect_api_error_does_not_change_exit_code(tmp_path, monkeypatch, capsys):
    scripted = _setup_reflect_test(
        monkeypatch,
        ["echo"],
        [
            _agent_tool_use_response("echo", {"x": 1}, tu_id="t1"),
            _agent_tool_use_response("echo", {"x": 2}, tu_id="t2"),
            _FakeAPIError("reflection-api-down"),
        ],
    )
    monkeypatch.setattr(
        cli_mod,
        "_async_call_tool",
        _make_async_call_tool_scripted([("ok1", False), ("ok2", False)]),
    )
    monkeypatch.setattr("builtins.input", lambda *a, **k: "y")

    rc = main(
        [
            "--mcp-agent",
            "--mcp-agent-max-turns",
            "2",
            "--reflect",
            "--mcp-server",
            "fake",
            "task",
        ]
    )

    assert rc == 7  # max-turns exit unchanged despite reflection failure
    captured = capsys.readouterr()
    assert "warning: --reflect API call failed" in captured.err


def test_reflect_handles_tool_use_in_response_gracefully(tmp_path, monkeypatch, capsys):
    reflection_with_tool_use = types.SimpleNamespace(
        content=[
            types.SimpleNamespace(type="text", text="reasoning text"),
            types.SimpleNamespace(type="tool_use", name="echo", input={}, id="bogus"),
        ]
    )
    scripted = _setup_reflect_test(
        monkeypatch,
        ["echo"],
        [
            _agent_tool_use_response("echo", {"x": 1}, tu_id="t1"),
            _agent_text_response("done"),
            reflection_with_tool_use,
        ],
    )
    monkeypatch.setattr(
        cli_mod,
        "_async_call_tool",
        _make_async_call_tool_scripted([("ok", False)]),
    )
    monkeypatch.setattr("builtins.input", lambda *a, **k: "y")

    rc = main(["--mcp-agent", "--reflect", "--mcp-server", "fake", "task"])

    assert rc == 0
    captured = capsys.readouterr()
    assert "Reflection: reasoning text" in captured.out
    assert "model proposed a tool call" in captured.err


def test_version_prints_version_and_exits_zero(capsys):
    with pytest.raises(SystemExit) as ei:
        main(["--version"])
    assert ei.value.code == 0
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert "workbuddy " in combined
    assert cli_mod.VERSION in combined


def test_version_does_not_require_task_arg(capsys):
    """--version must short-circuit BEFORE the positional 'task' arg is validated."""
    with pytest.raises(SystemExit) as ei:
        main(["--version"])
    assert ei.value.code == 0
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert "the following arguments are required" not in combined


def test_version_does_not_require_api_key(monkeypatch, capsys):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(SystemExit) as ei:
        main(["--version"])
    assert ei.value.code == 0


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
