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


# --- luki wykryte przez testy mutacyjne (`make mutation`) -------------------


def test_decision_thresholds_are_inclusive() -> None:
    """Wynik dokładnie na progu ma kwalifikować się do wyższej kategorii.

    Progi są regułą biznesową, nie szczegółem implementacji: przesunięcie
    o jeden krok w prawo zmienia decyzję dla par leżących dokładnie na granicy.
    """
    from business_osint.domain.identity import (
        MATCH_THRESHOLD,
        REVIEW_THRESHOLD,
        _decide,
    )

    assert _decide(MATCH_THRESHOLD, ()).decision is MatchDecision.MATCH
    assert _decide(REVIEW_THRESHOLD, ()).decision is MatchDecision.REVIEW
    assert _decide(REVIEW_THRESHOLD - 0.0001, ()).decision is MatchDecision.NO_MATCH


def test_score_is_rounded_to_four_decimals() -> None:
    from business_osint.domain.identity import _decide

    assert _decide(0.123456789, ()).score == 0.1235


def test_company_score_never_exceeds_one() -> None:
    """Premia za wspólny adres nie może wypchnąć wyniku poza skalę."""
    result = score_company_pair("ALFA Sp. z o.o.", "ALFA Sp. z o.o.", same_address=True)
    assert result.score == 1.0


def test_company_address_bonus_is_exactly_five_hundredths() -> None:
    """Wspólny adres podbija wynik o 0.05 — nie jest samodzielnym dowodem."""
    plain = score_company_pair("ALFA TECHNOLOGIE", "ALFA TECHNOLOGIA")
    boosted = score_company_pair("ALFA TECHNOLOGIE", "ALFA TECHNOLOGIA", same_address=True)
    assert boosted.score == round(plain.score + 0.05, 4)


def test_single_shared_company_scores_below_the_cap() -> None:
    """Jedna wspólna spółka to słaby sygnał — nie może ważyć tyle, co dwie."""
    one = score_person_pair(CandidateFeatures(name_similarity=0.0, shared_company_count=1))
    assert one.score == 0.05


def test_shared_companies_bonus_is_capped() -> None:
    """Dziesięć wspólnych spółek nie może ważyć więcej niż dwie — inaczej
    jeden hub (np. syndyk) scalałby przypadkowe osoby."""
    two = score_person_pair(CandidateFeatures(name_similarity=0.0, shared_company_count=2))
    ten = score_person_pair(CandidateFeatures(name_similarity=0.0, shared_company_count=10))
    assert two.score == 0.10
    assert ten.score == 0.10


def test_feature_weights_are_pinned() -> None:
    """Wagi cech są kontraktem — ich zmiana przesuwa granicę scalania osób."""
    assert score_person_pair(CandidateFeatures(name_similarity=1.0)).score == 0.70
    assert (
        score_person_pair(CandidateFeatures(name_similarity=1.0, same_birth_year=True)).score
        == 0.85
    )
    assert (
        score_person_pair(
            CandidateFeatures(name_similarity=1.0, same_birth_year=True, same_address=True)
        ).score
        == 0.95
    )


def test_person_score_never_exceeds_one() -> None:
    result = score_person_pair(
        CandidateFeatures(
            name_similarity=1.0,
            same_birth_year=True,
            same_address=True,
            shared_company_count=5,
        )
    )
    assert result.score == 1.0


def test_reasons_name_the_signals_that_fired() -> None:
    """Uzasadnienie trafia do kolejki przeglądu — człowiek musi wiedzieć, na
    czym oparto propozycję scalenia."""
    result = score_person_pair(
        CandidateFeatures(name_similarity=1.0, same_birth_year=True, shared_company_count=1)
    )
    assert result.reasons == ("name_similarity=1.00", "same_birth_year", "shared_companies=1")


def test_reasons_include_address_signal_verbatim() -> None:
    """Nazwy sygnałów trafiają do interfejsu kolejki przeglądu — są kontraktem."""
    result = score_person_pair(CandidateFeatures(name_similarity=1.0, same_address=True))
    assert result.reasons == ("name_similarity=1.00", "same_address")


def test_company_reasons_mention_address_only_when_used() -> None:
    without = score_company_pair("ALFA", "BETA")
    with_address = score_company_pair("ALFA", "BETA", same_address=True)
    assert "same_address" not in without.reasons
    assert "same_address" in with_address.reasons
