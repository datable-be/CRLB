"""Tests for the RKD entry instructions of step 5b."""

from crlb.enrichment.instructions import format_holder, last_first, simplify


def test_personal_names_as_last_first_with_particles_and_titles() -> None:
    """Particles follow the first names, titles of nobility too, forms of address go in brackets."""
    assert last_first("Frans van den Hecke") == "Hecke, Frans van den"
    assert (
        last_first("Jean François Joseph de Vinck de Wesel")
        == "Vinck de Wesel, Jean François Joseph de"
    )
    assert last_first("baron Ferdinand du Bois") == "Bois, Ferdinand du baron"
    assert (
        last_first("Sir William Stirling-Maxwell") == "Stirling-Maxwell, William (Sir)"
    )
    assert last_first("Dr. Schieffer") == "Schieffer (Dr)"


def test_holders_are_formatted_only_when_they_name_a_person() -> None:
    """Life dates are left out; institutions, buildings and two people stay as written."""
    assert (
        format_holder("Adelaide Milton de Groot (1876–1967)").value
        == "Groot, Adelaide Milton de"
    )
    assert format_holder("A.J. van Woerkum").value == "Woerkum, A.J. van"
    for text in (
        "The Metropolitan Museum of Art",
        "Casa de Campo",
        "Trier and Karl Nathan",
        "Noë",
    ):
        assert format_holder(text).value == text
        assert format_holder(text).rule is None


def test_unnamed_owners_get_the_rkd_terms() -> None:
    """Private collection, Art dealer and Whereabouts unknown, as the manual prescribes."""
    assert format_holder("private collection").value == "Private collection"
    assert format_holder("art market Vienna").value == "Art dealer"
    assert format_holder("whereabouts unknown").value == "Whereabouts unknown"


def test_simplified_forms_ignore_case_accents_punctuation_and_articles() -> None:
    """'The Metropolitan Museum of Art' and RKD's 'Metropolitan Museum of Art, The' compare equal."""
    assert simplify("The Metropolitan Museum of Art") == simplify(
        "Metropolitan Museum of Art, The"
    )
    assert simplify("Féral (1767–1848)") == "feral"
