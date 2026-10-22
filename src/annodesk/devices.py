"""Resolve logical devices in a short-lived spawned probe, before model workers exist."""

import multiprocessing as mp
import signal
from dataclasses import asdict, dataclass
from typing import Literal

DeviceType = Literal["auto", "cuda", "cpu", "mps"]


@dataclass(frozen=True)
class ExecutionOptions:
    device_type: DeviceType = "auto"
    devices: str = "auto"
    num_workers: str = "auto"


@dataclass(frozen=True)
class DevicePlan:
    device_type: str
    devices: list[str]
    workers: list[str]

    def to_dict(self):
        return asdict(self)


def _probe(connection):
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    try:
        import torch

        connection.send(
            {"cuda": torch.cuda.device_count(), "mps": bool(torch.backends.mps.is_available())}
        )
    except ImportError:
        connection.send({"cuda": 0, "mps": False})
    except Exception as error:
        connection.send({"error": str(error)})
    finally:
        connection.close()


def probe_devices() -> dict:
    context = mp.get_context("spawn")
    parent, child = context.Pipe(duplex=False)
    process = context.Process(target=_probe, args=(child,))
    process.start()
    child.close()
    try:
        if not parent.poll(60):
            raise ValueError("Device probe timed out")
        result = parent.recv()
        if "error" in result:
            raise ValueError(f"Device probe failed: {result['error']}")
        return result
    except EOFError as error:
        raise ValueError("Device probe exited without a result") from error
    finally:
        parent.close()
        process.join(timeout=1)
        if process.is_alive():
            process.terminate()
            process.join()


def resolve_plan(options: ExecutionOptions, available: dict | None = None) -> DevicePlan:
    if options.device_type not in {"auto", "cuda", "cpu", "mps"}:
        raise ValueError("device-type must be auto, cuda, cpu or mps")
    available = available if available is not None else probe_devices()
    kind = options.device_type
    if kind == "auto":
        kind = "cuda" if available["cuda"] else "mps" if available["mps"] else "cpu"
    if kind == "cuda":
        count = available["cuda"]
        if not count:
            raise ValueError("CUDA is unavailable (check CUDA_VISIBLE_DEVICES)")
        if options.devices == "auto":
            indices = list(range(count))
        else:
            try:
                pieces = options.devices.split(",")
                if any(not p.strip().isdigit() for p in pieces):
                    raise ValueError
                indices = [int(p) for p in pieces]
                if len(set(indices)) != len(indices) or any(i >= count for i in indices):
                    raise ValueError
            except ValueError as error:
                raise ValueError(
                    f"devices must contain distinct logical CUDA indices from 0 to {count - 1}"
                ) from error
        devices = [f"cuda:{i}" for i in indices]
    else:
        if options.devices != "auto":
            raise ValueError("Numeric devices require CUDA; CPU/MPS only accept devices=auto")
        if kind == "mps" and not available["mps"]:
            raise ValueError("MPS is unavailable")
        devices = [kind]
    try:
        workers = len(devices) if options.num_workers == "auto" else int(options.num_workers)
        if workers < 1:
            raise ValueError
    except (TypeError, ValueError) as error:
        raise ValueError("num-workers must be auto or a positive integer") from error
    return DevicePlan(kind, devices, [devices[i % len(devices)] for i in range(workers)])
