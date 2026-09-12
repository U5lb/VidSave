import asyncio
import json
import logging

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s"
)
logger = logging.getLogger(__name__)

# Замени IP и ТОКЕН на свои. Если тестируешь локально на Mac, пиши ws://127.0.0.1:8000/...
SERVER_URL = "ws://127.0.0.1:8000/ws/worker/orangepi_1?token=mysecter123"


async def process_task(task_data: dict):
    task_id = task_data.get("task_id")
    url = task_data.get("url")
    logger.info(f"Начинаю обработку задачи {task_id}: {url}")
    await asyncio.sleep(5)  # Имитация скачивания
    logger.info(f"Задача {task_id} завершена")


async def worker_loop():
    logger.info(f"Подключение к шлюзу: {SERVER_URL.split('?')[0]}...")

    try:
        async with connect(SERVER_URL) as websocket:
            logger.info("Соединение установлено. Запрашиваю задачи...")

            while True:
                await websocket.send(json.dumps({"action": "get_task"}))

                response = await websocket.recv()
                data = json.loads(response)

                if data.get("action") == "idle":
                    await asyncio.sleep(5)
                elif "task_id" in data:
                    await process_task(data)

    except ConnectionClosed:
        logger.warning("Соединение с сервером разорвано.")
    except Exception as e:
        logger.error(f"Непредвиденная ошибка: {e}")


async def main():
    while True:
        await worker_loop()
        logger.info("Переподключение через 5 секунд...")
        await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(main())
