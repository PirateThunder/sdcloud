from taskiq import TaskiqScheduler
from taskiq.schedule_sources import LabelScheduleSource
from taskiq_redis import ListQueueBroker, RedisAsyncResultBackend

from .config import get_settings
from .registry import import_models

import_models()

_connection = {"socket_timeout": None, "socket_connect_timeout": 5}
broker = ListQueueBroker(url=get_settings().redis_url, **_connection).with_result_backend(
    RedisAsyncResultBackend(redis_url=get_settings().redis_url, **_connection)
)
scheduler = TaskiqScheduler(broker=broker, sources=[LabelScheduleSource(broker)])
