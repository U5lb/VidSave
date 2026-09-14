import asyncio
import json
import logging

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s"
)
logger = logging.getLogger(__name__)

SERVER_URL = "ws://127.0.0.1:8000/ws/worker/orangepi_1?token=mysecter123"


async def get_video_meta(url: str):
    process = await asyncio.create_subprocess_exec(
        "yt-dlp",
        "-J",
        "--no-playlist",
        url,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    if process.returncode == 0:
        return json.loads(stdout.decode("utf-8"))
    return None


async def download_media(url: str, format_type: str, task_id: int):
    logger.info(f"Начинаю скачивание задачи {task_id}")

    # Базовые флаги: без плейлистов, встроить мету, встроить обложку
    args = ["yt-dlp", "--no-playlist", "--embed-metadata", "--embed-thumbnail"]

    if format_type in ["audio", "audio_cut"]:
        args.extend(["-f", "bestaudio", "-x", "--audio-format", "mp3"])

        if format_type == "audio_cut":
            # Разделение по таймкодам.
            # Специальный синтаксис output для генерации множества файлов: chapter:ШАБЛОН
            args.extend(["--split-chapters"])
            args.extend(["-o", f"chapter:{task_id}_%(section_title)s.%(ext)s"])
        else:
            args.extend(["-o", f"{task_id}_%(title)s.%(ext)s"])
    else:
        # Видео
        args.extend(["-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"])
        args.extend(["-o", f"{task_id}_%(title)s.%(ext)s"])

    process = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    await process.wait()

    if process.returncode == 0:
        logger.info(f"Задача {task_id} скачана.")
        return True
    else:
        logger.error("Ошибка скачивания")
        return False


async def process_task(task_data: dict, websocket):
    task_id = task_data.get("task_id")
    url = task_data.get("url")
    format_type = task_data.get("format_type")
    command = task_data.get("command")

    if command == "get_meta":
        meta = await get_video_meta(url)
        if meta:
            has_timecodes = bool(meta.get("chapters"))
            title = meta.get("title", "Без названия")
            channel = meta.get("uploader", "Неизвестный канал")
            # Вытаскиваем прямую ссылку на превью в максимальном качестве
            thumbnail = meta.get("thumbnail")

            await websocket.send(
                json.dumps(
                    {
                        "action": "meta_ready",
                        "task_id": task_id,
                        "has_timecodes": has_timecodes,
                        "title": title,
                        "channel": channel,
                        "thumbnail": thumbnail,
                    }
                )
            )

    elif command == "download":
        success = await download_media(url, format_type, task_id)
        if success:
            await websocket.send(
                json.dumps({"action": "download_complete", "task_id": task_id})
            )


async def worker_loop():
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
                    await process_task(data, websocket)
    except ConnectionClosed:
        logger.warning("Соединение с сервером разорвано.")
    except Exception as e:
        logger.error(f"Непредвиденная ошибка: {e}")


async def main():
    while True:
        await worker_loop()
        await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(main())
