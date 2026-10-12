"""In-memory workspace branding repository."""

from ..models import BrandingRecord


class InMemoryBrandingRepository:
    def __init__(self) -> None:
        self.active: BrandingRecord | None = None

    def get_active(self) -> BrandingRecord | None:
        return self.active

    def save_active(self, record: BrandingRecord) -> BrandingRecord:
        self.active = record
        return record

    def delete_active(self) -> None:
        self.active = None
