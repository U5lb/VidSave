import asyncio
import glob
import json
import logging
import os

import aiohttp
from config import settings
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s"
)
logger = logging.getLogger(__name__)

SERVER_URL = settings.SERVER_URL.get_secret_value()
TELEGRAM_API_URL = settings.TELEGRAM_API_URL
BOT_TOKEN = settings.BOT_TOKEN.get_secret_value()
BOT_USERNAME = settings.BOT_USERNAME


DOWNLOADS_DIR = "/app/downloads"
os.makedirs(DOWNLOADS_DIR, exist_ok=True)


async def get_video_meta(url: str) -> dict | None:
    process = await asyncio.create_subprocess_exec(
        "yt-dlp",
        "-J",
        "--no-playlist",
        url,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await process.communicate()
    if process.returncode == 0:
        return json.loads(stdout.decode("utf-8"))
    return None


async def get_video_dimensions(file_path: str) -> tuple[int, int]:
    try:
        process = await asyncio.create_subprocess_exec(
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "csv=s=x:p=0",
            file_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await process.communicate()
        if process.returncode == 0 and stdout:
            w, h = stdout.decode("utf-8").strip().split("x")
            return int(w), int(h)
    except Exception as e:
        logger.error(f"Ошибка получения размеров: {e}")
    return 1280, 720


async def download_media(url: str, format_type: str, task_id: int) -> bool:
    logger.info(f"Начало скачивания задачи {task_id}")
    args = ["yt-dlp", "--no-playlist", "--embed-metadata"]

    if format_type in ["audio", "audio_cut"]:
        args.extend(
            ["--embed-thumbnail", "-f", "bestaudio", "-x", "--audio-format", "mp3"]
        )
        if format_type == "audio_cut":
            args.extend(
                [
                    "--split-chapters",
                    "-o",
                    f"chapter:{DOWNLOADS_DIR}/chapter_{task_id}_%(section_number)02d_%(section_title)s.%(ext)s",
                    "-o",
                    f"{DOWNLOADS_DIR}/main_{task_id}_media.%(ext)s",
                ]
            )
        else:
            args.extend(["-o", f"{DOWNLOADS_DIR}/{task_id}_media.%(ext)s"])
    else:
        args.extend(
            [
                "-f",
                "bestvideo[vcodec^=avc1][ext=mp4]+bestaudio[ext=m4a]/bestvideo[vcodec^=avc1]+bestaudio/best[vcodec^=avc1]/best",
                "--merge-output-format",
                "mp4",
                "-o",
                f"{DOWNLOADS_DIR}/{task_id}_media.%(ext)s",
            ]
        )

    args.append(url)

    env = os.environ.copy()
    env["PATH"] = f"/root/.deno/bin:{env.get('PATH', '')}"

    process = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env
    )

    async def read_stream(stream, is_error=False):
        while line := await stream.readline():
            text = line.decode("utf-8", errors="ignore").strip()
            if text:
                if is_error:
                    logger.error(f"[yt-dlp] {text}")
                else:
                    logger.info(f"[yt-dlp] {text}")

    await asyncio.gather(
        read_stream(process.stdout), read_stream(process.stderr, is_error=True)
    )
    await process.wait()
    return process.returncode == 0


async def upload_to_telegram(
    task_data: dict, file_path: str, format_type: str, task_id: int
) -> bool:
    chat_id = task_data.get("chat_id")
    message_id = task_data.get("message_id")
    is_audio = file_path.endswith((".mp3", ".m4a"))
    title = task_data.get("title", "Медиа")

    # Парсинг названия трека из шаблона yt-dlp
    if is_audio and format_type == "audio_cut" and "chapter_" in file_path:
        parts = os.path.basename(file_path).split(f"_{task_id}_", 1)
        if len(parts) == 2:
            track_title = parts[1].rsplit(".", 1)[0]
            if track_title[:2].isdigit() and track_title[2] == "_":
                track_title = track_title[3:]
            title = f"{title} - {track_title}"

    api_endpoint = (
        f"{TELEGRAM_API_URL}/bot{BOT_TOKEN}/{'sendAudio' if is_audio else 'sendVideo'}"
    )

    payload = {
        "chat_id": chat_id,
        "reply_to_message_id": message_id,
        "caption": f"*{title}*\n_Скачано через @{BOT_USERNAME}_",
        "parse_mode": "Markdown",
    }

    if is_audio:
        payload["audio"] = f"file://{os.path.abspath(file_path)}"
        payload["title"] = title
    else:
        payload["video"] = f"file://{os.path.abspath(file_path)}"
        payload["supports_streaming"] = True
        w, h = await get_video_dimensions(file_path)
        payload["width"] = w
        payload["height"] = h

    logger.info(f"Выгрузка {file_path} в Telegram...")
    timeout = aiohttp.ClientTimeout(total=None, sock_connect=60, sock_read=None)

    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(api_endpoint, json=payload) as resp:
                result = await resp.json()
                if not result.get("ok"):
                    logger.error(f"Ошибка Telegram API: {result}")
                    return False
                return True
    except Exception as e:
        logger.error(f"Ошибка выгрузки: {e}")
        return False


async def handle_download_and_upload(task_data: dict, websocket):
    task_id = task_data.get("task_id")
    format_type = task_data.get("format_type")

    await websocket.send(
        json.dumps(
            {"action": "status_update", "task_id": task_id, "status": "downloading"}
        )
    )

    if not await download_media(task_data.get("url"), format_type, task_id):
        await websocket.send(json.dumps({"action": "error", "task_id": task_id}))
        return

    await websocket.send(
        json.dumps(
            {"action": "status_update", "task_id": task_id, "status": "uploading"}
        )
    )

    if format_type == "audio_cut":
        main_file = f"{DOWNLOADS_DIR}/main_{task_id}_media.mp3"
        if os.path.exists(main_file):
            try:
                os.remove(main_file)
            except OSError as e:
                logger.error(
                    f"Не удалось удалить основной файл нарезки {main_file}: {e}"
                )
        downloaded_files = sorted(glob.glob(f"{DOWNLOADS_DIR}/chapter_{task_id}_*"))
    else:
        downloaded_files = sorted(glob.glob(f"{DOWNLOADS_DIR}/*{task_id}_*"))

    for file_path in downloaded_files:
        await upload_to_telegram(task_data, file_path, format_type, task_id)
        try:
            os.remove(file_path)
        except OSError as e:
            logger.error(f"Ошибка удаления файла {file_path}: {e}")

        await asyncio.sleep(1.5)

    await websocket.send(
        json.dumps({"action": "download_complete", "task_id": task_id})
    )


async def process_task(task_data: dict, websocket):
    command = task_data.get("command")
    task_id = task_data.get("task_id")

    if command == "get_meta":
        meta = await get_video_meta(task_data.get("url"))
        if meta:
            await websocket.send(
                json.dumps(
                    {
                        "action": "meta_ready",
                        "task_id": task_id,
                        "has_timecodes": bool(meta.get("chapters")),
                        "title": meta.get("title", "Без названия"),
                        "channel": meta.get("uploader", "Неизвестный канал"),
                        "thumbnail": meta.get("thumbnail"),
                    }
                )
            )
    elif command == "download":
        await handle_download_and_upload(task_data, websocket)


async def worker_loop():
    try:
        async with connect(SERVER_URL) as websocket:
            logger.info("Соединение со шлюзом установлено. Запрос задач...")
            while True:
                await websocket.send(json.dumps({"action": "get_task"}))
                response = json.loads(await websocket.recv())

                if response.get("action") == "idle":
                    await asyncio.sleep(5)
                elif "task_id" in response:
                    asyncio.create_task(process_task(response, websocket))
    except ConnectionClosed:
        logger.warning("Соединение разорвано. Переподключение...")
    except Exception as e:
        logger.error(f"Системная ошибка воркера: {e}")


async def main():
    while True:
        await worker_loop()
        await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(main())
