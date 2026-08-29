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
    result = score_person_pair(
        CandidateFeatures(name_similarity=1.0, same_birth_year=True)
    )
    assert result.decision is MatchDecision.REVIEW


def test_hard_identifier_wins_over_everything() -> None:
    index = {(IdentifierScheme.NIP, "5252445172"): "entity-1"}
    assert (
        resolve_by_identifier({IdentifierScheme.NIP: "5252445172"}, index) == "entity-1"
    )
    assert resolve_by_identifier({IdentifierScheme.NIP: "0000000000"}, index) is None


def test_company_legal_form_difference_is_not_a_difference() -> None:
    result = score_company_pair(
        "ALFA TECHNOLOGIE Sp. z o.o.", "ALFA TECHNOLOGIE SPÓŁKA Z OGRANICZONĄ ODPOWIEDZIALNOŚCIĄ"
    )
    assert result.decision is MatchDecision.MATCH


def test_different_companies_do_not_match() -> None:
    result = score_company_pair("ALFA TECHNOLOGIE Sp. z o.o.", "BETA LOGISTYKA Sp. z o.o.")
    assert result.decision is MatchDecision.NO_MATCH
