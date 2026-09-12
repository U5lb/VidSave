from aiogram import F, Router
from aiogram.filters.callback_data import CallbackData
from aiogram.types import Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from app.core.config import settings
from app.db.models import Task
from sqlalchemy.ext.asyncio import AsyncSession

router = Router()


class TaskAction(CallbackData, prefix="task"):
    action: str
    task_id: int


# Системный хендлер для получения file_id
@router.message(F.photo)
async def get_photo_id(message: Message):
    if message.photo is None:
        return
    photo_id = message.photo[-1].file_id

    await message.answer(
        f"Добавьте этот ID в .env как:\n`MAIN_PHOTO_ID={photo_id}`",
        parse_mode="Markdown",
    )


@router.message(F.text)
async def handle_youtube_links(message: Message, session: AsyncSession):
    if not message.entities:
        return

    youtube_links = []
    for entity in message.entities:
        if entity.type == "url":
            if message.text is None:
                return
            url = entity.extract_from(message.text)
            if "youtube.com" in url or "youtu.be" in url:
                youtube_links.append(url)

    if not youtube_links:
        return

    if len(youtube_links) == 1:
        url = youtube_links[0]
        if message.from_user is None:
            return
        new_task = Task(user_id=message.from_user.id, url=url, status="draft")
        session.add(new_task)
        await session.commit()
        await session.refresh(new_task)

        builder = InlineKeyboardBuilder()
        builder.button(
            text="Видео",
            callback_data=TaskAction(action="video", task_id=new_task.id),
        )
        builder.button(
            text="Аудио",
            callback_data=TaskAction(action="audio", task_id=new_task.id),
        )
        builder.button(
            text="Аудио - Нарезка по таймкодам",
            callback_data=TaskAction(action="audio_cut", task_id=new_task.id),
        )
        builder.adjust(2, 1)

        text = "Выберите формат скачивания:"

        # Проверяем, задан ли ID фото в конфигурации
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
