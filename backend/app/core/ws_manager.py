from fastapi import WebSocket
from loguru import logger


class WSManager:
    def __init__(self):
        self.active_workers: dict[str, WebSocket] = {}

    @property
    def workers_count(self) -> int:
        """Возвращает количество активных WebSocket соединений."""
        return len(self.active_workers)

    async def connect(self, worker_id: str, ws: WebSocket):
        await ws.accept()
        self.active_workers[worker_id] = ws
        logger.info(f"Воркер {worker_id} подключился. Активных: {self.workers_count}")

    def disconnect(self, worker_id: str):
        self.active_workers.pop(worker_id, None)
        logger.warning(f"Воркер {worker_id} отключился. Активных: {self.workers_count}")

    async def send_task(self, worker_id: str, task_data: dict) -> bool:
        """Отправляет задачу указанному воркеру, если он онлайн."""
        if ws := self.active_workers.get(worker_id):
            await ws.send_json(task_data)
            return True
        return False


ws_manager = WSManager()
