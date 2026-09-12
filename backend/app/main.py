import asyncio
from contextlib import asynccontextmanager

from app.bot.core import bot, dp, set_app_menu, set_bot_avatar
from app.bot.handlers import router
from app.bot.middlewares import DbSessionMiddleware, MaintenanceMiddleware
from app.core.config import settings
from app.core.ws_manager import ws_manager
from app.db.database import Base, async_session_maker, engine
from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
from loguru import logger

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

    # Подключаем воркера и добавляем в словарь
    await ws_manager.connect(worker_id, websocket)

    try:
        while True:
            data = await websocket.receive_json()
            print(f"Воркер {worker_id} прислал данные: {data}")

    except WebSocketDisconnect:
        # Если связь оборвалась - безопасно удаляем воркера из словаря
        ws_manager.disconnect(worker_id)
