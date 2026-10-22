"""Block Python network calls and auto-install subprocesses in the inference worker."""

import os
import re
import sys
import threading
from contextlib import contextmanager

_state = threading.local()


def _guard(event, args):
    if not getattr(_state, "active", False):
        return
    blocked = event in {"socket.connect", "socket.getaddrinfo"}
    if event in {"subprocess.Popen", "os.system", "os.posix_spawn"}:
        command = str(args[:2])
        blocked = bool(
            re.search(r"\b(pip3?|uv|curl|wget)\b|git.{0,30}\b(clone|fetch|pull)\b", command)
        )
    if blocked:
        raise RuntimeError(
            "Network access and automatic installation are disabled during inference. "
            "Prepare model files and dependencies locally."
        )


sys.addaudithook(_guard)


@contextmanager
def offline_inference():
    # Set before importing optional libraries; do not let user env re-enable downloads.
    os.environ.update(
        HF_HUB_OFFLINE="1",
        TRANSFORMERS_OFFLINE="1",
        YOLO_OFFLINE="true",
        YOLO_AUTOINSTALL="false",
        YOLO_VERBOSE="false",
    )
    previous = getattr(_state, "active", False)
    _state.active = True
    try:
        yield
    finally:
        _state.active = previous
