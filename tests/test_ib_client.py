import pytest

from autostock.ib_client import choose_account


def test_choose_account_uses_first_when_preferred_empty() -> None:
    assert choose_account("", ["DU111", "DU222"]) == "DU111"


def test_choose_account_uses_preferred_when_present() -> None:
    assert choose_account("DU222", ["DU111", "DU222"]) == "DU222"


def test_choose_account_raises_when_preferred_not_available() -> None:
    with pytest.raises(RuntimeError):
        choose_account("DU999", ["DU111", "DU222"])
