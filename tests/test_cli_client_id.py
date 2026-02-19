from autostock.cli import flatten_uses_sidecar, select_client_id


def test_select_client_id_for_run() -> None:
    assert select_client_id(101, sidecar=False) == 101


def test_select_client_id_for_sidecar_commands() -> None:
    assert select_client_id(101, sidecar=True) == 102


def test_flatten_default_does_not_use_sidecar() -> None:
    assert flatten_uses_sidecar(False) is False


def test_flatten_force_uses_sidecar() -> None:
    assert flatten_uses_sidecar(True) is True
