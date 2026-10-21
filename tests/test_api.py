from fastapi.testclient import TestClient
from PIL import Image

from annodesk.app import create_app


def test_project_annotation_http_roundtrip(tmp_path):
    (tmp_path / "images/nested").mkdir(parents=True)
    Image.new("RGB", (120, 80)).save(tmp_path / "images/nested/a.png")
    client = TestClient(create_app())
    response = client.post("/api/v1/project/open", json={"path": str(tmp_path)})
    assert response.status_code == 200
    category = client.post("/api/v1/classes", json={"name": "Car"}).json()
    images = client.get("/api/v1/images").json()["items"]
    image_id = images[0]["id"]
    ann = client.get(f"/api/v1/images/{image_id}/annotation").json()
    ann["instances"] = [{"class_id": category["id"], "box": [10, 10, 90, 60]}]
    response = client.put(f"/api/v1/images/{image_id}/annotation", json=ann)
    assert response.status_code == 200, response.text
    assert response.json()["revision"] == 1
    assert client.put(f"/api/v1/images/{image_id}/annotation", json=ann).status_code == 409
    assert (
        client.get(f"/api/v1/images/{image_id}/thumbnail").headers["content-type"] == "image/jpeg"
    )
    assert client.get(f"/api/v1/images/{image_id}/file").status_code == 200
    assert client.get("/api/v1/images/missing/file").status_code == 404
