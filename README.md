# Palora

Palora desktop MVP built from `project_spec.md` and `prototypes/palora_chat_first_preview.html`.

## What is here

- `backend/`: FastAPI local backend with SQLite store, seeded memory graph, chat turn pipeline, actions, ingest, graph endpoints
- `desktop/`: Electron shell and renderer UI using preview visual language
- live context-build stream: chat requests animate graph node + edge creation in UI while retrieval runs

## Run

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e 'backend[dev]'
npm install
npm start
```

## Backend tests

```bash
. .venv/bin/activate
pytest backend/tests/test_app.py
```

## Notes

- Electron launcher prefers repo-local `.venv/bin/python` automatically.
- Data lives in `.palora-data/`.
- Seeded demo content includes actual repo spec + preview files, plus recruiter/build demo memories so flows are visible immediately.
