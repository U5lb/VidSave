from fastapi import WebSocket
from loguru import logger


class WSManager:
    def __init__(self):
        self.active_workers: dict = {}

    async def connect(self, worker_id: str, ws: WebSocket):
        await ws.accept()
        self.active_workers[worker_id] = ws

    def disconnect(self, worker_id: str):
        self.active_workers.pop(worker_id, None)


ws_manager = WSManager()
