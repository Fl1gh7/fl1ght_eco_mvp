import sys
import os

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from services.scouts.scout_vk import run_vk_scout

print("Ставлю run_vk_scout в очередь Celery...")
result = run_vk_scout.delay()
print(f"Task ID: {result.id}")
