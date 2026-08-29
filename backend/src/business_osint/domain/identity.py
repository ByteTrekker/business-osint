"""Entity resolution: rozstrzyganie, czy dwa rekordy to ten sam byt.

Strategia (deterministyczna przed probabilistyczną):

1. Twardy identyfikator (KRS/NIP/REGON/hash PESEL) -> pewne dopasowanie.
2. Blokowanie (blocking) po kluczu z ``normalization`` -> mały zbiór kandydatów.
3. Scoring cech (nazwa, adres, rola, rocznik) -> decyzja MATCH / REVIEW / NO_MATCH.

Wszystko poza pkt. 1 trafia do kolejki ``review`` — nie scalamy automatycznie
osób na podstawie samej zbieżności imienia i nazwiska.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher
from enum import StrEnum

from business_osint.domain.enums import IdentifierScheme
from business_osint.domain.normalization import (
    normalize_company_name,
    normalize_person_name,
)

#: Progi decyzyjne. Celowo konserwatywne: fałszywe scalenie osób jest
#: dużo droższe niż duplikat (duplikat widać, błędne scalenie tworzy fikcyjne powiązania).
MATCH_THRESHOLD = 0.92
REVIEW_THRESHOLD = 0.75


class MatchDecision(StrEnum):
    MATCH = "match"
    REVIEW = "review"
    NO_MATCH = "no_match"


@dataclass(frozen=True, slots=True)
class CandidateFeatures:
    """Cechy porównywanej pary rekordów."""

    name_similarity: float
    same_birth_year: bool | None = None
    same_address: bool | None = None
    shared_company_count: int = 0


@dataclass(frozen=True, slots=True)
class MatchResult:
    decision: MatchDecision
    score: float
    reasons: tuple[str, ...] = field(default=())


def string_similarity(a: str, b: str) -> float:
    """Podobieństwo 0..1. SequenceMatcher wystarcza na MVP.

    Docelowo: ``pg_trgm.similarity`` po stronie bazy (żeby liczyć na milionach
    rekordów) albo RapidFuzz, jeśli scoring zostanie w Pythonie.
    """
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def resolve_by_identifier(
    identifiers: dict[IdentifierScheme, str],
    index: dict[tuple[IdentifierScheme, str], str],
) -> str | None:
    """Zwraca entity_id, jeśli którykolwiek twardy identyfikator jest już znany.

    ``index`` to mapa (schemat, wartość) -> entity_id, w produkcji zastąpiona
    zapytaniem do tabeli ``entity_identifiers`` (UNIQUE na (scheme, value)).
    """
    for scheme in (
        IdentifierScheme.KRS,
        IdentifierScheme.NIP,
        IdentifierScheme.REGON,
        IdentifierScheme.PESEL_HASH,
        IdentifierScheme.CEIDG,
        IdentifierScheme.LEI,
    ):
        value = identifiers.get(scheme)
        if value and (entity_id := index.get((scheme, value))):
            return entity_id
    return None


def score_company_pair(
    left_name: str, right_name: str, same_address: bool | None = None
) -> MatchResult:
    """Porównuje dwie firmy bez wspólnego identyfikatora."""
    similarity = string_similarity(
        normalize_company_name(left_name), normalize_company_name(right_name)
    )
    score = similarity
    reasons = [f"name_similarity={similarity:.2f}"]
    if same_address:
        score = min(1.0, score + 0.05)
        reasons.append("same_address")
    return _decide(score, tuple(reasons))


def score_person_pair(features: CandidateFeatures) -> MatchResult:
    """Porównuje dwie osoby.

    Sama zgodność imienia i nazwiska NIGDY nie daje automatycznego MATCH —
    w Polsce jest ok. 100 tys. osób o nazwisku Nowak. Potrzebny jest
    dodatkowy sygnał: rocznik, adres albo wspólna spółka.
    """
    score = features.name_similarity * 0.7
    reasons = [f"name_similarity={features.name_similarity:.2f}"]
    if features.same_birth_year:
        score += 0.15
        reasons.append("same_birth_year")
    if features.same_address:
        score += 0.10
        reasons.append("same_address")
    if features.shared_company_count:
        score += min(0.10, 0.05 * features.shared_company_count)
        reasons.append(f"shared_companies={features.shared_company_count}")
    return _decide(min(score, 1.0), tuple(reasons))


def _decide(score: float, reasons: tuple[str, ...]) -> MatchResult:
    if score >= MATCH_THRESHOLD:
        decision = MatchDecision.MATCH
    elif score >= REVIEW_THRESHOLD:
        decision = MatchDecision.REVIEW
    else:
        decision = MatchDecision.NO_MATCH
    return MatchResult(decision=decision, score=round(score, 4), reasons=reasons)


def person_display_name(first_names: str, last_name: str) -> str:
    return " ".join(part for part in (first_names.strip(), last_name.strip()) if part)


def candidate_key(entity_type: str, *parts: str) -> str:
    """Klucz kandydata do blokowania (używany przez ETL do grupowania rekordów)."""
    normalized = "|".join(normalize_person_name(p) for p in parts if p)
    return f"{entity_type}:{normalized}"
