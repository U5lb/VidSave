import asyncio
from contextlib import asynccontextmanager

from app.bot.core import bot, dp, set_app_menu, set_bot_avatar
from app.bot.handlers import router
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
                    # Ищем самую старую задачу в статусе pending
                    stmt = (
                        select(Task)
                        .where(Task.status == "pending")
                        .order_by(Task.id.asc())
                        .limit(1)
                    )
                    result = await session.execute(stmt)
                    task = result.scalar_one_or_none()

                    if task:
                        # Бронируем задачу за этим воркером
                        task.status = "processing"
                        task.worker_id = worker_id
                        await session.commit()

                        # Отправляем задачу воркеру
                        await websocket.send_json(
                            {
                                "task_id": task.id,
                                "url": task.url,
                                "format_type": task.format_type,
                            }
                        )
                    else:
                        # Работы нет
                        await websocket.send_json({"action": "idle"})

            # Здесь позже добавим обработку "meta_ready" и "progress"

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
