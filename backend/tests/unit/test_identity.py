"""Reguły entity resolution — najdroższy błąd to fałszywe scalenie osób."""

from __future__ import annotations

from business_osint.domain.enums import IdentifierScheme
from business_osint.domain.identity import (
    CandidateFeatures,
    MatchDecision,
    resolve_by_identifier,
    score_company_pair,
    score_person_pair,
)


def test_identical_names_alone_never_auto_merge_people() -> None:
    """Dwóch Janów Kowalskich bez dodatkowego sygnału to NIE ta sama osoba."""
    result = score_person_pair(CandidateFeatures(name_similarity=1.0))
    assert result.decision is not MatchDecision.MATCH
    assert result.decision is MatchDecision.NO_MATCH


def test_name_plus_birth_year_plus_shared_company_reaches_review_or_match() -> None:
    result = score_person_pair(
        CandidateFeatures(
            name_similarity=1.0, same_birth_year=True, same_address=True, shared_company_count=2
        )
    )
    assert result.decision is MatchDecision.MATCH


def test_weak_signals_land_in_review_queue() -> None:
    result = score_person_pair(CandidateFeatures(name_similarity=1.0, same_birth_year=True))
    assert result.decision is MatchDecision.REVIEW


def test_hard_identifier_wins_over_everything() -> None:
    index = {(IdentifierScheme.NIP, "5252445172"): "entity-1"}
    assert resolve_by_identifier({IdentifierScheme.NIP: "5252445172"}, index) == "entity-1"
    assert resolve_by_identifier({IdentifierScheme.NIP: "0000000000"}, index) is None


def test_company_legal_form_difference_is_not_a_difference() -> None:
    result = score_company_pair(
        "ALFA TECHNOLOGIE Sp. z o.o.", "ALFA TECHNOLOGIE SPÓŁKA Z OGRANICZONĄ ODPOWIEDZIALNOŚCIĄ"
    )
    assert result.decision is MatchDecision.MATCH


def test_different_companies_do_not_match() -> None:
    result = score_company_pair("ALFA TECHNOLOGIE Sp. z o.o.", "BETA LOGISTYKA Sp. z o.o.")
    assert result.decision is MatchDecision.NO_MATCH


def test_similarity_of_empty_string_is_zero() -> None:
    """Pusta nazwa nie może przypadkiem dopasować się do czegokolwiek."""
    from business_osint.domain.identity import string_similarity

    assert string_similarity("", "alfa") == 0.0
    assert string_similarity("alfa", "") == 0.0


def test_same_address_raises_company_score() -> None:
    """Wspólny adres to sygnał wspierający — ale nie tworzy dopasowania sam z siebie."""
    without = score_company_pair("ALFA TECHNOLOGIE Sp. z o.o.", "ALFA TECHNOLOGIA Sp. z o.o.")
    with_address = score_company_pair(
        "ALFA TECHNOLOGIE Sp. z o.o.", "ALFA TECHNOLOGIA Sp. z o.o.", same_address=True
    )
    assert with_address.score > without.score
    assert "same_address" in with_address.reasons


def test_person_display_name_handles_missing_first_names() -> None:
    from business_osint.domain.identity import person_display_name

    assert person_display_name("Jan", "Kowalski") == "Jan Kowalski"
    assert person_display_name("", "Kowalski") == "Kowalski"


def test_candidate_key_is_stable_and_normalized() -> None:
    from business_osint.domain.identity import candidate_key

    assert candidate_key("person", "Michał", "Wójcik") == "person:michal|wojcik"
    # Puste człony nie tworzą pustych segmentów klucza.
    assert candidate_key("person", "Jan", "") == "person:jan"
