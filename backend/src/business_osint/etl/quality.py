"""Asercje jakości danych uruchamiane po imporcie.

Powód istnienia tego modułu jest konkretny. 69 438 firm i 505 640 osób leżało
w bazie fałszywie scalonych, a jedna jednoosobowa działalność miała przypisane
734 adresy. Obie awarie łamały niezmiennik N4, obie były wykrywalne pojedynczym
zapytaniem — i obie przeleżały tygodnie, bo nikt takiego zapytania nie pisał.
Wyszło dopiero wtedy, gdy właściciel projektu wyszukał w interfejsie samego
siebie i zobaczył cudzy NIP.

Każda kontrola w tym pliku wywodzi się z awarii, która **naprawdę się zdarzyła**,
albo z niezmiennika zapisanego w CLAUDE.md. Nie dopisujemy tu kontroli
hipotetycznych: asercja, która nigdy nie może zapłonąć, uczy ignorowania raportu.

Nie ma tu kontroli na pętle własne ani na odwrócony okres obowiązywania,
choć oba były realnymi awariami. Wymuszają je ograniczenia `CHECK` na tabeli
`relationships` — `ck_relationships_no_self_loop` i `ck_relationships_valid_period`
— więc naruszenie nie ma jak trafić do bazy. Napisałem obie i dopiero test
integracyjny pokazał, że nie da się ich zapalić. Gdyby te ograniczenia kiedyś
zniknęły, kontrole trzeba tu dopisać.

Kontrole są świadomie napisane jako surowy SQL zwracający **liczbę naruszeń
i próbkę**. Sama liczba mówi, czy jest awaria; próbka mówi, od czego zacząć
debugowanie, i oszczędza pisania drugiego zapytania po fakcie.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from business_osint.db.session import get_etl_sessionmaker

#: Ile przykładowych naruszeń pokazać przy nieudanej kontroli.
SAMPLE_SIZE = 5


@dataclass(frozen=True, slots=True)
class Check:
    """Pojedyncza asercja: nazwa, uzasadnienie i zapytanie liczące naruszenia.

    ``sql`` musi zwracać jedną kolumnę z identyfikatorem albo opisem naruszenia.
    Liczbę i próbkę wyznacza runner, żeby każda kontrola nie powtarzała tej samej
    obudowy.

    ``threshold`` to liczba naruszeń, którą jeszcze uznajemy za stan normalny.
    Domyślnie zero. Wartość wyższa wymaga komentarza mówiącego, dlaczego dane
    naruszenie jest dopuszczalne — inaczej próg cicho zamienia awarię w tło.
    """

    name: str
    invariant: str
    description: str
    sql: str
    threshold: int = 0


@dataclass(slots=True)
class CheckResult:
    """Wynik jednej kontroli."""

    check: Check
    violations: int
    sample: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.violations <= self.check.threshold


@dataclass(slots=True)
class QualityReport:
    """Wynik całego przebiegu."""

    results: list[CheckResult] = field(default_factory=list)

    @property
    def failed(self) -> list[CheckResult]:
        return [r for r in self.results if not r.passed]

    @property
    def ok(self) -> bool:
        return not self.failed


# --- Kontrole ----------------------------------------------------------------

CHECKS: tuple[Check, ...] = (
    Check(
        name="entity_holds_one_identifier_per_scheme",
        invariant="N4",
        description=(
            "Encja z dwoma NIP-ami to dwie encje sklejone w jedną. Dokładnie tak "
            "wyglądała awaria z 69 438 firmami: import CEIDG łączył wiersze po "
            "znormalizowanej nazwie, więc każdy Kowalski bez nazwy firmy trafiał "
            "do wspólnego węzła razem z cudzymi numerami. "
            "Kontrola obejmuje wyłącznie identyfikatory krajowe. LEI jest "
            "świadomie pominięty: GLEIF wystawia rekordy zduplikowane i wygasłe, "
            "więc jedna spółka legalnie nosi dwa LEI-e — sprawdzone na 22 "
            "przypadkach, każdy z jednym KRS-em i dwoma LEI-ami."
        ),
        sql="""
            SELECT e.display_name || ' (' || i.scheme || ' x' || count(*) || ')'
            FROM entity_identifiers i
            JOIN entities e ON e.id = i.entity_id
            WHERE e.merged_into_id IS NULL
              AND i.scheme IN ('nip', 'krs', 'regon')
            GROUP BY e.id, e.display_name, i.scheme
            HAVING count(*) > 1
        """,
    ),
    Check(
        name="relationship_has_provenance",
        invariant="N2",
        description=(
            "Krawędź bez wpisu w relationship_sources jest twierdzeniem bez źródła. "
            "Nie da się jej ani zweryfikować, ani obronić przed osobą, której "
            "dotyczy."
        ),
        # 733 krawędzie z importu z 30 sierpnia, sprzed wprowadzenia pochodzenia
        # do ścieżki masowej. Ich raport źródłowy już nie istnieje — CEIDG
        # publikuje migawki, a te wpisy w bieżących raportach nie występują.
        # Wymyślenie im dokumentu byłoby gorsze niż zostawienie ich policzonych.
        # Próg jest dokładny, nie zaokrąglony: 734. naruszenie to regresja.
        threshold=733,
        sql="""
            SELECT r.id::text
            FROM relationships r
            WHERE NOT EXISTS (
                SELECT 1 FROM relationship_sources s WHERE s.relationship_id = r.id
            )
        """,
    ),
    Check(
        name="company_is_not_registered_at_many_addresses",
        invariant="N4",
        description=(
            "Firma zarejestrowana pod kilkudziesięcioma adresami naraz to skutek "
            "scalenia, nie fakt o gospodarce. Tak wyszedł GABAR z 734 adresami: "
            "EntityResolver łączył encje po dwunastu pierwszych znakach nazwy. "
            "Próg 12 zostawia miejsce na spółki z oddziałami; wyżej to już defekt."
        ),
        sql="""
            SELECT e.display_name || ' (' || count(*) || ' adresów)'
            FROM relationships r
            JOIN entities e ON e.id = r.source_entity_id
            WHERE r.relationship_type = 'registered_at'
              AND r.superseded_at IS NULL
              AND e.merged_into_id IS NULL
            GROUP BY e.id, e.display_name
            HAVING count(*) > 12
        """,
    ),
    Check(
        name="superseded_fact_is_not_older_than_its_record",
        invariant="N1",
        description=(
            "Fakt unieważniony wcześniej, niż został zapisany, oznacza zepsutą oś "
            "czasu systemowego — a na niej stoi zapytanie `as_of`."
        ),
        sql="""
            SELECT r.id::text
            FROM relationships r
            WHERE r.superseded_at IS NOT NULL
              AND r.superseded_at < r.recorded_at
        """,
    ),
    Check(
        name="entity_has_a_display_name",
        invariant="N4",
        description=(
            "Encja bez nazwy jest nieodróżnialna od każdej innej takiej encji, "
            "więc prędzej czy później ktoś ją z czymś scali."
        ),
        sql="""
            SELECT e.id::text
            FROM entities e
            WHERE e.merged_into_id IS NULL
              AND (e.display_name IS NULL OR btrim(e.display_name) = '')
        """,
    ),
    Check(
        name="merged_entity_has_no_active_edges",
        invariant="N1",
        description=(
            "Encja wskazana jako scalona nie może dalej trzymać własnych krawędzi — "
            "traversal pokazałby ten sam fakt dwa razy, raz na każdym z węzłów."
        ),
        sql="""
            SELECT e.id::text
            FROM entities e
            WHERE e.merged_into_id IS NOT NULL
              AND EXISTS (
                  SELECT 1 FROM relationships r
                  WHERE r.superseded_at IS NULL
                    AND (r.source_entity_id = e.id OR r.target_entity_id = e.id)
              )
        """,
    ),
    Check(
        name="degree_matches_actual_edge_count",
        invariant="N3",
        description=(
            "`entities.degree` jest zdenormalizowane i steruje tłumieniem hubów. "
            "Gdy się rozjedzie, budżet zapytania tnie nie to, co trzeba, a "
            "`meta.truncated` przestaje odpowiadać rzeczywistości. Kontrola jest "
            "kosztowna, więc uruchamiamy ją osobno — patrz `run_checks(deep=True)`."
        ),
        sql="""
            WITH rzeczywiste AS (
                SELECT entity_id, count(*)::int AS stopien
                FROM (
                    SELECT source_entity_id AS entity_id FROM relationships
                    WHERE superseded_at IS NULL
                    UNION ALL
                    SELECT target_entity_id FROM relationships
                    WHERE superseded_at IS NULL
                ) x
                GROUP BY entity_id
            )
            SELECT e.display_name || ' (' || e.degree || ' zamiast ' || r.stopien || ')'
            FROM entities e
            JOIN rzeczywiste r ON r.entity_id = e.id
            WHERE e.degree IS DISTINCT FROM r.stopien
        """,
    ),
)

#: Kontrole liczone na całych relacjach — kosztowne, poza domyślnym przebiegiem.
DEEP_CHECKS = frozenset({"degree_matches_actual_edge_count"})


def select_checks(*, deep: bool = False) -> tuple[Check, ...]:
    """Zwraca kontrole do uruchomienia.

    Domyślny przebieg pomija kontrole pełnoprzeglądowe, żeby dało się go odpalać
    po każdym imporcie bez zastanowienia. Kontrola, którą uruchamia się rzadko,
    bo „długo trwa", jest kontrolą, której się nie uruchamia wcale.
    """
    if deep:
        return CHECKS
    return tuple(c for c in CHECKS if c.name not in DEEP_CHECKS)


async def execute_checks(
    session: AsyncSession, checks: Sequence[Check], *, progress: Any = None
) -> QualityReport:
    """Uruchamia podane kontrole na podanej sesji.

    Wydzielone z `run_checks`, żeby dało się je odpalić na sesji testowej.
    Wariant produkcyjny otwiera własną sesję na silniku ETL i nie zobaczyłby
    danych zapisanych w transakcji testu.
    """
    report = QualityReport()
    for check in checks:
        statement = text(
            f"SELECT count(*) AS naruszenia,"  # noqa: S608
            f" (array_agg(opis))[1:{SAMPLE_SIZE}] AS probka"
            f" FROM ({check.sql}) AS naruszenie(opis)"
        )
        row = (await session.execute(statement)).one()
        result = CheckResult(
            check=check,
            violations=int(row.naruszenia),
            sample=list(row.probka or []),
        )
        report.results.append(result)
        if progress is not None:
            progress(result)
    return report


async def run_checks(*, deep: bool = False, progress: Any = None) -> QualityReport:
    """Uruchamia asercje na produkcyjnej bazie i zwraca raport.

    Korzysta z silnika ETL, bo część kontroli przechodzi przez całą tabelę
    relacji i limit czasu instrukcji właściwy dla API by ją uciął.
    """
    factory = get_etl_sessionmaker()
    async with factory() as session:
        await session.execute(text("SET statement_timeout = '30min'"))
        return await execute_checks(session, select_checks(deep=deep), progress=progress)


def format_report(report: QualityReport) -> Sequence[str]:
    """Raport w postaci linii tekstu — dla CLI i dla logu CI."""
    lines: list[str] = []
    for result in report.results:
        mark = "OK  " if result.passed else "BŁĄD"
        lines.append(f"{mark} [{result.check.invariant}] {result.check.name}")
        if not result.passed:
            lines.append(f"       naruszeń: {result.violations}")
            for example in result.sample:
                lines.append(f"       - {example}")
    lines.append("")
    if report.ok:
        lines.append(f"Wszystkie kontrole przeszły ({len(report.results)}).")
    else:
        lines.append(f"Nieudane kontrole: {len(report.failed)} z {len(report.results)}.")
    return lines
