import asyncio
from contextlib import asynccontextmanager

from aiogram.types import InputMediaPhoto
from aiogram.utils.keyboard import InlineKeyboardBuilder
from app.bot.core import bot, dp, set_app_menu, set_bot_avatar
from app.bot.handlers import TaskAction, router
from app.bot.middlewares import DbSessionMiddleware, MaintenanceMiddleware
from app.core.config import settings
from app.core.ws_manager import ws_manager
from app.db.database import Base, async_session_maker, engine
from app.db.models import Task
from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
from loguru import logger
from sqlalchemy import select, update

dp.message.outer_middleware(MaintenanceMiddleware(is_maintenance=False))
dp.callback_query.outer_middleware(MaintenanceMiddleware(is_maintenance=False))
dp.message.middleware(DbSessionMiddleware(async_session_maker))
dp.callback_query.middleware(DbSessionMiddleware(async_session_maker))
dp.include_router(router)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.add("logs/bot.log", rotation="10 MB", retention="10 days", level="INFO")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with async_session_maker() as session:
        await session.execute(
            update(Task)
            .where(Task.status == "fetching_meta")
            .values(status="pending", worker_id=None)
        )
        await session.execute(
            update(Task)
            .where(Task.status.in_(["downloading", "uploading"]))
            .values(status="ready_to_download", worker_id=None)
        )
        await session.commit()

    await set_bot_avatar(bot)
    await bot.delete_webhook(drop_pending_updates=True)
    await set_app_menu(bot)

    bot_task = asyncio.create_task(dp.start_polling(bot, handle_signals=False))
    yield

    bot_task.cancel()
    try:
        await bot_task
    except asyncio.CancelledError:
        pass
    await bot.session.close()


app = FastAPI(lifespan=lifespan)


async def update_telegram_ui(
    task: Task, text: str, markup=None, thumbnail_url: str = None
):
    try:
        if thumbnail_url and settings.MAIN_PHOTO_ID:
            media = InputMediaPhoto(
                media=thumbnail_url, caption=text, parse_mode="Markdown"
            )
            await bot.edit_message_media(
                chat_id=task.chat_id,
                message_id=task.message_id,
                media=media,
                reply_markup=markup,
            )
        elif settings.MAIN_PHOTO_ID:
            await bot.edit_message_caption(
                chat_id=task.chat_id,
                message_id=task.message_id,
                caption=text,
                reply_markup=markup,
                parse_mode="Markdown",
            )
        else:
            await bot.edit_message_text(
                chat_id=task.chat_id,
                message_id=task.message_id,
                text=text,
                reply_markup=markup,
                parse_mode="Markdown",
                disable_web_page_preview=True,
            )
    except Exception as e:
        logger.error(f"Ошибка обновления UI: {e}")


@app.websocket("/ws/worker/{worker_id}")
async def worker_endpoint(
    websocket: WebSocket, worker_id: str, token: str = Query(...)
):
    if token != settings.WORKER_TOKEN.get_secret_value():
        await websocket.close(code=1008)
        return

    await ws_manager.connect(worker_id, websocket)

    try:
        while True:
            data = await websocket.receive_json()
            action = data.get("action")

            if action == "get_task":
                async with async_session_maker() as session:
                    stmt = (
                        select(Task)
                        .where(Task.status.in_(["pending", "ready_to_download"]))
                        .order_by(Task.id.asc())
                        .limit(1)
                    )
                    task = (await session.execute(stmt)).scalar_one_or_none()

                    if task:
                        command = "get_meta" if task.status == "pending" else "download"
                        task.status = (
                            "fetching_meta" if command == "get_meta" else "downloading"
                        )
                        task.worker_id = worker_id
                        await session.commit()

                        await websocket.send_json(
                            {
                                "command": command,
                                "task_id": task.id,
                                "url": task.url,
                                "format_type": task.format_type,
                                "chat_id": task.chat_id,
                                "message_id": task.message_id,
                                "title": task.title,
                            }
                        )
                    else:
                        await websocket.send_json({"action": "idle"})

            elif action == "status_update":
                async with async_session_maker() as session:
                    task = await session.get(Task, data.get("task_id"))
                    if task and task.chat_id and task.message_id:
                        task.status = data.get("status")
                        await session.commit()

                        status_msg = (
                            "В процессе скачивания..."
                            if task.status == "downloading"
                            else "Загрузка в Telegram..."
                        )
                        text = f"*Видео: {task.title}*\nКанал: [{task.channel}]({task.url})\n\n_{status_msg}_"
                        await update_telegram_ui(task, text)

            elif action == "meta_ready":
                async with async_session_maker() as session:
                    task = await session.get(Task, data.get("task_id"))
                    if task and task.chat_id and task.message_id:
                        task.title = data.get("title")
                        task.channel = data.get("channel")

                        base_text = f"*Видео: {task.title}*\nКанал: [{task.channel}]({task.url})\n\n"

                        if task.format_type == "audio" and data.get("has_timecodes"):
                            task.status = "awaiting_cut"
                            builder = InlineKeyboardBuilder()
                            builder.button(
                                text="Скачать целиком",
                                callback_data=TaskAction(
                                    action="dl_audio_full", task_id=task.id
                                ),
                            )
                            builder.button(
                                text="Нарезать по таймкодам",
                                callback_data=TaskAction(
                                    action="dl_audio_cut", task_id=task.id
                                ),
                            )
                            builder.adjust(1)

                            await session.commit()
                            await update_telegram_ui(
                                task,
                                base_text + "_Найдены таймкоды. Выберите формат:_",
                                builder.as_markup(),
                                data.get("thumbnail"),
                            )
                        else:
                            task.status = "ready_to_download"
                            await session.commit()
                            await update_telegram_ui(
                                task,
                                base_text + "_Очередь на скачивание..._",
                                None,
                                data.get("thumbnail"),
                            )

            elif action == "download_complete":
                async with async_session_maker() as session:
                    task = await session.get(Task, data.get("task_id"))
                    if task and task.chat_id and task.message_id:
                        task.status = "completed"
                        await session.commit()
                        try:
                            await bot.delete_message(
                                chat_id=task.chat_id, message_id=task.message_id
                            )
                        except Exception:
                            pass

            elif action == "error":
                async with async_session_maker() as session:
                    task = await session.get(Task, data.get("task_id"))
                    if task and task.chat_id and task.message_id:
                        task.status = "error"
                        await session.commit()
                        await update_telegram_ui(
                            task, "*Ошибка скачивания*\nНе удалось загрузить медиа."
                        )

    except WebSocketDisconnect:
        ws_manager.disconnect(worker_id)
        async with async_session_maker() as session:
            await session.execute(
                update(Task)
                .where(
                    Task.worker_id == worker_id,
                    Task.status.in_(
                        ["processing", "fetching_meta", "downloading", "uploading"]
                    ),
                )
                .values(status="pending", worker_id=None)
            )
            await session.commit()
