"""The command line of the validation interface (Django's manage.py as the `crlb-web` script)."""

import os
import sys

from django.core.management import execute_from_command_line


def main() -> None:
    """Run a Django management command with the settings of the validation interface."""
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "crlb_web.settings")
    execute_from_command_line(sys.argv)
