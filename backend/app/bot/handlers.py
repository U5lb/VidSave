import asyncio

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import CommandStart
from aiogram.filters.callback_data import CallbackData
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from app.core.config import settings
from app.core.ws_manager import ws_manager
from app.db.models import Task
from sqlalchemy.ext.asyncio import AsyncSession

router = Router()


class TaskAction(CallbackData, prefix="task"):
    action: str
    task_id: int


@router.message(CommandStart())
async def cmd_start(message: Message):
    """
    Обработчик стартовой команды.
    Отображает текущее состояние кластера воркеров.
    """
    workers_online = ws_manager.workers_count
    status_text = (
        f"Активных серверов для скачивания: {workers_online}"
        if workers_online > 0
        else "Серверы скачивания временно недоступны."
    )
    await message.answer(f"Панель управления загрузками.\n{status_text}")


@router.message(F.photo)
async def get_photo_id(message: Message):
    photo_id = message.photo[-1].file_id
    await message.answer(
        f"ID фото для .env:\n`MAIN_PHOTO_ID={photo_id}`", parse_mode="Markdown"
    )


@router.message(F.text)
async def handle_youtube_links(message: Message, session: AsyncSession):
    """
    Парсинг YouTube ссылок, очистка чата от исходного сообщения
    и формирование черновика задачи в БД.
    """
    if not message.entities:
        return

    youtube_links = []
    for entity in message.entities:
        if entity.type == "url" and message.text:
            url = entity.extract_from(message.text)
            if "youtube.com" in url or "youtu.be" in url:
                youtube_links.append(url)

    if not youtube_links:
        return

    # Безопасное удаление сообщения пользователя с ссылками
    try:
        await message.delete()
    except TelegramAPIError:
        pass

    if len(youtube_links) == 1:
        new_task = Task(
            user_id=message.from_user.id, url=youtube_links[0], status="draft"
        )
        session.add(new_task)
        await session.commit()
        await session.refresh(new_task)

        builder = InlineKeyboardBuilder()
        builder.button(
            text="Видео", callback_data=TaskAction(action="video", task_id=new_task.id)
        )
        builder.button(
            text="Аудио", callback_data=TaskAction(action="audio", task_id=new_task.id)
        )
        builder.adjust(2)

        text = "Выберите формат скачивания:"

        if settings.MAIN_PHOTO_ID:
            await message.answer_photo(
                photo=settings.MAIN_PHOTO_ID,
                caption=text,
                reply_markup=builder.as_markup(),
            )
        else:
            await message.answer(text=text, reply_markup=builder.as_markup())
    else:
        await message.answer("Пакетная обработка в разработке.")


@router.callback_query(TaskAction.filter(F.action.in_(["video", "audio"])))
async def process_format_selection(
    callback: CallbackQuery, callback_data: TaskAction, session: AsyncSession
):
    """
    Обработка выбора формата.
    Включает механизм повторных попыток отправки задачи воркеру (retry_logic).
    Если воркеры недоступны, задача сохраняется со статусом 'pending'.
    """
    await callback.answer()

    task = await session.get(Task, callback_data.task_id)
    if not task:
        await callback.message.edit_text("Ошибка: Задача устарела или не найдена.")
        return

    # Фиксация выбора пользователя и координат интерфейса
    task.chat_id = callback.message.chat.id
    task.message_id = callback.message.message_id
    task.format_type = callback_data.action
    task.status = "pending"
    await session.commit()

    await callback.message.edit_caption(caption="Подключение к воркеру...")

    payload = {"task_id": task.id, "url": task.url, "action": task.format_type}

    # Попытка отправки с интервалом
    worker_id = "orangepi_1"
    success = await ws_manager.send_task(worker_id, payload)

    if not success:
        await asyncio.sleep(2.0)
        success = await ws_manager.send_task(worker_id, payload)

    if success:
        task.status = "fetching_meta"
        await session.commit()
        await callback.message.edit_caption(caption="Анализ медиаданных...")
    else:
        await callback.message.edit_caption(
            caption="Воркеры временно недоступны. Ссылки сохранены в очередь, скачивание начнется автоматически."
        )
