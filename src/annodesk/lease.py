"""One writer runtime per project, shared by the CLI and HTTP server."""

from pathlib import Path

from filelock import FileLock, Timeout


class ProjectLease:
    def __init__(self, root: Path):
        root = root.expanduser().resolve()
        if not root.is_dir():
            raise ValueError("Project directory does not exist")
        private = root / ".annodesk"
        private.mkdir(exist_ok=True)
        self.lock = FileLock(private / "writer.lock", thread_local=False)
        try:
            self.lock.acquire(timeout=0)
        except Timeout as error:
            raise ValueError(
                "Project is in use by another AnnoDesk runtime; close it before writing"
            ) from error

    def close(self):
        self.lock.release()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
