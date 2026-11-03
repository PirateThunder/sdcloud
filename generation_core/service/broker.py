from taskiq_redis import ListQueueBroker, RedisAsyncResultBackend

from .config import get_settings

_connection_kwargs = {"socket_timeout": None, "socket_connect_timeout": 5}

broker = ListQueueBroker(url=get_settings().redis_url, **_connection_kwargs).with_result_backend(
    RedisAsyncResultBackend(redis_url=get_settings().redis_url, **_connection_kwargs)
)
