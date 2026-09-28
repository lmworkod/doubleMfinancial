from fastapi import FastAPI

from app import db

app = FastAPI(title="DoubleM Financial", docs_url=None, redoc_url=None)


@app.get("/health")
def health() -> dict[str, str]:
    try:
        with db.engine.connect() as connection:
            connection.exec_driver_sql("SELECT 1")
        return {"status": "ok"}
    except Exception:
        return {"status": "degraded"}
