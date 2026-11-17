import os
import time
import sqlite3
from datetime import datetime
from typing import Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

app = FastAPI(title="Prompt Testing Playground")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_PATH = "prompts.db"


def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS prompt_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_name TEXT NOT NULL,
            version_tag TEXT NOT NULL,
            system_prompt TEXT,
            user_template TEXT NOT NULL,
            notes TEXT,
            quality_score REAL DEFAULT 0.0,
            created_at TEXT NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS test_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            version_id INTEGER,
            input_variables TEXT,
            output_text TEXT,
            latency_ms INTEGER,
            token_estimate INTEGER,
            rating INTEGER,
            created_at TEXT NOT NULL,
            FOREIGN KEY(version_id) REFERENCES prompt_versions(id)
        )
    """)
    conn.commit()
    conn.close()


init_db()


class VersionCreate(BaseModel):
    project_name: str = "Default Project"
    system_prompt: Optional[str] = "You are a helpful AI assistant."
    user_template: str
    notes: Optional[str] = ""


class RunCompareRequest(BaseModel):
    version_a_id: int
    version_b_id: int
    test_input: str


class ScoreUpdate(BaseModel):
    quality_score: float


def simulate_or_call_llm(system_prompt: str, user_prompt: str) -> tuple[str, int]:
    start = time.time()
    api_key = os.getenv("OPENAI_API_KEY")

    if api_key:
        import urllib.request
        import json

        req = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions",
            data=json.dumps({
                "model": "gpt-4o-mini",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.4,
            }).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            output = data["choices"][0]["message"]["content"]
    else:
        time.sleep(0.15)
        has_constraints = any(
            k in (system_prompt + user_prompt).lower()
            for k in ["json", "bullet", "step-by-step", "concise", "table"]
        )
        structure_note = (
            "Structured & Constraint-Aligned Output"
            if has_constraints
            else "Unconstrained General Output"
        )
        output = (
            f"[{structure_note}]\n"
            f"System Framing: {system_prompt[:60]}...\n"
            f"Processed Prompt: {user_prompt}\n\n"
            f"Response: Here is the synthesized result tailored to your prompt instructions. "
            f"{'Formatted with strict structural guardrails.' if has_constraints else 'Consider adding output format constraints in the next version.'}"
        )

    latency_ms = int((time.time() - start) * 1000)
    return output, latency_ms


@app.get("/")
def serve_ui():
    frontend_path = os.path.join(os.path.dirname(__file__), "..", "frontend", "index.html")
    return FileResponse(frontend_path)


@app.post("/api/versions")
def create_version(payload: VersionCreate):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT COUNT(*) FROM prompt_versions WHERE project_name = ?",
        (payload.project_name,),
    )
    count = cursor.fetchone()[0]
    version_tag = f"v{count + 1}"
    now = datetime.utcnow().isoformat()

    cursor.execute(
        """
        INSERT INTO prompt_versions (project_name, version_tag, system_prompt, user_template, notes, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            payload.project_name,
            version_tag,
            payload.system_prompt,
            payload.user_template,
            payload.notes,
            now,
        ),
    )
    version_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return {"id": version_id, "version_tag": version_tag, "created_at": now}


@app.get("/api/versions")
def list_versions():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM prompt_versions ORDER BY id ASC")
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()

    baseline = rows[0]["quality_score"] if rows else 0.0
    for r in rows:
        r["delta_vs_v1"] = round(r["quality_score"] - baseline, 2)
    return rows


@app.patch("/api/versions/{version_id}/score")
def update_score(version_id: int, payload: ScoreUpdate):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE prompt_versions SET quality_score = ? WHERE id = ?",
        (payload.quality_score, version_id),
    )
    if cursor.rowcount == 0:
        conn.close()
        raise HTTPException(status_code=404, detail="Version not found")
    conn.commit()
    conn.close()
    return {"status": "updated", "version_id": version_id, "quality_score": payload.quality_score}


@app.post("/api/compare")
def compare_versions(payload: RunCompareRequest):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM prompt_versions WHERE id = ?", (payload.version_a_id,))
    ver_a = cursor.fetchone()
    cursor.execute("SELECT * FROM prompt_versions WHERE id = ?", (payload.version_b_id,))
    ver_b = cursor.fetchone()

    if not ver_a or not ver_b:
        conn.close()
        raise HTTPException(status_code=404, detail="One or both prompt versions not found")

    prompt_a = ver_a["user_template"].replace("{{input}}", payload.test_input)
    prompt_b = ver_b["user_template"].replace("{{input}}", payload.test_input)

    out_a, lat_a = simulate_or_call_llm(ver_a["system_prompt"], prompt_a)
    out_b, lat_b = simulate_or_call_llm(ver_b["system_prompt"], prompt_b)

    now = datetime.utcnow().isoformat()
    cursor.execute(
        "INSERT INTO test_runs (version_id, input_variables, output_text, latency_ms, token_estimate, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (ver_a["id"], payload.test_input, out_a, lat_a, len(out_a.split()), now),
    )
    cursor.execute(
        "INSERT INTO test_runs (version_id, input_variables, output_text, latency_ms, token_estimate, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (ver_b["id"], payload.test_input, out_b, lat_b, len(out_b.split()), now),
    )
    conn.commit()
    conn.close()

    return {
        "version_a": {
            "tag": ver_a["version_tag"],
            "rendered_prompt": prompt_a,
            "output": out_a,
            "latency_ms": lat_a,
            "word_count": len(out_a.split()),
        },
        "version_b": {
            "tag": ver_b["version_tag"],
            "rendered_prompt": prompt_b,
            "output": out_b,
            "latency_ms": lat_b,
            "word_count": len(out_b.split()),
        },
    }
