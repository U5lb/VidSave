import os

from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramAPIError
from aiogram.types import (
    FSInputFile,
    InputProfilePhotoStatic,
    MenuButtonWebApp,
    WebAppInfo,
)
from app.core.config import settings
from loguru import logger

bot = Bot(token=settings.BOT_TOKEN.get_secret_value())

dp = Dispatcher()


async def set_app_menu(bot: Bot) -> None:
    await bot.set_chat_menu_button(
        menu_button=MenuButtonWebApp(
            text="Меню", web_app=WebAppInfo(url=settings.WEB_APP_URL)
        )
    )


async def set_bot_avatar(bot: Bot):
    """Загружает аватар бота из локальной директории assets."""
    avatar_path = "assets/avatar.jpg"

    if not os.path.exists(avatar_path):
        logger.warning(f"Файл аватара не найден по пути: {avatar_path}")
        return

    try:
        file_obj = FSInputFile(avatar_path)
        photo_wrapper = InputProfilePhotoStatic(photo=file_obj)
        await bot.set_my_profile_photo(photo=photo_wrapper)
        logger.info("Аватар успешно загружен из исходников.")
    except TelegramAPIError as e:
        logger.error(f"Ошибка API Telegram при загрузке аватара: {e.message}")
    except OSError as e:
        logger.error(f"Системная ошибка чтения файла аватара: {e}")
