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
    text = f"Панель управления загрузками.\n\n{status_text}"

    if settings.MAIN_PHOTO_ID:
        await message.answer_photo(
            photo=settings.MAIN_PHOTO_ID,
            caption=text,
        )
    else:
        await message.answer(text=text)


@router.message(F.photo)
async def get_photo_id(message: Message):
    if message.photo is None:
        return
    photo_id = message.photo[-1].file_id
    await message.answer(
        f"ID фото для .env:\n`MAIN_PHOTO_ID={photo_id}`", parse_mode="Markdown"
    )


@router.message(F.text)
async def handle_youtube_links(message: Message, session: AsyncSession):
    if message.from_user is None:
        return
    if not message.entities:
        return
    """
    Парсинг YouTube ссылок, очистка чата от исходного сообщения
    и формирование черновика задачи в БД.
    """

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
    if callback.message is None or callback.from_user is None:
        return

    await callback.answer()

    if not isinstance(callback.message, Message):
        await callback.answer(
            "Сообщение устарело. Отправьте ссылку заново.", show_alert=True
        )
        return

    task = await session.get(Task, callback_data.task_id)
    if not task:
        await callback.answer(text="Задача устарела или не найдена.", show_alert=True)
        return

    # Запись параметров задачи в базу данных.
    # База данных выступает в роли очереди (Message Queue).
    task.chat_id = callback.message.chat.id
    task.message_id = callback.message.message_id
    task.format_type = callback_data.action
    task.status = "pending"
    await session.commit()

    # Сразу обновляем интерфейс для пользователя, не дожидаясь ответа от воркеров.
    # Как только любой свободный воркер заберет задачу из БД, статус поменяется автоматически через WebSocket-шлюз.
    await callback.message.edit_caption(
        caption="Добавлено в очередь. Ожидание свободного сервера..."
    )
