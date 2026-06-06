import uvicorn
from dotenv import load_dotenv

load_dotenv()  # loads backend/.env when present; no-op if missing

from banyan_platform.app import create_app

app = create_app()

if __name__ == "__main__":
    uvicorn.run("banyan_platform.main:app", host="0.0.0.0", port=8000, reload=False)
