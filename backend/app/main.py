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

# Регистрация мидлварей
dp.message.outer_middleware(MaintenanceMiddleware(is_maintenance=False))
dp.callback_query.outer_middleware(MaintenanceMiddleware(is_maintenance=False))
dp.message.middleware(DbSessionMiddleware(async_session_maker))
dp.callback_query.middleware(DbSessionMiddleware(async_session_maker))

# Подключение роутеров
dp.include_router(router)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Красивое и правильное логирование
    logger.add(
        "logs/bot.log",
        rotation="10 MB",
        retention="10 days",
        level="INFO",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
    )

    logger.info("Инициализация базы данных...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)  # НЕ ЗАБЫТЬ УДАЛИТЬ
        await conn.run_sync(Base.metadata.create_all)

    logger.info("Настройка визуального профиля и меню бота...")
    # Ставим аватар из файла backend/assets/avatar.jpg
    await set_bot_avatar(bot)

    # Удаляем старые запросы к боту за время пока бот был выключен
    await bot.delete_webhook(drop_pending_updates=True)

    # Подключаем WebApp
    await set_app_menu(bot)

    logger.info("Запуск поллинга aiogram...")
    bot_task = asyncio.create_task(dp.start_polling(bot, handle_signals=False))

    yield

    logger.warning("Остановка приложения, закрытие сессий...")
    bot_task.cancel()
    try:
        await bot_task
    except asyncio.CancelledError:
        pass

    await bot.session.close()


app = FastAPI(lifespan=lifespan)


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
            # Ждем JSON от Воркера
            data = await websocket.receive_json()
            action = data.get("action")

            # Воркер просит работу
            if action == "get_task":
                async with async_session_maker() as session:
                    # 1. ИЩЕМ И PENDING, И READY_TO_DOWNLOAD
                    stmt = (
                        select(Task)
                        .where(Task.status.in_(["pending", "ready_to_download"]))
                        .order_by(Task.id.asc())
                        .limit(1)
                    )
                    result = await session.execute(stmt)
                    task = result.scalar_one_or_none()

                    if task:
                        # 2. ОПРЕДЕЛЯЕМ КОМАНДУ
                        command = "get_meta" if task.status == "pending" else "download"

                        # 3. МЕНЯЕМ СТАТУС В ЗАВИСИМОСТИ ОТ КОМАНДЫ
                        task.status = (
                            "fetching_meta" if command == "get_meta" else "downloading"
                        )
                        task.worker_id = worker_id
                        await session.commit()

                        # 4. ОТПРАВЛЯЕМ КОМАНДУ ВОРКЕРУ
                        await websocket.send_json(
                            {
                                "command": command,  # Добавлено поле command
                                "task_id": task.id,
                                "url": task.url,
                                "format_type": task.format_type,
                            }
                        )
                    else:
                        await websocket.send_json({"action": "idle"})

            # Обработка мета данных
            elif action == "meta_ready":
                task_id = data.get("task_id")
                has_timecodes = data.get("has_timecodes")
                title = data.get("title")
                channel = data.get("channel")
                thumbnail_url = data.get("thumbnail")

                async with async_session_maker() as session:
                    task = await session.get(Task, task_id)
                    if task and task.chat_id and task.message_id:
                        task.title = title
                        task.channel = channel

                        channel_link = f"[{channel}]({task.url})"
                        base_text = f"*Видео: {title}*\nКанал: {channel_link}\n\n"

                        if task.format_type == "audio" and has_timecodes:
                            task.status = "awaiting_cut"
                            await session.commit()

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

                            text = base_text + "_Найдены таймкоды. Выберите формат:_"
                            markup = builder.as_markup()
                        else:
                            task.status = "ready_to_download"
                            await session.commit()

                            text = base_text + "_Очередь на скачивание..._"
                            markup = None

                        try:
                            # Если у нас есть превью и изначальное сообщение было с фото (MAIN_PHOTO_ID)
                            if thumbnail_url and settings.MAIN_PHOTO_ID:
                                media = InputMediaPhoto(
                                    media=thumbnail_url,
                                    caption=text,
                                    parse_mode="Markdown",
                                )
                                await bot.edit_message_media(
                                    chat_id=task.chat_id,
                                    message_id=task.message_id,
                                    media=media,
                                    reply_markup=markup,
                                )
                            # Фолбэк: если превью нет, но было системное фото
                            elif settings.MAIN_PHOTO_ID:
                                await bot.edit_message_caption(
                                    chat_id=task.chat_id,
                                    message_id=task.message_id,
                                    caption=text,
                                    reply_markup=markup,
                                    parse_mode="Markdown",
                                )
                            # Фолбэк: если фото вообще не было (текстовое сообщение)
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
                            logger.error(f"Ошибка обновления UI Telegram: {e}")

    except WebSocketDisconnect:
        # Воркер отвалился. Начинаем процедуру спасения задач.
        ws_manager.disconnect(worker_id)

        async with async_session_maker() as session:
            # Находим все задачи, которые этот воркер не успел доделать, и возвращаем в очередь
            stmt = (
                update(Task)
                .where(
                    Task.worker_id == worker_id,
                    Task.status.in_(["processing", "fetching_meta"]),
                )
                .values(status="pending", worker_id=None)
            )

            await session.execute(stmt)
            await session.commit()
