"""Repositories package for data access layer."""

from backend.app.repositories.base import BaseRepository
from backend.app.repositories.company import CompanyRepository
from backend.app.repositories.contact import ContactRepository
from backend.app.repositories.credit import CreditRepository
from backend.app.repositories.job import JobRepository

__all__ = [
    "BaseRepository",
    "CompanyRepository",
    "JobRepository",
    "ContactRepository",
    "CreditRepository",
]
