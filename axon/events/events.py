"""AXON event system."""

from dataclasses import dataclass, field
from datetime import datetime
from collections import defaultdict


@dataclass
class Event:
    name: str
    data: dict = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)


class EventBus:
    def __init__(self):
        self._listeners = defaultdict(list)

    def on(self, event_name: str, callback):
        self._listeners[event_name].append(callback)

    def off(self, event_name: str, callback):
        if callback in self._listeners.get(event_name, []):
            self._listeners[event_name].remove(callback)

    def emit(self, event_name: str, data: dict = None):
        event = Event(name=event_name, data=data or {})
        for callback in self._listeners.get(event_name, []):
            callback(event)
        return event
