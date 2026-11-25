"""The admin: users and groups (Django's own), and the review log, read-only."""

from django.contrib import admin
from django.http import HttpRequest

from crlb_web.validation.models import Review


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    """The review log: every decision, filterable, never changed here."""

    list_display = (
        "reviewed_at",
        "reviewer",
        "action",
        "table_name",
        "row_id",
        "column_name",
        "new_value",
        "comment",
    )
    list_filter = ("action", "reviewer", "table_name")
    search_fields = ("comment", "new_value", "old_value")
    date_hierarchy = None

    def has_add_permission(self, request: HttpRequest) -> bool:
        """Decisions are made on the entry pages only."""
        return False

    def has_change_permission(
        self, request: HttpRequest, obj: Review | None = None
    ) -> bool:
        """Decisions are never changed."""
        return False

    def has_delete_permission(
        self, request: HttpRequest, obj: Review | None = None
    ) -> bool:
        """Decisions are never deleted."""
        return False
