import asyncio
import asyncpg
import os
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.types import (
    Message,
    BotCommand,
    ReplyKeyboardMarkup,
    KeyboardButton,
    FSInputFile,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardRemove,
)
from aiogram.filters import Command
from config import BOT_TOKEN, DB_CONFIG_1
from parser import periodic_parser



logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
db_pool = None


async def connect_db():
    global db_pool
    if db_pool is None:
        db_pool = await asyncpg.create_pool(**DB_CONFIG_1)


async def set_main_menu():
    commands = [
        BotCommand(command="/menu", description="📜 Меню ресторана"),
        BotCommand(command="/info", description="ℹ️ О ресторане")
    ]
    await bot.set_my_commands(commands)


def get_main_menu_keyboard() -> ReplyKeyboardMarkup:
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📜 Меню ресторана")],
            [KeyboardButton(text="ℹ️ О ресторане")],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
    return keyboard


async def get_categories_keyboard() -> ReplyKeyboardMarkup:
    async with db_pool.acquire() as db:
        categories = await db.fetch("SELECT DISTINCT category FROM menu_items")
    keyboard = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=cat["category"])] for cat in categories],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
    return keyboard


async def get_dishes_inline_keyboard(category: str) -> InlineKeyboardMarkup:
    async with db_pool.acquire() as db:
        rows = await db.fetch("SELECT id, name FROM menu_items WHERE category = $1", category)

    buttons = [[InlineKeyboardButton(text=row["name"], callback_data=f"dish:{row['id']}")] for row in rows]
    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_categories")])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


@dp.message(Command("start"))
async def start_command(message: Message):
    keyboard = get_main_menu_keyboard()
    await message.answer("☕ Привет! Добро пожаловать в Coffeemania! Выберите действие:", reply_markup=keyboard)


@dp.message(lambda msg: msg.text == "📜 Меню ресторана")
async def menu_command(message: Message):
    keyboard = await get_categories_keyboard()
    await message.answer("📜 Выберите категорию:", reply_markup=keyboard)


@dp.message(lambda msg: msg.text == "ℹ️ О ресторане")
async def about_restaurant(message: Message):
    response = (
        "Кофемания — это 20 лет уюта, вкуса и заботы. "
        "С 2001 года мы создаем атмосферу, где сочетаются лучшие традиции кофейни и ресторана высокой кухни. "
    )
    await message.answer(response)


async def send_dish_info(message: Message, dish_record):
    dish_text = (
        f"🍽 *{dish_record['name']}*\n"
        f"💰 Цена: {dish_record['price']}\n"
        f"🔥 Калории: {dish_record.get('calories', 'N/A')} ккал\n"
        f"🥩 Белки: {dish_record.get('proteins', 'N/A')}\n"
        f"🥑 Жиры: {dish_record.get('fats', 'N/A')}\n"
        f"🍞 Углеводы: {dish_record.get('carbohydrates', 'N/A')}\n"
        f"⚖️ Вес: {dish_record.get('weight', 'N/A')}\n\n"
        f"📖 *Описание:*\n{dish_record['description'][:1000]}\n\n"
        f"⚠️ *Аллергены:*{dish_record['allergens'][10:1000]}\n\n"
        f"🛒 Присутствует в наличии: {"да" if dish_record['availability'] else "нет"}"
    )
    back_button = InlineKeyboardButton(
        text="🔙 Назад", callback_data=f"back_to_category:{dish_record['category']}"
    )
    back_kb = InlineKeyboardMarkup(inline_keyboard=[[back_button]])

    photo_path = dish_record["image_url"]
    if os.path.exists(photo_path) and os.path.isfile(photo_path):
        photo = FSInputFile(photo_path)
        await message.answer_photo(
            photo=photo,
            caption=dish_text,
            parse_mode="Markdown",
            reply_markup=back_kb
        )
    else:
        await message.answer(
            dish_text,
            parse_mode="Markdown",
            reply_markup=back_kb
        )

user_selected_category = {}
@dp.message()
async def handle_category_selection(message: Message):
    text = message.text.strip()
    async with db_pool.acquire() as db:
        dishes = await db.fetch("SELECT id, name FROM menu_items WHERE category = $1", text)

    if dishes:
        user_selected_category[message.from_user.id] = text
        inline_kb = await get_dishes_inline_keyboard(text)
        await message.answer(
            f"🍽 Меню категории *{text}*:",
            reply_markup=inline_kb,
            parse_mode="Markdown"
        )
    else:
        category = user_selected_category.get(message.from_user.id)
        if category:
            async with db_pool.acquire() as db:
                dish = await db.fetchrow(
                    "SELECT * FROM menu_items WHERE LOWER(name) = LOWER($1) AND category = $2",
                    text, category
                )
            if dish:
                await send_dish_info(message, dish)
            else:
                await message.answer("❌ Блюдо не найдено в выбранной категории. Попробуйте снова.")
        else:
            await message.answer("❌ Сначала выберите категорию из меню.")

@dp.callback_query(lambda c: c.data.startswith("dish:"))
async def dish_callback_handler(callback: types.CallbackQuery):
    dish_id = int(callback.data.split(":")[1])
    async with db_pool.acquire() as db:
        dish = await db.fetchrow("SELECT * FROM menu_items WHERE id = $1", dish_id)

    if dish:
        await send_dish_info(callback.message, dish)
    else:
        await callback.message.answer("❌ Блюдо не найдено.")

    await callback.answer()


@dp.callback_query(lambda c: c.data == "back_to_categories")
async def back_callback_handler(callback: types.CallbackQuery):

    await callback.message.edit_reply_markup(reply_markup=None)

    keyboard = await get_categories_keyboard()
    await callback.message.answer("📜 Выберите категорию:", reply_markup=keyboard)
    await callback.answer()


@dp.callback_query(lambda c: c.data.startswith("back_to_category:"))
async def back_to_category_handler(callback: types.CallbackQuery):
    _, category = callback.data.split(":", 1)
    inline_kb = await get_dishes_inline_keyboard(category)

    await bot.send_message(
        chat_id=callback.message.chat.id,
        text=f"🍽 Меню категории *{category}*:",
        reply_markup=inline_kb,
        parse_mode="Markdown"
    )
    await callback.answer()



async def start_bot():
    await connect_db()
    await set_main_menu()
    await dp.start_polling(bot)


async def main():
    asyncio.create_task(periodic_parser())
    await start_bot()


if __name__ == "__main__":
    asyncio.run(main())