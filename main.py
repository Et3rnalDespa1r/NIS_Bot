from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import Message

BOT_TOKEN = '7810815969:AAGGOmJMZWC45WenKK4VuJAakEH9HfnpMyw'

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


@dp.message(Command(commands=["start"]))
async def process_start_command(message: Message):
    await message.answer("☕ Привет! Добро пожаловать в Coffeemania — твой проводник в гастрономический рай!"
                        "Давай пройдем быструю регистрацию и приступим!")
if __name__ == '__main__':
    dp.run_polling(bot)
