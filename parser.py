import asyncio
import aiohttp
import logging
import random
import os
from menu_items import menu_urls
from bs4 import BeautifulSoup

BASE_URL = "https://coffeemania.ru"

# Настройка логирования
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Асинхронная функция запроса с повторными попытками и рандомной задержкой (анти-бан)
async def fetch(url, session, retries=3, delay_range=(1, 3)):
    for attempt in range(retries):
        try:
            # Рандомная задержка перед запросом
            delay = random.uniform(*delay_range)
            await asyncio.sleep(delay)
            async with session.get(url, timeout=10) as response:
                if response.status == 200:
                    return await response.text()
                else:
                    logging.error(f"Ошибка {response.status} при запросе {url}")
        except Exception as e:
            logging.exception(f"Exception при запросе {url}: {e}")
        logging.info(f"🔄 Повтор запроса {url} (попытка {attempt + 1}/{retries})")
    return None


# Асинхронная функция скачивания изображения (без обработки SVG)
async def download_image(img_url, session, category, dish_name):
    if not img_url or img_url == "Нет фото":
        return "Нет фото"
    try:
        async with session.get(img_url, timeout=10) as response:
            if response.status != 200:
                logging.error(f"Не удалось скачать изображение {img_url} (статус {response.status})")
                return img_url
            img_bytes = await response.read()
    except Exception as e:
        logging.exception(f"Exception при скачивании изображения {img_url}: {e}")
        return img_url

    # Создаём директорию для изображений
    dir_path = os.path.join("images", category)
    os.makedirs(dir_path, exist_ok=True)

    # Формируем безопасное имя файла
    safe_dish_name = "".join(c for c in dish_name if c.isalnum() or c in " _-").strip()
    file_extension = os.path.splitext(img_url)[1].lower() if '.' in img_url else '.jpg'
    output_path = os.path.join(dir_path, f"{safe_dish_name}{file_extension}")

    try:
        with open(output_path, "wb") as f:
            f.write(img_bytes)
        return output_path
    except Exception as e:
        logging.exception(f"Ошибка при сохранении изображения {img_url}: {e}")
        return img_url


# Асинхронная функция парсинга страницы блюда
async def parse_dish(url, session, category, semaphore):
    async with semaphore:
        html = await fetch(url, session)
        if html is None:
            logging.error(f"Не удалось получить данные со страницы {url}")
            return None

        try:
            soup = BeautifulSoup(html, "html.parser")
            item_info = soup.find("div", id="itemInfo")
            if not item_info:
                logging.error(f"Блок itemInfo не найден на {url}")
                return None

            # Извлекаем название и описание
            name_tag = item_info.find("h1", class_="itemTitle")
            name = name_tag.text.strip() if name_tag else "Нет названия"
            description_tag = item_info.find("div", class_="itemDesc")
            description = description_tag.text.strip() if description_tag else "Нет описания"

            # Извлекаем цену
            price_tag = item_info.find("div", class_="itemPrice")
            price = price_tag.text.strip() if price_tag else "Нет цены"

            # Извлекаем пищевую ценность
            nutrition_values = {}
            nutrition_section = item_info.find("div", class_="itemAboutValueContent")
            if nutrition_section:
                for stat in nutrition_section.find_all("div", class_="itemStat"):
                    key_tag = stat.find("span")
                    if key_tag:
                        key = key_tag.text.strip()
                        value = stat.text.replace(key, "").replace("\xa0", " ").strip()
                        nutrition_values[key] = value

            # Извлекаем состав
            composition = "Нет состава"
            composition_section = item_info.find("div", class_="itemAboutCompositionContent")
            if composition_section:
                composition_p = composition_section.find("p")
                if composition_p:
                    composition = composition_p.text.strip()

            # Извлекаем информацию об аллергенах
            allergens_section = item_info.find("p", style="font-style: italic")
            allergens = allergens_section.text.strip() if allergens_section else "Нет информации"

            # Извлекаем URL картинки:
            # Сначала ищем блок с изображениями (itemSlider)
            slider = soup.find("div", id="itemSlider")
            if slider:
                first_slide = slider.find("div", class_="itemSlide")
                if first_slide:
                    img_tag = first_slide.find("img", itemprop="contentUrl")
                    if img_tag and img_tag.has_attr("src"):
                        img_url = img_tag["src"]
                    else:
                        img_url = "Нет фото"
                else:
                    img_url = "Нет фото"
            else:
                # Если блока itemSlider нет, ищем картинку по старой логике
                img_tag = item_info.find("img")
                img_url = img_tag["src"] if img_tag and img_tag.has_attr("src") else "Нет фото"

            # Если это не "Нет фото" — проверяем расширение
            if img_url != "Нет фото":
                # Если URL содержит .svg, устанавливаем "Нет фото" (пропускаем)
                if img_url.lower().endswith(".svg"):
                    img_url = "Нет фото"
                elif not img_url.startswith("http"):
                    img_url = BASE_URL + img_url

            # Скачиваем (или пропускаем, если "Нет фото")
            processed_img = await download_image(img_url, session, category, name)
            return {
                "Название": name,
                "Цена": price,
                "Описание": description,
                "Пищевая ценность": nutrition_values,
                "Состав": composition,
                "Аллергены": allergens,
                "Фото": processed_img
            }
        except Exception as e:
            logging.exception(f"Ошибка при разборе страницы {url}: {e}")
            return None


# Основная асинхронная функция
async def main():
    parsed_menu = {}
    # Ограничение на количество одновременных запросов (анти-бан)
    semaphore = asyncio.Semaphore(5)

    # Отключаем проверку SSL-сертификата (не рекомендуется для production)
    connector = aiohttp.TCPConnector(ssl=False)

    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = []  # Список задач для каждого URL
        for category, content in menu_urls.items():
            parsed_menu[category] = {}
            logging.info(f"\n Парсим категорию: {category}")

            # Если это раздел "Напитки" (словарь с подгруппами)
            if isinstance(content, dict):
                for subcategory, urls in content.items():
                    parsed_menu[category][subcategory] = []
                    for url in urls:
                        task = asyncio.create_task(parse_dish(url, session, category, semaphore))
                        tasks.append((category, subcategory, task))
            # Если это обычная категория (список)
            else:
                parsed_menu[category] = []
                for url in content:
                    task = asyncio.create_task(parse_dish(url, session, category, semaphore))
                    tasks.append((category, None, task))

        # Ожидаем завершения всех задач
        for category, subcategory, task in tasks:
            dish = await task
            if dish:
                if subcategory:
                    parsed_menu[category][subcategory].append(dish)
                else:
                    parsed_menu[category].append(dish)

    # Читаемый вывод результатов
    for category, content in parsed_menu.items():
        print(f"\nКатегория: {category}")
        if isinstance(content, dict):  # Если это раздел "Напитки"
            for subcategory, dishes in content.items():
                print(f"\n Подкатегория: {subcategory}")
                for dish in dishes:
                    print(f"\nНазвание: {dish['Название']}")
                    print(f"Цена: {dish['Цена']}")
                    print(f"Описание: {dish['Описание']}")
                    print(" Пищевая ценность:")
                    for k, v in dish["Пищевая ценность"].items():
                        print(f" {k}: {v}")
                    print(f"Состав: {dish['Состав']}")
                    print(f"{dish['Аллергены']}")
                    print(f"Фото: {dish['Фото']}")
                    print("-" * 50)
        else:  # Если это обычная категория
            for dish in content:
                print(f"\nНазвание: {dish['Название']}")
                print(f"Цена: {dish['Цена']}")
                print(f"Описание: {dish['Описание']}")
                print(" Пищевая ценность:")
                for k, v in dish["Пищевая ценность"].items():
                    print(f"   {k}: {v}")
                print(f"Состав: {dish['Состав']}")
                print(f"{dish['Аллергены']}")
                print(f"Фото: {dish['Фото']}")
                print("-" * 50)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        logging.exception(f"Ошибка: {e}")