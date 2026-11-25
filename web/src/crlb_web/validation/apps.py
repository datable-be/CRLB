"""The validation app: review pages and decisions on the results of crlb."""

from django.apps import AppConfig


class ValidationConfig(AppConfig):
    """Configuration of the validation app."""

    name = "crlb_web.validation"
    label = "validation"
    verbose_name = "Validation"
