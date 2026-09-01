"""Profile źródeł danych.

Jedno miejsce, w którym zapisane jest, jak wolno rozmawiać z każdym rejestrem:
tempo, ponawianie, współbieżność i sposób pobierania przyrostowego.

Dzięki temu dodanie źródła to wpis w tablicy, a nie nowy klient z własnym
pomysłem na retry. Wartości są konserwatywne — zablokowany adres IP zatrzymuje
cały projekt, a żaden z tych rejestrów nie publikuje twardego limitu.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from business_osint.domain.enums import SourceKind
from business_osint.etl.fetching.policy import RetryPolicy


class AccessMode(StrEnum):
    """Jak fizycznie zdobywamy dane."""

    BULK_FILE = "bulk_file"  # jeden plik z całością — najtańsze
    SEARCH_API = "search_api"  # zapytania po dacie/zakresie
    PER_ENTITY = "per_entity"  # jedno zapytanie na podmiot — najdroższe


class IncrementalMode(StrEnum):
    """Na czym opieramy pobieranie przyrostowe."""

    DELTA_FILE = "delta_file"  # dostawca publikuje plik zmian
    DATE_RANGE = "date_range"  # filtr po dacie publikacji/modyfikacji
    CHANGE_FEED = "change_feed"  # osobny strumień zdarzeń (np. MSiG dla KRS)
    CONTENT_HASH = "content_hash"  # brak wsparcia — porównujemy sha256 treści
    FULL_ONLY = "full_only"  # trzeba pobrać całość za każdym razem


@dataclass(frozen=True, slots=True)
class SourceProfile:
    """Parametry operacyjne jednego źródła."""

    kind: SourceKind
    name: str
    access: AccessMode
    incremental: IncrementalMode
    #: Maksymalne tempo zapytań. Dla plików zbiorczych bez znaczenia.
    rate_per_second: float
    #: Ile zapytań równolegle. Przy PER_ENTITY i tak ogranicza nas tempo.
    concurrency: int
    retry: RetryPolicy
    #: Szacowana liczba obiektów do pobrania przy pełnym przebiegu.
    estimated_objects: int | None = None
    #: Szacowany rozmiar pełnego zestawu w MB (po dekompresji).
    estimated_size_mb: int | None = None
    notes: str = ""
    #: Uwaga: liczby są szacunkami do zweryfikowania przy pierwszym imporcie.
    verified: bool = False


#: Ostrożna polityka dla rejestrów bez SLA — długi backoff, mało prób.
_CAREFUL = RetryPolicy(max_attempts=5, initial_backoff=2.0, max_backoff=120.0)
#: Dla plików statycznych: mało prób, ale szybkie — awaria jest zwykle trwała.
_BULK = RetryPolicy(max_attempts=3, initial_backoff=5.0, max_backoff=60.0)


PROFILES: dict[SourceKind, SourceProfile] = {
    SourceKind.KRS: SourceProfile(
        kind=SourceKind.KRS,
        name="api-krs.ms.gov.pl",
        access=AccessMode.PER_ENTITY,
        # KRS nie publikuje kanału zmian. Praktycznym kanałem zmian jest MSiG,
        # a bez niego zostaje ponowne pobranie i porównanie sha256.
        incremental=IncrementalMode.CONTENT_HASH,
        rate_per_second=1.0,
        concurrency=1,
        retry=_CAREFUL,
        estimated_objects=700_000,
        estimated_size_mb=120_000,
        notes="Odpis pełny zawiera wpisy wykreślone — bez niego nie ma historii.",
    ),
    SourceKind.REGON: SourceProfile(
        kind=SourceKind.REGON,
        name="GUS BIR1",
        access=AccessMode.BULK_FILE,
        incremental=IncrementalMode.DELTA_FILE,
        rate_per_second=2.0,
        concurrency=2,
        retry=_CAREFUL,
        estimated_objects=5_000_000,
        estimated_size_mb=3_000,
        notes="Paczki zbiorcze zamiast API per podmiot — API jest zbyt wolne na pełny przebieg.",
    ),
    SourceKind.CEIDG: SourceProfile(
        kind=SourceKind.CEIDG,
        name="CEIDG API",
        access=AccessMode.SEARCH_API,
        incremental=IncrementalMode.DATE_RANGE,
        # Zmierzone z nagłówków odpowiedzi 2026-09-01: `x-rate-limit-limit: 1000`
        # na 60 minut, czyli 0,28 zapytania na sekundę. Wcześniejsze 5,0 było
        # zgadywane — przy nim przebieg po pojedynczych wpisach dostał 429 po
        # 930 zapytaniach. Rejestr **publikuje** swój limit, wbrew założeniu
        # z nagłówka tego pliku; trzeba było przeczytać nagłówki, nie zgadywać.
        # 900, nie 1000: tempo równe limitowi siedzi dokładnie na jego krawędzi,
        # a okno jest przesuwne — wystarczy jedno ponowienie, żeby je przekroczyć.
        rate_per_second=900 / 3600,
        concurrency=1,
        retry=_CAREFUL,
        estimated_objects=2_500_000,
        estimated_size_mb=2_000,
        notes=(
            "Wymaga tokenu. Limit 1000 zapytań/60 min podany w nagłówkach "
            "`x-rate-limit-*`. Raport zbiorczy jest tani, ale pole `spolki` "
            "jest wyłącznie w pojedynczym wpisie `/firma`."
        ),
    ),
    SourceKind.CRBR: SourceProfile(
        kind=SourceKind.CRBR,
        name="CRBR",
        access=AccessMode.PER_ENTITY,
        incremental=IncrementalMode.CONTENT_HASH,
        rate_per_second=1.0,
        concurrency=1,
        retry=_CAREFUL,
        estimated_objects=600_000,
        estimated_size_mb=6_000,
        notes="Beneficjenci rzeczywiści — dane, których nie ma w KRS.",
    ),
    SourceKind.MF_WHITELIST: SourceProfile(
        kind=SourceKind.MF_WHITELIST,
        name="Biała lista podatników VAT",
        access=AccessMode.BULK_FILE,
        incremental=IncrementalMode.DELTA_FILE,
        rate_per_second=1.0,
        concurrency=1,
        retry=_BULK,
        estimated_objects=3_000_000,
        estimated_size_mb=2_500,
        notes="Płaski plik dzienny; API per NIP ma limity i nie nadaje się do przebiegu.",
    ),
    SourceKind.BZP: SourceProfile(
        kind=SourceKind.BZP,
        name="Biuletyn Zamówień Publicznych",
        access=AccessMode.SEARCH_API,
        incremental=IncrementalMode.DATE_RANGE,
        rate_per_second=5.0,
        concurrency=8,
        retry=_CAREFUL,
        estimated_objects=250_000,
        estimated_size_mb=400,
        notes="Naturalnie przyrostowy: pobieramy po dacie publikacji ogłoszenia.",
    ),
    SourceKind.TED: SourceProfile(
        kind=SourceKind.TED,
        name="Tenders Electronic Daily",
        access=AccessMode.BULK_FILE,
        incremental=IncrementalMode.DELTA_FILE,
        rate_per_second=2.0,
        concurrency=4,
        retry=_BULK,
        estimated_objects=1_000_000,
        estimated_size_mb=8_000,
        notes="Paczki dzienne — pobieramy tylko dni, których jeszcze nie mamy.",
    ),
    SourceKind.EU_FUNDS: SourceProfile(
        kind=SourceKind.EU_FUNDS,
        name="Dotacje UE",
        access=AccessMode.BULK_FILE,
        incremental=IncrementalMode.FULL_ONLY,
        rate_per_second=1.0,
        concurrency=1,
        retry=_BULK,
        estimated_objects=300_000,
        estimated_size_mb=150,
        notes="Mały zestaw — pełne pobranie jest tańsze niż logika przyrostowa.",
    ),
}


def profile_for(kind: SourceKind) -> SourceProfile:
    """Profil źródła. Brak profilu jest błędem konfiguracji, nie przypadkiem brzegowym."""
    try:
        return PROFILES[kind]
    except KeyError as error:
        raise KeyError(f"brak profilu pobierania dla źródła {kind}") from error


def sorted_by_cost() -> list[SourceProfile]:
    """Źródła od najtańszego do najdroższego w pełnym przebiegu.

    Koszt liczymy jako czas ściany: dla plików zbiorczych to pobranie i
    parsowanie, dla zapytań per podmiot — liczba obiektów podzielona przez
    dozwolone tempo. Ta kolejność jest podstawą planu w docs/07.
    """
    return sorted(PROFILES.values(), key=_full_run_seconds)


def _full_run_seconds(profile: SourceProfile) -> float:
    if profile.access is AccessMode.BULK_FILE:
        # Pobranie pliku: przyjmujemy 20 MB/s łącza i parsowanie w tym samym rzędzie.
        return (profile.estimated_size_mb or 0) / 20.0
    objects = profile.estimated_objects or 0
    effective_rate = profile.rate_per_second * max(1, profile.concurrency)
    return objects / effective_rate if effective_rate else float("inf")


def full_run_estimate_hours(kind: SourceKind) -> float:
    """Szacowany czas pełnego przebiegu w godzinach."""
    return _full_run_seconds(profile_for(kind)) / 3600.0
