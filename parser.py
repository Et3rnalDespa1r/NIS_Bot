import asyncio
import aiohttp
import asyncpg
import logging
import random
import os
import re
import jso
import aiofilesn
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
from config import DB_CONFIG, BASE_URL

MENU_URL = f"{BASE_URL}/menu"

MAX_CONCURRENT_REQUESTS = 20
FETCH_DELAY_RANGE = (0.01, 0.02)
SCROLL_PAUSE_TIME = 0
MAX_SCROLLS = 20

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")



def clean_text(text: str) -> str:
    if not text:
        return ""
    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def parse_price(raw_price: str) -> str:
    raw_price = clean_text(raw_price)
    raw_price = re.sub(r"\s*₽", " ₽", raw_price)
    return raw_price


def parse_calories(cal_str: str) -> int:
    cal_str = clean_text(cal_str)
    try:
        return int(cal_str)
    except ValueError:
        match = re.search(r"\d+", cal_str)
        return int(match.group(0)) if match else 0

async def scroll_to_bottom(page, pause_time: float = SCROLL_PAUSE_TIME, max_scrolls: int = MAX_SCROLLS):
    last_height = await page.evaluate("document.body.scrollHeight")
    scrolls = 0
    while True:
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight);")
        await asyncio.sleep(pause_time)
        new_height = await page.evaluate("document.body.scrollHeight")
        if new_height == last_height:
            break
        last_height = new_height
        scrolls += 1
        if scrolls >= max_scrolls:
            logging.info(f"Достигли лимита скроллов ({max_scrolls}).")
            break


async def get_categories_and_dishes(page, url: str) -> dict:
    logging.info(f"Переходим на страницу: {url}")
    await page.goto(url, timeout=60000, wait_until="domcontentloaded")
    await asyncio.sleep(1)
    await scroll_to_bottom(page)

    content = await page.content()
    soup = BeautifulSoup(content, "html.parser")
    categories = {}

    for cat_container in soup.select(".deliveryCategoryBlockWrapper.deliveryCategoryContainer"):
        cat_title = cat_container.get("data-title", "Неизвестная категория").strip()
        dish_links = []
        for a in cat_container.find_all("a", href=True):
            href = a["href"]
            if "/menu/" in href:
                if not href.startswith("http"):
                    href = BASE_URL + href
                dish_links.append(href)
        dish_links = list(set(dish_links))
        if dish_links:
            categories[cat_title] = dish_links

    return categories


async def fetch(url, session, retries=3, delay_range=FETCH_DELAY_RANGE):

    for attempt in range(retries):
        try:
            delay = random.uniform(*delay_range)
            await asyncio.sleep(delay)
            async with session.get(url, timeout=10) as response:
                if response.status == 200:
                    return await response.text()
                else:
                    logging.error(f"Ошибка {response.status} при запросе {url}")
        except Exception as E:
            logging.exception(f"Exception при запросе {url}: {E}")
        logging.info(f"Повтор запроса {url} (попытка {attempt + 1}/{retries})")
    return None


async def download_image(img_url, session, category, dish_name):
    if not img_url or img_url == "Нет фото":
        return "Нет фото"
    safe_dish_name = "".join(c for c in dish_name if c.isalnum() or c in " _-").strip()
    file_extension = os.path.splitext(img_url)[1].lower() if '.' in img_url else '.jpg'
    dir_path = os.path.join("images", category)
    os.makedirs(dir_path, exist_ok=True)
    output_path = os.path.join(dir_path, f"{safe_dish_name}{file_extension}")

    if os.path.exists(output_path):
        logging.info(f"Изображение уже существует: {output_path}")
        return output_path

    try:
        async with session.get(img_url, timeout=10) as response:
            if response.status != 200:
                logging.error(f"Не удалось скачать изображение {img_url} (статус {response.status})")
                return img_url
            img_bytes = await response.read()
    except Exception as E:
        logging.exception(f"Exception при скачивании изображения {img_url}: {E}")
        return img_url

    try:
        async with aiofiles.open(output_path, "wb") as f:
            await f.write(img_bytes)
        return output_path
    except Exception as E:
        logging.exception(f"Ошибка при сохранении изображения {img_url}: {E}")
        return img_url


async def parse_dish(url, session, category, semaphore):
    async with semaphore:
        html = await fetch(url, session)
        if html is None:
            logging.error(f"Не удалось получить данные со страницы {url}")
            return None

        try:
            soup = BeautifulSoup(html, "html.parser")

            sku = None
            script_tag = soup.find("script", type="application/ld+json")
            if script_tag:
                try:
                    data = json.loads(script_tag.string)
                    if isinstance(data, dict) and data.get("@type") == "Product":
                        sku = int(data.get("sku"))
                except Exception as e:
                    logging.warning(f"Ошибка парсинга JSON-LD для SKU на {url}: {e}")

            item_info = soup.find("div", id="itemInfo")
            if not item_info:
                logging.error(f"Блок itemInfo не найден на {url}")
                return None

            name_tag = item_info.find("h1", class_="itemTitle")
            name = clean_text(name_tag.text) if name_tag else "Нет названия"

            description_tag = item_info.find("div", class_="itemDesc")
            description = clean_text(description_tag.text) if description_tag else "Нет описания"

            price_tag = item_info.find("div", class_="itemPrice")
            if price_tag:
                raw_price = price_tag.get_text(strip=True)
                price = parse_price(raw_price)
            else:
                price = "Нет цены"

            nutrition_values = {}
            nutrition_section = item_info.find("div", class_="itemAboutValueContent")
            if nutrition_section:
                for stat in nutrition_section.find_all("div", class_="itemStat"):
                    key_tag = stat.find("span")
                    if key_tag:
                        key = clean_text(key_tag.text)
                        value = stat.text.replace(key, "")
                        value = clean_text(value)
                        nutrition_values[key] = value

            composition = "Нет состава"
            composition_section = item_info.find("div", class_="itemAboutCompositionContent")
            if composition_section:
                composition_p = composition_section.find("p")
                if composition_p:
                    composition = clean_text(composition_p.text)

            allergens_section = item_info.find("p", style="font-style: italic")
            allergens = clean_text(allergens_section.text) if allergens_section else "Нет информации"

            img_url = "Нет фото"

            item_image_div = soup.find("div", id="itemImage")
            if item_image_div:
                img_tag = item_image_div.find("img", itemprop="contentUrl")
                if img_tag and img_tag.has_attr("src"):
                    img_url = img_tag["src"]

            if img_url == "Нет фото":
                slider = soup.find("div", id="itemSlider")
                if slider:
                    first_slide = slider.find("div", class_="itemSlide")
                    if first_slide:
                        img_tag = first_slide.find("img", itemprop="contentUrl")
                        if img_tag and img_tag.has_attr("src"):
                            img_url = img_tag["src"]

            if img_url != "Нет фото":
                if img_url.lower().endswith(".svg"):
                    img_url = "Нет фото"
                elif not img_url.startswith("http"):
                    img_url = BASE_URL + img_url

            processed_img = await download_image(img_url, session, category, name)

            time_label = soup.find("div", class_="timeLabel")
            timetable = time_label.get_text(strip=True) if time_label else ""

            return {
                "SKU": sku,
                "Категория": category,
                "Название": name,
                "Цена": price,
                "Описание": description,
                "Пищевая ценность": nutrition_values,
                "Состав": composition,
                "Аллергены": allergens,
                "Фото": processed_img,
                "В наличии": True,
                "TimeTable": timetable
            }
        except Exception as e:
            logging.exception(f"Ошибка при разборе страницы {url}: {e}")
            return None


async def save_dishes_to_db(db_pool, dishes: list):
    if not dishes:
        return

    query = """
        INSERT INTO menu_items 
            (id, category, name, price, calories, proteins, fats, carbohydrates, weight, 
             description, composition, allergens, image_url, availability, timetable)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15)
        ON CONFLICT (id, category) DO UPDATE 
        SET name = EXCLUDED.name,
            price = EXCLUDED.price,
            calories = EXCLUDED.calories,
            proteins = EXCLUDED.proteins,
            fats = EXCLUDED.fats,
            carbohydrates = EXCLUDED.carbohydrates,
            weight = EXCLUDED.weight,
            description = EXCLUDED.description,
            composition = EXCLUDED.composition,
            allergens = EXCLUDED.allergens,
            image_url = EXCLUDED.image_url,
            availability = EXCLUDED.availability,
            timetable = EXCLUDED.timetable;
    """
    params_list = []
    for dish in dishes:
        sku = dish.get("SKU")
        if not sku:
            logging.warning(f"Пропускаем блюдо без SKU: {dish.get('Название')}")
            continue
        category = dish.get("Категория", "Меню")
        name = dish.get("Название", "Нет названия")
        price = dish.get("Цена", "Нет цены")
        description = dish.get("Описание", "Нет описания")
        composition = dish.get("Состав", "Нет состава")
        allergens = dish.get("Аллергены", "Нет информации")
        img_url = dish.get("Фото", "Нет фото")
        availability = dish.get("В наличии", True)
        nutrition = dish.get("Пищевая ценность", {})
        calories = parse_calories(nutrition.get("Ккал", "0"))
        proteins = nutrition.get("Белки", "Нет данных")
        fats = nutrition.get("Жиры", "Нет данных")
        carbs = nutrition.get("Углеводы", "Нет данных")
        weight = nutrition.get("Вес", "Нет данных")
        timetable = dish.get("TimeTable", "Нет данных")
        params_list.append((sku, category, name, price, calories,
                            proteins, fats, carbs, weight,
                            description, composition, allergens, img_url, availability, timetable))
    async with db_pool.acquire() as conn:
        await conn.executemany(query, params_list)


async def main():
    parsed_menu = {}

    async with async_playwright() as p:
        logging.info("Запуск браузера Playwright для сбора категорий...")
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()
        categories_dict = await get_categories_and_dishes(page, MENU_URL)
        await page.close()
        await browser.close()
        logging.info("Получены категории и ссылки:")
        for cat, links in categories_dict.items():
            logging.info(f"{cat}: {links}")

    for category in categories_dict:
        parsed_menu[category] = []

    semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)
    connector = aiohttp.TCPConnector(ssl=False)
    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = []
        for category, urls in categories_dict.items():
            for url in urls:
                tasks.append(parse_dish(url, session, category, semaphore))
        results = await asyncio.gather(*tasks)
        for dish in results:
            if dish:
                parsed_menu[dish["Категория"]].append(dish)

    db_pool = await asyncpg.create_pool(**DB_CONFIG, min_size=1, max_size=10)
    for category, dishes in parsed_menu.items():
        await save_dishes_to_db(db_pool, dishes)

    async with db_pool.acquire() as conn:
        site_categories = list(parsed_menu.keys())
        if site_categories:
            await conn.execute("DELETE FROM menu_items WHERE category NOT IN (SELECT unnest($1::text[]))",
                               site_categories)
        for category, dishes in parsed_menu.items():
            site_skus = [dish["SKU"] for dish in dishes if dish.get("SKU")]
            if site_skus:
                await conn.execute(
                    "DELETE FROM menu_items WHERE category = $1 AND NOT (id = ANY($2::integer[]))",
                    category, site_skus
                )
            else:
                await conn.execute("DELETE FROM menu_items WHERE category = $1", category)

    logging.info("Синхронизация с сайтом завершена. Все блюда обновлены в базе данных.")
    await db_pool.close()


async def periodic_parser(interval=3600):
    while True:
        logging.info("Запуск цикла парсинга...")
        await main()
        logging.info(f"Ожидание {interval} секунд до следующего запуска...")
        await asyncio.sleep(interval)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        logging.exception(f"Ошибка: {e}")