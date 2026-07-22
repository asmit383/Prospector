from abc import ABC, abstractmethod

from models.job import Job


class BaseSource(ABC):
    """Every source fetches raw data and normalizes it into a list[Job].

    Keep each source self-contained: if it raises, main.py should log and
    continue with the other sources (source isolation principle).
    """

    name: str  # short id, e.g. "hn", "remoteok" — also used in Job.source

    @abstractmethod
    def fetch(self) -> list[Job]:
        """Hit the API/feed and return normalized Job objects."""
        ...
