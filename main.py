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
)
from aiogram.filters import Command
from config import BOT_TOKEN, DB_CONFIG  # Импорт конфигурации
from parser import periodic_parser  # Импорт функции периодического парсера

# Логирование
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Инициализация бота и диспетчера
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Глобальная переменная для пула соединений с БД
db_pool = None


# Инициализация соединения с БД
async def connect_db():
    global db_pool
    if db_pool is None:
        db_pool = await asyncpg.create_pool(**DB_CONFIG)


# Установка команд меню
async def set_main_menu():
    commands = [BotCommand(command="/menu", description="📜 Меню ресторана")]
    await bot.set_my_commands(commands)


# Главное меню (reply-клавиатура)
def get_main_menu_keyboard() -> ReplyKeyboardMarkup:
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📜 Меню ресторана")],
            [KeyboardButton(text="ℹ️ О ресторане")],
        ],
        resize_keyboard=True,
    )
    return keyboard


# Клавиатура с категориями (reply-клавиатура)
async def get_categories_keyboard() -> ReplyKeyboardMarkup:
    async with db_pool.acquire() as db:
        categories = await db.fetch("SELECT DISTINCT category FROM menu_items")
    keyboard = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=cat["category"])] for cat in categories],
        resize_keyboard=True,
    )
    return keyboard


# Инлайн-клавиатура с блюдами
async def get_dishes_inline_keyboard(category: str) -> InlineKeyboardMarkup:
    async with db_pool.acquire() as db:
        rows = await db.fetch("SELECT id, name FROM menu_items WHERE category = $1", category)

    buttons = [[InlineKeyboardButton(text=row["name"], callback_data=f"dish:{row['id']}")] for row in rows]
    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_categories")])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


# Команда /start
@dp.message(Command("start"))
async def start_command(message: Message):
    keyboard = get_main_menu_keyboard()
    await message.answer("☕ Привет! Добро пожаловать в Coffeemania! Выберите действие:", reply_markup=keyboard)


# Обработчик кнопки "📜 Меню ресторана"
@dp.message(lambda msg: msg.text == "📜 Меню ресторана")
async def menu_command(message: Message):
    keyboard = await get_categories_keyboard()
    await message.answer("📜 Выберите категорию:", reply_markup=keyboard)


# Обработчик кнопки "ℹ️ О ресторане"
@dp.message(lambda msg: msg.text == "ℹ️ О ресторане")
async def about_restaurant(message: Message):
    response = (
        "Кофемания — это 20 лет уюта, вкуса и заботы. "
        "С 2001 года мы создаем атмосферу, где сочетаются лучшие традиции кофейни и ресторана высокой кухни. "
    )
    await message.answer(response)


# Отправка информации о блюде
async def send_dish_info(message: Message, dish_record):
    dish_text = (
        f"🍽 *{dish_record['name']}*\n"
        f"💰 Цена: {dish_record['price']}\n"
        f"🔥 Калории: {dish_record.get('calories', 'N/A')} ккал\n"
        f"🥩 Белки: {dish_record.get('proteins', 'N/A')}\n"
        f"🥑 Жиры: {dish_record.get('fats', 'N/A')}\n"
        f"🍞 Углеводы: {dish_record.get('carbohydrates', 'N/A')}\n"
        f"⚖️ Вес: {dish_record.get('weight', 'N/A')}\n\n"
        f"📖 *Описание:*\n{dish_record['description'][:1000]}"
    )
    photo_path = dish_record["image_url"]

    if os.path.exists(photo_path) and os.path.isfile(photo_path):
        photo = FSInputFile(photo_path)
        await message.answer_photo(photo=photo, caption=dish_text, parse_mode="Markdown")
    else:
        await message.answer(dish_text, parse_mode="Markdown")


# Обработчик выбора категории
@dp.message()
async def handle_category_selection(message: Message):
    category = message.text
    async with db_pool.acquire() as db:
        dishes = await db.fetch("SELECT id, name FROM menu_items WHERE category = $1", category)

    if not dishes:
        await message.answer("❌ Категория не найдена. Попробуйте снова.")
        return

    inline_kb = await get_dishes_inline_keyboard(category)
    await message.answer(f"🍽 Меню категории *{category}*:", reply_markup=inline_kb, parse_mode="Markdown")


# Обработчик выбора блюда
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


# Кнопка "Назад"
@dp.callback_query(lambda c: c.data == "back_to_categories")
async def back_callback_handler(callback: types.CallbackQuery):
    keyboard = await get_categories_keyboard()
    await callback.message.answer("📜 Выберите категорию:", reply_markup=keyboard)
    await callback.answer()


# Запуск бота
async def start_bot():
    await connect_db()
    await set_main_menu()
    await dp.start_polling(bot)


# Запуск парсера и бота
async def main():
    # Запускаем парсер в фоне
    asyncio.create_task(periodic_parser())
    await start_bot()


if __name__ == "__main__":
    asyncio.run(main())