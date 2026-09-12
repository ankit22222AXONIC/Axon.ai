"""AXON application state."""

from enum import Enum


class AxonStatus(Enum):
    INITIALIZING = "initializing"
    READY = "ready"
    RUNNING = "running"
    SHUTTING_DOWN = "shutting_down"
    STOPPED = "stopped"


class State:
    def __init__(self):
        self.status = AxonStatus.INITIALIZING

    def set(self, status: AxonStatus):
        self.status = status

    def __repr__(self):
        return f"State({self.status.value})"
