from abc import abstractmethod
from typing import Optional, TypeVar

from pyspark.sql import DataFrame

from ..core import BaseComponent, Registry


class BaseConsumer(BaseComponent):
    @abstractmethod
    def consume(self, df: DataFrame, batch_id: Optional[int] = None) -> None:
        pass


_consumer_registry = Registry[BaseConsumer]()
T = TypeVar('T', bound='BaseConsumer')


def consumer(t: type[T]) -> type[T]:
    _consumer_registry[t.__name__] = t
    return t
