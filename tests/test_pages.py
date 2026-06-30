from fastapi.testclient import TestClient

from app.main import app


def test_public_pages_show_icp_record() -> None:
    client = TestClient(app)

    for path in ["/", "/privacy", "/terms"]:
        response = client.get(path)

        assert response.status_code == 200
        assert "京ICP备2026033738号-1" in response.text
        assert "https://beian.miit.gov.cn/" in response.text
