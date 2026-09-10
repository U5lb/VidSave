from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject
from sqlalchemy.ext.asyncio import async_sessionmaker


class MaintenanceMiddleware(BaseMiddleware):
    """
    Внешняя мидлварь. Срабатывает ДО поиска хендлеров.
    Отсекает запросы, если бот на обслуживании.
    """

    def __init__(self, is_maintenance: bool = False):
        self.is_maintenance = is_maintenance

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        # Если режим включен, блокируем дальнейшее выполнение
        if self.is_maintenance:
            text = "Сервис находится на техническом обслуживании. Возвращайтесь позже."

            if isinstance(event, Message):
                await event.answer(text)
            elif isinstance(event, CallbackQuery):
                await event.answer(text, show_alert=True)

            return  # Прерываем цепочку, БД не тревожим

        return await handler(event, data)


class DbSessionMiddleware(BaseMiddleware):
    """
    Внутренняя мидлварь. Срабатывает ТОЛЬКО если найден нужный хендлер.
    Безопасно прокидывает сессию БД.
    """

    def __init__(self, session_pool: async_sessionmaker):
        self.session_pool = session_pool

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        # Открываем сессию, кладем в data
        async with self.session_pool() as session:
            data["session"] = session
            return await handler(event, data)
