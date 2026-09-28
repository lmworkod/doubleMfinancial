import threading

import uvicorn

from app.health import app


def start_health_thread() -> threading.Thread:
    thread = threading.Thread(
        target=lambda: uvicorn.run(app, host="127.0.0.1", port=8081, log_level="warning"),
        name="health-server", daemon=True)
    thread.start()
    return thread
