"""Django models of the crlb tables that the admin shows; crlb owns their schema (managed = False)."""

from django.db import models

# The section of the entry page each reviewable table belongs to; a reviewer
# needs the section's permission (review_<section>) to accept, reject or correct
SECTIONS = {
    "ro_objects": "objects",
    "ro_object_identifiers": "objects",
    "ro_attributions": "objects",
    "ro_dimensions": "objects",
    "ro_related_objects": "objects",
    "ro_object_exhibitions": "references",
    "ro_object_sources": "references",
    "ro_collection_stays": "provenance",
    "ro_auctions": "provenance",
    "normalised_values": "normalisation",
}


class Review(models.Model):
    """A review decision (crlb table `reviews`, schema 06_review.sql)."""

    id = models.AutoField(primary_key=True)
    table_name = models.TextField()
    row_id = models.IntegerField()
    column_name = models.TextField(null=True)
    action = models.TextField()
    old_value = models.TextField(null=True)
    new_value = models.TextField(null=True)
    reviewer = models.TextField()
    reviewed_at = models.TextField()
    comment = models.TextField(null=True)
    first_word_id = models.IntegerField(null=True)
    last_word_id = models.IntegerField(null=True)

    class Meta:
        """Table and permissions; the permissions are the roles' building blocks."""

        managed = False
        db_table = "reviews"
        ordering = ("-id",)
        default_permissions = ("view",)
        permissions = (
            ("remark", "Can add remarks"),
            ("review_objects", "Can accept, reject and correct object data"),
            (
                "review_references",
                "Can accept, reject and correct exhibitions and literature",
            ),
            ("review_provenance", "Can accept, reject and correct provenance"),
            (
                "review_normalisation",
                "Can accept, reject and correct normalised values",
            ),
        )

    def __str__(self) -> str:
        """Return the decision in short."""
        return f"{self.action} {self.table_name} {self.row_id} by {self.reviewer}"
