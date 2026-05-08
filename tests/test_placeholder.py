import workbuddy
from workbuddy.cli import main


def test_workbuddy_importable():
    assert workbuddy is not None


def test_main_returns_zero():
    assert main() == 0
