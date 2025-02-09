from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.types import BotCommand
import asyncio
import parser

BOT_TOKEN = '7810815969:AAGGOmJMZWC45WenKK4VuJAakEH9HfnpMyw'

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


@dp.message(Command(commands=["start"]))
async def process_start_command(message: Message):
    await message.answer("☕ Привет! Добро пожаловать в Coffeemania — твой проводник в гастрономический рай!"
                        "Давай пройдем быструю регистрацию и приступим!")

async def set_main_menu(bot: Bot):

    main_menu_commands = [
        BotCommand(command='/menu',
                   description='Меню ресторана'),
        BotCommand(command='/restaurant',
                   description='Выбор ресторана'),
        BotCommand(command='/registration',
                   description='Регистрация по номеру телефона для новых посетителей'),
        BotCommand(command='/history',
                   description='История заказов')
    ]

    await bot.set_my_commands(main_menu_commands)

@dp.message(Command(commands=["menu"]))
async def process_start_command(message: Message):
    await message.answer("Пока эта функция не работает")

@dp.message(Command(commands=["restaurant"]))
async def process_start_command(message: Message):
    await message.answer("Пока эта функция не работает")

@dp.message(Command(commands=["history"]))
async def process_start_command(message: Message):
    await message.answer("Пока эта функция не работает")

@dp.message(Command(commands=["registration"]))
async def process_start_command(message: Message):
    await message.answer("Пока эта функция не работает")

if __name__ == '__main__':
    dp.run_polling(bot)
    asyncio.run(parser.main())