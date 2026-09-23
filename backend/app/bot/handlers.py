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
    workers_online = ws_manager.workers_count
    status_text = (
        f"Активных серверов: {workers_online}"
        if workers_online > 0
        else "Серверы временно недоступны."
    )
    text = f"Панель управления загрузками.\n\n{status_text}"
    await message.answer_photo(photo=settings.MAIN_PHOTO_ID, caption=text)


# @router.message(F.photo)
# async def get_photo_id(message: Message):
#    if message.photo:
#        await message.answer(
#            f"ID фото для .env:\n`MAIN_PHOTO_ID={message.photo[-1].file_id}`",
#            parse_mode="Markdown",
#        )


@router.message(F.text)
async def handle_youtube_links(message: Message, session: AsyncSession):
    if not message.from_user or not message.entities:
        return

    youtube_links = [
        entity.extract_from(message.text)
        for entity in message.entities
        if entity.type == "url"
        and (
            "youtube.com" in entity.extract_from(message.text)
            or "youtu.be" in entity.extract_from(message.text)
        )
    ]

    if not youtube_links:
        return

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

        text = "Выберите формат скачивания:"
        await message.answer_photo(
            photo=settings.MAIN_PHOTO_ID,
            caption=text,
            reply_markup=builder.as_markup(),
        )

    else:
        await message.answer("Пакетная обработка в разработке.")


@router.callback_query(
    TaskAction.filter(F.action.in_(["video", "audio", "dl_audio_full", "dl_audio_cut"]))
)
async def process_format_selection(
    callback: CallbackQuery, callback_data: TaskAction, session: AsyncSession
):
    if not callback.message or not callback.from_user:
        return

    await callback.answer()

    if not isinstance(callback.message, Message):
        await callback.answer(
            "Сообщение устарело. Отправьте ссылку заново.", show_alert=True
        )
        return

    task = await session.get(Task, callback_data.task_id)
    if not task:
        await callback.answer(text="Задача не найдена.", show_alert=True)
        return

    task.chat_id = callback.message.chat.id
    task.message_id = callback.message.message_id

    # Пропуск этапа get_meta для задач нарезки
    if callback_data.action in ["dl_audio_full", "dl_audio_cut"]:
        task.format_type = (
            "audio" if callback_data.action == "dl_audio_full" else "audio_cut"
        )
        task.status = "ready_to_download"
    else:
        task.format_type = callback_data.action
        task.status = "pending"

    await session.commit()
    await callback.message.edit_caption(
        caption="Добавлено в очередь. Ожидание сервера..."
    )
