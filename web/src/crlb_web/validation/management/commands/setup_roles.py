"""Create or update the groups of the roles: Viewer, Commenter and Reviewer."""

from typing import Any

from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand

SECTIONS = ("objects", "references", "provenance", "normalisation")
ROLES = {
    "Viewer": [],
    "Commenter": ["remark"],
    "Reviewer": ["remark", *(f"review_{s}" for s in SECTIONS)],
}


class Command(BaseCommand):
    """Create the role groups with their permissions; running it again resets them."""

    help = __doc__

    def handle(self, *args: Any, **options: Any) -> None:
        """Create or update each group."""
        for name, codenames in ROLES.items():
            group, _ = Group.objects.get_or_create(name=name)
            group.permissions.set(
                Permission.objects.filter(
                    content_type__app_label="validation", codename__in=codenames
                )
            )
            self.stdout.write(f"{name}: {len(codenames)} permissions")
