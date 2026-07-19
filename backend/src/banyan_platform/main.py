import pathlib
import uvicorn
from dotenv import load_dotenv

# Anchor .env resolution to the backend/ directory (two levels up from this file:
# src/banyan_platform/main.py → src/banyan_platform → src → backend)
_BACKEND_DIR = pathlib.Path(__file__).parent.parent.parent
load_dotenv(_BACKEND_DIR / ".env")  # no-op if .env is absent

from banyan_platform.app import create_app

app = create_app()

if __name__ == "__main__":
    uvicorn.run("banyan_platform.main:app", host="0.0.0.0", port=8000, reload=False)
