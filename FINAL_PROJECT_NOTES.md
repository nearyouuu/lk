`final_project` is based on `back2`.

Merged from `back1`:
- `assets/`
- `index.html`
- `vite.svg`
- `.env.docker`
- `Image.png`
- unique files from `media/`

Intentionally not merged from `back1`:
- Python source files
- Alembic migrations

Important:
- Backend code uses `app/media` by default via `app/core/config.py`.
- Some routers also write to root-level `media/`.
- Before production use, it is worth unifying media storage to one location.
