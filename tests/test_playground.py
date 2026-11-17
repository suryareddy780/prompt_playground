import os
import sys
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))
import main  # noqa: E402

client = TestClient(main.app)


def test_versioning_and_comparison_flow():
    # 1. Create v1
    r1 = client.post("/api/versions", json={
        "project_name": "Test Suite",
        "system_prompt": "You are an assistant.",
        "user_template": "Summarize this: {{input}}",
        "notes": "Initial baseline prompt"
    })
    assert r1.status_code == 200
    v1_id = r1.json()["id"]
    assert r1.json()["version_tag"] == "v1"

    # 2. Create v2 with structured constraints
    r2 = client.post("/api/versions", json={
        "project_name": "Test Suite",
        "system_prompt": "You are a concise analyst.",
        "user_template": "Provide a bullet summary in JSON format: {{input}}",
        "notes": "Added JSON and bullet guardrails"
    })
    assert r2.status_code == 200
    v2_id = r2.json()["id"]
    assert r2.json()["version_tag"] == "v2"

    # 3. Score v1 and v2 and verify delta tracking
    client.patch(f"/api/versions/{v1_id}/score", json={"quality_score": 6.5})
    client.patch(f"/api/versions/{v2_id}/score", json={"quality_score": 9.0})

    versions = client.get("/api/versions").json()
    v2_record = [v for v in versions if v["id"] == v2_id][0]
    assert v2_record["delta_vs_v1"] == 2.5

    # 4. Run side-by-side comparison
    comp = client.post("/api/compare", json={
        "version_a_id": v1_id,
        "version_b_id": v2_id,
        "test_input": "Quarterly revenue grew 18% YoY."
    })
    assert comp.status_code == 200
    data = comp.json()
    assert "Unconstrained" in data["version_a"]["output"]
    assert "Structured" in data["version_b"]["output"]
