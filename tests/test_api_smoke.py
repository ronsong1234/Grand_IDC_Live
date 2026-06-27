from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from web.backend import main, qc_runner


def test_summary_endpoint_returns_monkeypatched_result(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "result_for_slide_id", lambda slide_id: {"slide_id": slide_id, "usable": True})
    client = TestClient(main.app)

    response = client.get("/api/results/TCGA-XX-0000-01Z-00-DX1/summary")

    assert response.status_code == 200
    payload = response.json()
    assert payload["slide_id"] == "TCGA-XX-0000-01Z-00-DX1"
    assert payload["summary"]["usable"] is True


def test_summary_endpoint_maps_ambiguous_results_to_409(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_ambiguous(slide_id: str):
        raise qc_runner.AmbiguousResultError(f"ambiguous {slide_id}")

    monkeypatch.setattr(main, "result_for_slide_id", raise_ambiguous)
    client = TestClient(main.app)

    response = client.get("/api/results/TCGA-XX-0000-01Z-00-DX1/summary")

    assert response.status_code == 409
    assert "ambiguous" in response.json()["detail"]


def test_artifact_endpoint_serves_monkeypatched_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    artifact = tmp_path / "mask.png"
    artifact.write_bytes(b"not-a-real-png-but-file-response-is-enough")
    monkeypatch.setattr(main, "artifact_path", lambda slide_id, artifact_name: artifact)
    client = TestClient(main.app)

    response = client.get("/api/results/TCGA-XX-0000-01Z-00-DX1/mask")

    assert response.status_code == 200
    assert response.content == artifact.read_bytes()


def test_result_lookup_rejects_duplicate_slide_ids(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    slide_id = "TCGA-XX-0000-01Z-00-DX1"
    for collection in ["tcga_one", "tcga_two"]:
        slide_dir = tmp_path / collection / slide_id
        slide_dir.mkdir(parents=True)
        (slide_dir / "summary.json").write_text('{"slide_id":"' + slide_id + '"}', encoding="utf-8")

    monkeypatch.setattr(qc_runner, "OUTPUT_DIR", tmp_path)

    with pytest.raises(qc_runner.AmbiguousResultError):
        qc_runner.result_for_slide_id(slide_id)
