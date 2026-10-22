import pytest

from annodesk.devices import ExecutionOptions, resolve_plan


@pytest.mark.parametrize(
    "workers,expected",
    [
        ("auto", ["cuda:0", "cuda:2"]),
        ("5", ["cuda:0", "cuda:2", "cuda:0", "cuda:2", "cuda:0"]),
        ("1", ["cuda:0"]),
    ],
)
def test_round_robin_logical_devices(workers, expected):
    plan = resolve_plan(ExecutionOptions("cuda", "0,2", workers), {"cuda": 3, "mps": True})
    assert plan.workers == expected


@pytest.mark.parametrize("devices", ["", "0,", "-1", "0,0", "3", "a"])
def test_invalid_devices(devices):
    with pytest.raises(ValueError):
        resolve_plan(ExecutionOptions("cuda", devices), {"cuda": 3, "mps": False})


def test_auto_selection_and_unavailable_explicit_devices():
    assert resolve_plan(ExecutionOptions(), {"cuda": 0, "mps": True}).workers == ["mps"]
    assert resolve_plan(ExecutionOptions(), {"cuda": 0, "mps": False}).workers == ["cpu"]
    for options in [
        ExecutionOptions("cpu", "0"),
        ExecutionOptions("auto", "0"),
        ExecutionOptions("cuda"),
        ExecutionOptions("mps"),
        ExecutionOptions(num_workers="0"),
    ]:
        with pytest.raises(ValueError):
            resolve_plan(options, {"cuda": 0, "mps": False})
