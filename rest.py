import logging
import json
import requests
import asyncpg
from bs4 import BeautifulSoup
import asyncio
from config import DB_CONFIG_2  # Импортируем параметры подключения из config.py

# Настройка логирования
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Константы
BASE_URL = "https://coffeemania.ru"
REST_URL = f"{BASE_URL}/restaurants"


def fetch_restaurant_data(url):
    """
    Получает данные ресторана по переданному URL.
    """
    try:
        page = requests.get(url)
        page.raise_for_status()
        soup = BeautifulSoup(page.text, "html.parser")

        # Извлечение JSON-данных из тега <script id="__NEXT_DATA__">
        script_tag = soup.find('script', id='__NEXT_DATA__')
        json_data = script_tag.string
        dat = json.loads(json_data)
        restaurant_id = dat['props']['pageProps']['restaurant']['inner-id']

        # Извлечение описания ресторана
        descriptions = soup.find("div", class_="styles__AboutContent-sc-1q087s8-26 kcNVuQ")
        description_text = descriptions.get_text(strip=True) if descriptions else "Нет описания"

        # Извлечение дополнительной информации
        extra_info = soup.find_all("div", class_="styles__ExtraInfoItemText-sc-1q087s8-23 KvPwL")
        veranda = extra_info[0].get_text(strip=True) if len(extra_info) > 0 else "Без летней веранды"
        changing_table = dat['props']['pageProps']['restaurant']['changing-tables']
        animation = extra_info[2].get_text(strip=True) if len(extra_info) > 2 else "Без детской анимации"

        # Извлечение адреса
        address = dat['props']['pageProps']['restaurant']['address']

        # Извлечение информации о винной карте
        vine = soup.find("a", class_='underline', attrs={"rel": "noopener noreferrer"})
        vine_text = vine.get_text(strip=True) if vine else ""
        vine_url = vine['href'] if vine else ""

        # Извлечение изображения ресторана
        restaurant_img = soup.find('img', {'itemprop': 'contentUrl'})
        img_url = restaurant_img["src"] if restaurant_img else None

        # Извлечение информации о метро, времени работы и контактах
        metro = dat['props']['pageProps']['restaurant']['metro']
        work_time = str(dat['props']['pageProps']['restaurant']['working-hours']).replace("[", "").replace("]", "")
        contacts = dat['props']['pageProps']['restaurant']['phone']

        # Извлечение ссылки на меню ресторана
        restaurant_menu = soup.find("a", string="Смотреть меню")
        menu_url = restaurant_menu['href'] if restaurant_menu else "Нет меню"

        data = {
            "id": restaurant_id,
            # Имя ресторана будет добавлено отдельно при сборе общего списка
            "address": address,
            "restaurant_img": img_url,
            "metro": metro,
            "description": description_text,
            "veranda": veranda,
            "changing_table": changing_table,
            "animation": animation,
            "work_time": work_time,
            "contacts": contacts,
            "vine": vine_text,
            "vine_url": vine_url,
            "restaurant_menu": menu_url,
        }
        return data

    except requests.RequestException as e:
        logging.error(f"Ошибка при запросе {url}: {e}")
        return None


def fetch_all_restaurants():
    """
    Получает список всех ресторанов.
    Возвращает словарь, где ключ – название ресторана, а значение – URL.
    """
    page = requests.get(REST_URL)
    soup = BeautifulSoup(page.text, "html.parser")
    all_rests = soup.find_all("a", class_="image-side")
    restaurants = {}

    for rest in all_rests:
        rest_name = rest.find("img").get("title")
        rest_url = BASE_URL + rest.get("href")
        restaurants[rest_name] = rest_url

    # Исключаем ресторан "Кофемания Chef's", если он не нужен
    restaurants.pop("Кофемания Chef's", None)
    return restaurants
async def save_restaurants_to_db(db_pool, restaurants: list):
    if not restaurants:
        return {}

    query = """
        INSERT INTO restaurants_db 
            (restaurant_id, name, address, restaurant_image, metro, description, veranda, changing_table, animation, work_time, contacts, vine_card)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
        ON CONFLICT (restaurant_id) DO UPDATE 
        SET name = EXCLUDED.name,
            address = EXCLUDED.address,
            restaurant_image = EXCLUDED.restaurant_image,
            metro = EXCLUDED.metro,
            description = EXCLUDED.description,
            veranda = EXCLUDED.veranda,
            changing_table = EXCLUDED.changing_table,
            animation = EXCLUDED.animation,
            work_time = EXCLUDED.work_time,
            contacts = EXCLUDED.contacts,
            vine_card = EXCLUDED.vine_card;
    """

    params_list = []
    links_dict = {}

    for restaurant in restaurants:
        restaurant_id = restaurant.get("id")
        if not restaurant_id:
            logging.warning(f"Пропускаем ресторан без ID: {restaurant.get('name', 'Без названия')}")
            continue

        name = restaurant.get("name", "Без названия")
        address = restaurant.get("address", "Нет адреса")
        restaurant_image = restaurant.get("restaurant_img", "Нет изображения")
        metro = restaurant.get("metro", "Нет данных о метро")
        description = restaurant.get("description", "Нет описания")
        veranda = restaurant.get("veranda", "Без летней веранды")
        changing_table = restaurant.get("changing_table", "Нет данных")
        animation = restaurant.get("animation", "Нет анимации")
        work_time = restaurant.get("work_time", "Нет данных о времени работы")
        contacts = restaurant.get("contacts", "Нет контактов")
        vine_card = restaurant.get("vine", "Нет данных о винной карте")

        params_list.append((
            restaurant_id,
            name,
            address,
            restaurant_image,
            metro,
            description,
            veranda,
            changing_table,
            animation,
            work_time,
            contacts,
            vine_card
        ))

        # Сохраняем ссылки отдельно, используя id ресторана в качестве ключа
        restaurant_menu_link = restaurant.get("restaurant_menu", "Нет меню")
        wine_card_link = restaurant.get("vine_url", "Нет винной карты")
        links_dict[restaurant_id] = {
            "restaurant_menu": restaurant_menu_link,
            "wine_card": wine_card_link
        }

    async with db_pool.acquire() as conn:
        await conn.executemany(query, params_list)

    return links_dict


async def main(db_pool):
    # Получаем список ресторанов
    restaurants_dict = fetch_all_restaurants()
    restaurant_data_list = []

    for name, url in restaurants_dict.items():
        data = fetch_restaurant_data(url)
        if data:
            # Добавляем имя ресторана, так как его нет в данных, полученных из fetch_restaurant_data
            data["name"] = name
            restaurant_data_list.append(data)
            logging.info(f"Получены данные ресторана: {name}")