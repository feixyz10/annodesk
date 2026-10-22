import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from annodesk.app import create_app
from annodesk.lease import ProjectLease


def test_writer_lease_is_cross_process_and_released(tmp_path):
    code = "from pathlib import Path; from annodesk.lease import ProjectLease; import sys; ProjectLease(Path(sys.argv[1]))"
    with ProjectLease(tmp_path):
        result = subprocess.run(
            [sys.executable, "-c", code, str(tmp_path)], capture_output=True, text=True
        )
        assert result.returncode != 0 and "in use" in result.stderr
    assert subprocess.run([sys.executable, "-c", code, str(tmp_path)]).returncode == 0


def test_http_lifetime_holds_lease(tmp_path):
    with TestClient(create_app(project=tmp_path)):
        with pytest.raises(ValueError, match="in use"):
            ProjectLease(tmp_path)
    with ProjectLease(tmp_path):
        pass


@pytest.mark.parametrize("config_state", ["missing", "broken"])
def test_failed_model_configuration_releases_startup_lease(tmp_path, config_state):
    # Keep the traceback alive: lease release must not depend on garbage collection.
    config = tmp_path / "models.json"
    if config_state == "broken":
        config.write_text("broken json")
    with pytest.raises(ValueError) as error:
        create_app(project=tmp_path, models_config=config)
    with ProjectLease(tmp_path):
        assert error.value
