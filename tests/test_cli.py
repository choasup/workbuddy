import subprocess
import sys

import pytest

from workbuddy.cli import main


def test_main_echoes_task(capsys):
    rc = main(["do something"])
    assert rc == 0
    captured = capsys.readouterr()
    assert "do something" in captured.out


def test_main_missing_argument_exits_nonzero(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main([])
    assert excinfo.value.code != 0
    captured = capsys.readouterr()
    assert captured.err  # argparse writes usage to stderr


def test_module_invocation_echoes_task():
    result = subprocess.run(
        [sys.executable, "-m", "workbuddy", "hello world"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "hello world" in result.stdout
