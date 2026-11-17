# Prompt Testing & Versioning Playground

A lightweight full-stack playground to version prompts (`v1`, `v2`, `v3`), run side-by-side A/B output comparisons, and track quality score improvements over time.

## Quickstart

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

Open `http://127.0.0.1:8000` in your browser.

*(Optional)* Set `OPENAI_API_KEY` in your environment to evaluate against live OpenAI models; otherwise, the app runs in deterministic offline simulation mode out of the box.

## Run Automated Tests

```bash
pytest -v
```
