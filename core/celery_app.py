import os
import sys
from celery import Celery
from celery.schedules import crontab
from dotenv import load_dotenv

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, PROJECT_ROOT)
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

REDIS_URL = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")

celery_app = Celery(
    "service_flight_tasks",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=[
        "services.scouts.scout_vk",
        "services.scouts.group_finder",
        "services.scouts.tasks",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Europe/Moscow",
    enable_utc=True,
)

celery_app.autodiscover_tasks(["services.scouts"])

celery_app.conf.beat_schedule = {
    # Обход стен и комментариев VK.
    "run-vk-scout-every-2-hours": {
        "task": "services.scouts.scout_vk.run_vk_scout",
        "schedule": 120 * 60.0,
    },
    # Раз в неделю пересобираю список пабликов (вс 03:00 Europe/Moscow).
    "run-group-finder-weekly": {
        "task": "services.scouts.group_finder.run_finder",
        "schedule": crontab(hour=3, minute=0, day_of_week="sun"),
    },
}
