import sys
import os
import traceback

# Add backend directory and app directory to sys.path
base_dir = os.path.dirname(__file__)
backend_dir = os.path.abspath(os.path.join(base_dir, "..", "backend"))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

try:
    from app.main import app
except Exception as e:
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse
    app = FastAPI()
    error_msg = f"{type(e).__name__}: {str(e)}\n\n{traceback.format_exc()}"
    
    @app.api_route("/{path_name:path}", methods=["GET", "POST", "PUT", "DELETE"])
    async def catch_all(path_name: str):
        return JSONResponse(
            status_code=500,
            content={"error": "Backend initialization failed", "details": error_msg}
        )

