## LINE Bot (Flask) with Redis-backed sessions

This project implements a LINE Messaging API bot using Flask. Per-user conversation state is stored in Redis via `session.RedisSession`. The main entrypoint is `script.py`, which exposes a Flask app as `app`.

You can run locally or via Docker. The Docker setup uses Gunicorn to serve `script:app` and a Redis service.

### Prerequisites
- LINE channel secret and access token
- Docker Desktop (recommended) or Python 3.11

### Environment variables
Create a `.env` file based on `.env.example`:

- `LINE_CHANNEL_SECRET` — LINE channel secret
- `LINE_CHANNEL_ACCESS_TOKEN` — LINE channel access token
- `REDIS_URL` — e.g. `redis://localhost:6379/0` for local, or `redis://redis:6379/0` in Docker Compose

### Run with Docker
1. Copy `.env.example` to `.env` and fill in your credentials
2. Start services:
	- `docker compose up --build -d`
3. The Flask app will be served at `http://localhost:8000`

Expose `/callback` as your LINE webhook URL. For local development, use a tunnel (e.g. ngrok) and point to `http://localhost:8000/callback`.

### Run without Docker (optional)
1. Create a virtual environment and install from `requirements.txt`
2. Set environment variables (or `.env`)
3. Run `gunicorn -w 2 -k gthread -b 0.0.0.0:8000 script:app`

### Notes
- Images uploaded by users are stored under `tmp_uploads/`. In Docker, this folder is mounted as a volume for persistence.
- Redis connection is configured via `REDIS_URL`. In Docker Compose, the default is `redis://redis:6379/0`.
- The bot replies only when all required parts are present (details, EDC status, and image), then sends a summary.