import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    YANDEX_API_KEY = os.getenv("YANDEX_API_KEY")
    YANDEX_FOLDER_ID = os.getenv("YANDEX_FOLDER_ID")


settings = Settings()

if not settings.YANDEX_API_KEY or not settings.YANDEX_FOLDER_ID:
    print("YANDEX_API_KEY / YANDEX_FOLDER_ID не заданы — нужен .env в корне репозитория")
