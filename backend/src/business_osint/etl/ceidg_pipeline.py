"""Masowy import CEIDG przez tabelę pomocniczą i ``COPY``.

Przy 2,5 mln działalności ścieżka „encja po encji" z ``EntityResolver`` robi
kilka zapytań na wiersz — to miliony round-tripów i godziny pracy. Tutaj idziemy
inaczej: strumień CSV trafia przez ``COPY`` do tabeli tymczasowej, a całą resztę
robią zapytania zbiorcze.

Model tożsamości dla JDG:

* **działalność** to encja ``company`` z NIP-em i REGON-em,
* **właściciel** to encja ``person``, zakotwiczona w identyfikatorze
  ``internal: ceidg-owner:{NIP}``. To twardy klucz z rejestru, nie zbieżność
  imienia i nazwiska — więc niezmiennik N4 zostaje zachowany. Bez tego dwaj
  Janowie Kowalscy prowadzący własne firmy scaliliby się w jeden węzeł.
* NIP nie może trafić na obie encje, bo ``entity_identifiers`` ma
  ``UNIQUE(scheme, value)``; stąd osobny schemat dla właściciela.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, cast

from sqlalchemy import CursorResult, text
from sqlalchemy.ext.asyncio import AsyncSession

from business_osint.db.session import get_etl_sessionmaker
from business_osint.domain.enums import SourceKind
from business_osint.domain.normalization import (
    is_valid_nip,
    normalize_company_name,
    normalize_person_name,
)
from business_osint.etl.loaders import store_raw_document
from business_osint.etl.pipeline import get_or_create_source

#: CEIDG podaje status jako całe zdanie po polsku (do 57 znaków), a kolumna
#: `companies.status` jest przeznaczona na kod. Mapujemy po prefiksie, a pełny
#: opis zachowujemy w atrybutach — bez tego traci się informację, że działalność
#: jest prowadzona wyłącznie w formie spółki cywilnej.
STATUS_CODES: dict[str, str] = {
    "aktywn": "active",
    "wykreślon": "deleted",
    "wykreslon": "deleted",
    "zawieszon": "suspended",
    "oczekuje": "pending",
    "wyłącznie w formie spółki": "partnership_only",
    "wylacznie w formie spolki": "partnership_only",
}


def status_code(raw: str) -> str | None:
    """Kod kanoniczny statusu albo ``None``, gdy nie rozpoznajemy wartości."""
    lowered = raw.strip().lower()
    if not lowered:
        return None
    for marker, code in STATUS_CODES.items():
        if marker in lowered:
            return code
    return "unknown"


STAGE_COLUMNS = (
    "nip",
    "regon",
    "nazwa",
    "nazwisko",
    "imie",
    "telefon",
    "email",
    "www",
    "kod",
    "powiat",
    "gmina",
    "miejscowosc",
    "ulica",
    "budynek",
    "lokal",
    "pkd",
    "pkd_pozostale",
    "status",
    "status_raw",
    "data_rozpoczecia",
    "data_zakonczenia",
    "data_zawieszenia",
    "data_wznowienia",
    "normalized_name",
    "owner_normalized",
    "address_display",
    "address_normalized",
    "wojewodztwo",
    "company_id",
    "owner_id",
)

#: DROP przed CREATE, nie `IF NOT EXISTS`: tabela pomocnicza przeżywa przebieg,
#: a przy zmianie zestawu kolumn `IF NOT EXISTS` zostawia stary schemat i COPY
#: wywala się na nieznanej kolumnie.
_DROP_STAGE = text("DROP TABLE IF EXISTS ceidg_stage")

_CREATE_STAGE = text(
    "CREATE UNLOGGED TABLE ceidg_stage (" + ", ".join(f"{c} text" for c in STAGE_COLUMNS) + ")"
)


@dataclass(slots=True)
class CeidgStats:
    regions: int = 0
    rows_read: int = 0
    rows_staged: int = 0
    companies: int = 0
    people: int = 0
    addresses: int = 0
    relationships: int = 0
    #: Krawędzie z wcześniejszych importów, którym dopisano brakujące pochodzenie.
    provenance_backfilled: int = 0
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "regions": self.regions,
            "provenance_backfilled": self.provenance_backfilled,
            "rows_read": self.rows_read,
            "rows_staged": self.rows_staged,
            "companies": self.companies,
            "people": self.people,
            "addresses": self.addresses,
            "relationships": self.relationships,
            "errors": len(self.errors),
        }


def format_address(*, street: str, building: str, unit: str, postal_code: str, city: str) -> str:
    """Adres w zapisie polskim: `ul. Kąty 14/2, 34-443 Sromowce Wyżne`.

    Przecinek oddziela wyłącznie ulicę od kodu pocztowego. Wcześniejsza wersja
    wstawiała go między każdy człon („ul. Kąty, 14, 34-443, Sromowce Wyżne"),
    co jest poprawne maszynowo, ale nie jest adresem, jaki ktokolwiek napisze.
    """
    line = street
    if building:
        line = f"{line} {building}".strip()
        if unit:
            line = f"{line}/{unit}"
    elif unit:
        line = f"{line} {unit}".strip()

    locality = " ".join(part for part in (postal_code, city) if part)
    return ", ".join(part for part in (line.strip(), locality) if part)


def prepare_row(row: dict[str, Any], *, region: str = "") -> tuple[str, ...] | None:
    """Wiersz CSV -> krotka do ``COPY``. ``None``, gdy brak poprawnego NIP-u.

    NIP jest jedyną kotwicą tożsamości w tym źródle — wiersz bez niego trafiłby
    do grafu jako węzeł niepowiązywalny z niczym innym.
    """
    nip = "".join(ch for ch in (row.get("Nip") or "") if ch.isdigit())
    if not is_valid_nip(nip):
        return None

    company_name = (row.get("NazwaPodmiotu") or "").strip()
    surname = (row.get("Nazwisko") or "").strip()
    given = (row.get("Imie") or "").strip()
    if company_name in ("", "-"):
        # Część wpisów nie ma nazwy firmy — wtedy firmą jest imię i nazwisko.
        company_name = " ".join(p for p in (given, surname) if p) or f"JDG {nip}"

    address_display = format_address(
        street=(row.get("Ulica") or "").strip(),
        building=(row.get("NrBudynku") or "").strip(),
        unit=(row.get("NrLokalu") or "").strip(),
        postal_code=(row.get("KodPocztowy") or "").strip(),
        city=(row.get("Miejscowosc") or "").strip(),
    )
    owner_display = " ".join(p for p in (given, surname) if p)

    return (
        nip,
        "".join(ch for ch in (row.get("Regon") or "") if ch.isdigit()),
        company_name,
        surname,
        given,
        (row.get("Telefon") or "").strip(),
        (row.get("Email") or "").strip(),
        (row.get("AdresWWW") or "").strip(),
        (row.get("KodPocztowy") or "").strip(),
        (row.get("Powiat") or "").strip(),
        (row.get("Gmina") or "").strip(),
        (row.get("Miejscowosc") or "").strip(),
        (row.get("Ulica") or "").strip(),
        (row.get("NrBudynku") or "").strip(),
        (row.get("NrLokalu") or "").strip(),
        (row.get("GlownyKodPkd") or "").strip(),
        (row.get("PozostaleKodyPkd") or "").strip(),
        status_code(row.get("StatusDzialalnosci") or "") or "",
        (row.get("StatusDzialalnosci") or "").strip(),
        (row.get("DataRozpoczeciaDzialalnosci") or "").strip(),
        (row.get("DataZakonczeniaDzialalnosci") or "").strip(),
        (row.get("DataZawieszeniaDzialalnosci") or "").strip(),
        (row.get("DataWznowieniaDzialalnosci") or "").strip(),
        normalize_company_name(company_name),
        normalize_person_name(owner_display),
        address_display,
        normalize_person_name(address_display).replace(" ", ""),
        region,
        # Identyfikatory generujemy tutaj i przenosimy przez tabelę pomocniczą.
        # Wcześniejsza wersja łączyła encje po znormalizowanej nazwie — a że JDG
        # bez własnej nazwy firmy nazywa się „Imię Nazwisko", wszyscy Kowalscy
        # w Polsce trafiali w jeden węzeł. To złamanie niezmiennika N4 od strony
        # firm: 69 tys. encji zebrało po kilka cudzych NIP-ów.
        str(uuid.uuid4()),
        str(uuid.uuid4()),
    )


async def stage_rows(session: AsyncSession, rows: Iterable[tuple[str, ...]]) -> int:
    """Wrzuca partię przez ``COPY`` — jedno przejście zamiast miliona INSERT-ów."""
    batch = list(rows)
    if not batch:
        return 0
    raw = await session.connection()
    driver = (await raw.get_raw_connection()).driver_connection
    if driver is None:  # pragma: no cover - tylko przy egzotycznym dialekcie
        raise RuntimeError("COPY wymaga sterownika asyncpg")
    await driver.copy_records_to_table("ceidg_stage", records=batch, columns=list(STAGE_COLUMNS))
    return len(batch)


# Wszystko poniżej to zapytania zbiorcze: jedno przejście po tabeli pomocniczej
# zamiast zapytania na wiersz. Każde jest idempotentne (ON CONFLICT DO NOTHING),
# więc ponowny import tego samego raportu nie tworzy duplikatów.

_DEDUPE_STAGE = text("""
    DELETE FROM ceidg_stage a USING ceidg_stage b
    WHERE a.ctid < b.ctid AND a.nip = b.nip
""")

# Krok kluczowy dla poprawności: wiersze, których NIP już znamy, przejmują
# istniejący identyfikator encji. Reszta zachowuje ten wygenerowany w Pythonie.
# Dzięki temu tożsamość opiera się wyłącznie na NIP-ie i nigdy na nazwie.
_RESOLVE_EXISTING_COMPANIES = text("""
    UPDATE ceidg_stage s
    SET company_id = i.entity_id::text
    FROM entity_identifiers i
    WHERE i.scheme = 'nip' AND i.value = s.nip
""")

_RESOLVE_EXISTING_OWNERS = text("""
    UPDATE ceidg_stage s
    SET owner_id = i.entity_id::text
    FROM entity_identifiers i
    WHERE i.scheme = 'internal' AND i.value = 'ceidg-owner:' || s.nip
""")

_INSERT_COMPANIES = text("""
    WITH nowe AS (
        SELECT s.company_id::uuid AS id, s.nazwa, s.normalized_name
        FROM ceidg_stage s
        LEFT JOIN entity_identifiers i ON i.scheme = 'nip' AND i.value = s.nip
        WHERE i.entity_id IS NULL
    ), wstawione AS (
        INSERT INTO entities (id, entity_type, display_name, normalized_name, blocking_key)
        SELECT id, 'company', nazwa, normalized_name,
               left(replace(normalized_name, ' ', ''), 12)
        FROM nowe
        ON CONFLICT (id) DO NOTHING
        RETURNING id
    )
    SELECT count(*) FROM wstawione
""")

_LINK_COMPANY_IDENTIFIERS = text("""
    INSERT INTO entity_identifiers (id, entity_id, scheme, value)
    SELECT gen_random_uuid(), s.company_id::uuid, 'nip', s.nip
    FROM ceidg_stage s
    ON CONFLICT ON CONSTRAINT uq_entity_identifiers_scheme_value DO NOTHING
""")

_INSERT_COMPANY_DETAILS = text("""
    INSERT INTO companies (entity_id, nip, regon, status, registered_on, deregistered_on,
                           pkd_main, attributes)
    SELECT s.company_id::uuid, s.nip, nullif(s.regon, ''), nullif(s.status, ''),
           nullif(s.data_rozpoczecia, '')::date, nullif(s.data_zakonczenia, '')::date,
           nullif(s.pkd, ''),
           jsonb_strip_nulls(jsonb_build_object(
               'legal_form', 'jdg',
               'city', nullif(s.miejscowosc, ''),
               'powiat', nullif(s.powiat, ''),
               'gmina', nullif(s.gmina, ''),
               'wojewodztwo', nullif(s.wojewodztwo, ''),
               'pkd_other', nullif(s.pkd_pozostale, ''),
               'status_raw', nullif(s.status_raw, ''),
               'phone', nullif(s.telefon, ''),
               'email', nullif(s.email, ''),
               'www', nullif(s.www, ''),
               'suspended_on', nullif(s.data_zawieszenia, ''),
               'resumed_on', nullif(s.data_wznowienia, '')))
    FROM ceidg_stage s
    ON CONFLICT (entity_id) DO NOTHING
""")

_INSERT_PEOPLE = text("""
    WITH nowi AS (
        SELECT s.owner_id::uuid AS id, s.imie, s.nazwisko, s.owner_normalized
        FROM ceidg_stage s
        LEFT JOIN entity_identifiers i
               ON i.scheme = 'internal' AND i.value = 'ceidg-owner:' || s.nip
        WHERE i.entity_id IS NULL AND s.nazwisko <> ''
    ), wstawione AS (
        INSERT INTO entities (id, entity_type, display_name, normalized_name, blocking_key)
        SELECT id, 'person', btrim(imie || ' ' || nazwisko), owner_normalized,
               lower(imie) || '|' || lower(nazwisko)
        FROM nowi
        ON CONFLICT (id) DO NOTHING
        RETURNING id
    )
    SELECT count(*) FROM wstawione
""")

_LINK_PEOPLE = text("""
    INSERT INTO entity_identifiers (id, entity_id, scheme, value)
    SELECT gen_random_uuid(), s.owner_id::uuid, 'internal', 'ceidg-owner:' || s.nip
    FROM ceidg_stage s
    WHERE s.nazwisko <> ''
    ON CONFLICT ON CONSTRAINT uq_entity_identifiers_scheme_value DO NOTHING
""")

_INSERT_PERSON_DETAILS = text("""
    INSERT INTO people (entity_id, first_names, last_name)
    SELECT s.owner_id::uuid, s.imie, s.nazwisko
    FROM ceidg_stage s
    WHERE s.nazwisko <> ''
    ON CONFLICT (entity_id) DO NOTHING
""")

_INSERT_ADDRESSES = text("""
    WITH nowe AS (
        SELECT DISTINCT ON (s.address_normalized)
               s.address_normalized, s.address_display, s.miejscowosc,
               s.ulica, s.budynek, s.lokal, s.kod,
               nullif(s.wojewodztwo, '') AS wojewodztwo
        FROM ceidg_stage s
        WHERE s.address_normalized <> ''
          AND NOT EXISTS (SELECT 1 FROM addresses a WHERE a.normalized = s.address_normalized)
    ), wstawione AS (
        INSERT INTO entities (id, entity_type, display_name, normalized_name)
        SELECT gen_random_uuid(), 'address', address_display, address_normalized FROM nowe
        RETURNING id, normalized_name
    )
    INSERT INTO addresses (entity_id, city, street, building, unit, postal_code,
                           voivodeship, normalized)
    SELECT w.id, n.miejscowosc, n.ulica, nullif(n.budynek, ''), nullif(n.lokal, ''),
           n.kod, n.wojewodztwo, n.address_normalized
    FROM nowe n JOIN wstawione w ON w.normalized_name = n.address_normalized
    ON CONFLICT (normalized) DO NOTHING
""")

_BACKFILL_VOIVODESHIP = text("""
    UPDATE addresses a
    SET voivodeship = s.wojewodztwo
    FROM ceidg_stage s
    WHERE a.normalized = s.address_normalized
      AND a.voivodeship IS DISTINCT FROM s.wojewodztwo
      AND nullif(s.wojewodztwo, '') IS NOT NULL
""")

# Krawędzie i ich pochodzenie powstają w **jednej instrukcji**, przez CTE
# z RETURNING. Rozdzielenie tego na dwa kroki było pierwotnym błędem: import
# masowy wstawiał relacje zbiorczym SQL-em i nie dotykał `relationship_sources`,
# przez co 6 392 682 z 6 466 459 krawędzi w bazie nie miało źródła — 98,9%
# grafu i złamany niezmiennik N2. Kontrola `check-data` to wykryła.
#
# Dokumentem źródłowym jest **raport**, nie podmiot. CEIDG udostępnia dane
# hurtowo w plikach CSV; tworzenie 3,5 mln dokumentów po jednym na firmę
# opisywałoby rzeczywistość fałszywie. Wiersz w raporcie wskazuje `locator`.
_INSERT_OWNER_EDGES = text("""
    WITH wstawione AS (
        INSERT INTO relationships (id, source_entity_id, target_entity_id, relationship_type,
                                   role, valid_from, valid_to, confidence, confidence_score)
        SELECT gen_random_uuid(), s.owner_id::uuid, s.company_id::uuid, 'sole_proprietor_of',
               'WŁAŚCICIEL', nullif(s.data_rozpoczecia, '')::date,
               nullif(s.data_zakonczenia, '')::date, 'registered', 1.0
        FROM ceidg_stage s
        WHERE s.nazwisko <> '' AND s.owner_id <> s.company_id
        ON CONFLICT DO NOTHING
        RETURNING id, source_entity_id, target_entity_id
    )
    INSERT INTO relationship_sources (relationship_id, raw_document_id, locator)
    SELECT w.id, CAST(:raw_document_id AS uuid), 'nip:' || s.nip
    FROM wstawione w
    JOIN ceidg_stage s ON s.owner_id::uuid = w.source_entity_id
                      AND s.company_id::uuid = w.target_entity_id
    ON CONFLICT DO NOTHING
""")

_INSERT_ADDRESS_EDGES = text("""
    WITH wstawione AS (
        INSERT INTO relationships (id, source_entity_id, target_entity_id, relationship_type,
                                   valid_from, confidence, confidence_score)
        SELECT gen_random_uuid(), s.company_id::uuid, a.entity_id, 'registered_at',
               nullif(s.data_rozpoczecia, '')::date, 'registered', 1.0
        FROM ceidg_stage s
        JOIN addresses a ON a.normalized = s.address_normalized
        WHERE s.address_normalized <> '' AND s.company_id::uuid <> a.entity_id
        ON CONFLICT DO NOTHING
        RETURNING id, source_entity_id, target_entity_id
    )
    INSERT INTO relationship_sources (relationship_id, raw_document_id, locator)
    SELECT w.id, CAST(:raw_document_id AS uuid), 'nip:' || s.nip
    FROM wstawione w
    JOIN addresses a ON a.entity_id = w.target_entity_id
    JOIN ceidg_stage s ON s.company_id::uuid = w.source_entity_id
                      AND s.address_normalized = a.normalized
    ON CONFLICT DO NOTHING
""")


# --- Naprawa wierszy zaimportowanych wcześniej ---------------------------------
#
# Wstawianie idzie z `ON CONFLICT DO NOTHING`, więc ponowny import **nie tyka**
# tego, co już jest w bazie. Bez poniższych instrukcji reimport przeszedłby bez
# skutku: krawędzie dalej byłyby bez pochodzenia, a adresy w starym formacie.
#
# Świadomie naprawiamy w miejscu, zamiast czyścić i ładować od nowa. Wyczyszczenie
# to skasowanie 9,5 mln encji i 6,4 mln krawędzi — operacja nieodwracalna, przy
# której każdy błąd kosztuje dobę pobierania. UPDATE jest wolniejszy i brzydszy,
# ale da się go powtórzyć.

_BACKFILL_OWNER_PROVENANCE = text("""
    INSERT INTO relationship_sources (relationship_id, raw_document_id, locator)
    SELECT r.id, CAST(:raw_document_id AS uuid), 'nip:' || s.nip
    FROM ceidg_stage s
    JOIN relationships r ON r.source_entity_id = s.owner_id::uuid
                        AND r.target_entity_id = s.company_id::uuid
                        AND r.relationship_type = 'sole_proprietor_of'
    WHERE NOT EXISTS (
        SELECT 1 FROM relationship_sources rs WHERE rs.relationship_id = r.id
    )
    ON CONFLICT DO NOTHING
""")

_BACKFILL_ADDRESS_PROVENANCE = text("""
    INSERT INTO relationship_sources (relationship_id, raw_document_id, locator)
    SELECT r.id, CAST(:raw_document_id AS uuid), 'nip:' || s.nip
    FROM ceidg_stage s
    JOIN addresses a ON a.normalized = s.address_normalized
    JOIN relationships r ON r.source_entity_id = s.company_id::uuid
                        AND r.target_entity_id = a.entity_id
                        AND r.relationship_type = 'registered_at'
    WHERE s.address_normalized <> ''
      AND NOT EXISTS (
          SELECT 1 FROM relationship_sources rs WHERE rs.relationship_id = r.id
      )
    ON CONFLICT DO NOTHING
""")

#: Numer budynku i lokalu trafiały wcześniej wyłącznie do napisu adresu, a kolumny
#: zostawały puste. Bez nich nie da się dopasować adresu do punktu adresowego PRG.
_BACKFILL_ADDRESS_PARTS = text("""
    UPDATE addresses a
    SET building = nullif(s.budynek, ''),
        unit = nullif(s.lokal, '')
    FROM ceidg_stage s
    WHERE a.normalized = s.address_normalized
      AND a.building IS NULL
      AND nullif(s.budynek, '') IS NOT NULL
""")

#: Zapis adresu: `ul. Kąty 14/2, 34-443 Sromowce Wyżne`, a nie człony rozdzielone
#: przecinkami. Poprawka formatu powstała po imporcie, więc istniejące encje
#: adresów niosą jeszcze stary napis.
_BACKFILL_ADDRESS_DISPLAY = text("""
    UPDATE entities e
    SET display_name = s.address_display
    FROM ceidg_stage s
    WHERE e.normalized_name = s.address_normalized
      AND e.entity_type = 'address'
      AND e.display_name IS DISTINCT FROM s.address_display
""")


async def _run(session: AsyncSession, statement: Any) -> int:
    result = await session.execute(statement)
    try:
        value = result.scalar()
        return int(value) if value is not None else 0
    except Exception:
        return 0


async def load_staged(
    session: AsyncSession, stats: CeidgStats, *, raw_document_id: uuid.UUID
) -> None:
    """Przenosi zawartość tabeli pomocniczej do modelu grafu.

    ``raw_document_id`` jest wymagany, nie opcjonalny. Krawędź bez pochodzenia
    łamie niezmiennik N2, a domyślna wartość oznaczałaby, że da się ją stworzyć
    przez przeoczenie — dokładnie tak powstało 6,39 mln krawędzi bez źródła.
    """
    await session.execute(_DEDUPE_STAGE)
    await session.execute(_RESOLVE_EXISTING_COMPANIES)
    await session.execute(_RESOLVE_EXISTING_OWNERS)
    stats.companies += await _run(session, _INSERT_COMPANIES)
    await session.execute(_LINK_COMPANY_IDENTIFIERS)
    await session.execute(_INSERT_COMPANY_DETAILS)
    stats.people += await _run(session, _INSERT_PEOPLE)
    await session.execute(_LINK_PEOPLE)
    await session.execute(_INSERT_PERSON_DETAILS)
    await session.execute(_INSERT_ADDRESSES)
    # Adresy wczytane wcześniej istnieją już w bazie, więc INSERT je pomija —
    # województwo trzeba im uzupełnić osobno.
    await session.execute(_BACKFILL_VOIVODESHIP)
    # Najpierw naprawa tego, co już jest, potem wstawianie nowego. Odwrotna
    # kolejność działa tak samo, ale ta czyta się zgodnie z intencją: reimport
    # ma **dokończyć** poprzedni, a nie tylko dołożyć.
    await session.execute(_BACKFILL_ADDRESS_PARTS)
    await session.execute(_BACKFILL_ADDRESS_DISPLAY)
    for statement in (_BACKFILL_OWNER_PROVENANCE, _BACKFILL_ADDRESS_PROVENANCE):
        result = await session.execute(statement, {"raw_document_id": raw_document_id})
        stats.provenance_backfilled += cast(CursorResult[Any], result).rowcount or 0

    for statement in (_INSERT_OWNER_EDGES, _INSERT_ADDRESS_EDGES):
        # rowcount dotyczy zewnętrznego INSERT-a, czyli wpisów pochodzenia.
        # Odpowiada liczbie krawędzi jeden do jednego, bo CTE zwraca dokładnie
        # te, które faktycznie weszły.
        result = await session.execute(statement, {"raw_document_id": raw_document_id})
        stats.relationships += cast(CursorResult[Any], result).rowcount or 0
    await session.execute(text("TRUNCATE ceidg_stage"))


BATCH_SIZE = 20_000


def _region_key(region: str) -> str:
    """Nazwa regionu bez przedrostka, do porównań."""
    return region.strip().lower().removeprefix("województwo ").strip()


async def import_all_regions(
    token: str, *, only_region: str | None = None, progress: Any = None
) -> CeidgStats:
    """Pobiera raporty zbiorcze i ładuje je do grafu.

    Przebieg jest wznawialny na poziomie regionu: każdy raport ładuje się we
    własnej transakcji, więc przerwanie kosztuje najwyżej jeden region.
    """
    from business_osint.etl.sources.ceidg_reports import CeidgReportClient, iter_report_rows

    stats = CeidgStats()
    client = CeidgReportClient(token)
    factory = get_etl_sessionmaker()
    try:
        reports = await client.latest_reports()
        if only_region:
            # Porównujemy pełną nazwę regionu bez przedrostka „województwo".
            # Ani `in`, ani `endswith` tu nie wystarczą: „pomorskie" jest
            # podłańcuchem i końcówką zarówno „kujawsko-pomorskiego",
            # jak i „zachodniopomorskiego".
            wanted = only_region.strip().lower().removeprefix("województwo ").strip()
            exact = [r for r in reports if _region_key(r.region) == wanted]
            reports = exact or [r for r in reports if wanted in _region_key(r.region)]

        for report in reports:
            try:
                payload = await client.download(report)
            except Exception as error:
                stats.errors.append(f"{report.region}: {error}")
                continue

            async with factory() as session, session.begin():
                # Globalny statement_timeout to 5 s — chroni API przed zapytaniem
                # grafowym, które ucieka. Operacje masowe trwają minuty, więc
                # podnosimy limit wyłącznie w tej transakcji.
                await session.execute(text("SET LOCAL statement_timeout = '30min'"))
                await session.execute(_DROP_STAGE)
                await session.execute(_CREATE_STAGE)
                source_id = await get_or_create_source(
                    session, SourceKind.CEIDG, "dane.biznes.gov.pl", "https://dane.biznes.gov.pl"
                )
                # Dokumentem źródłowym jest raport, nie podmiot. Payload trzyma
                # metadane, nie treść: archiwum ma dziesiątki megabajtów, a do
                # wykazania integralności wystarczy suma kontrolna.
                document_id, _ = await store_raw_document(
                    session,
                    source_id=source_id,
                    external_id=f"{report.id}",
                    url=report.url,
                    fetched_at=dt.datetime.now(dt.UTC),
                    content_sha256=hashlib.sha256(payload).hexdigest(),
                    payload={
                        "name": report.name,
                        "region": report.region,
                        "created_at": report.created_at,
                        "bytes": len(payload),
                    },
                )
                batch: list[tuple[str, ...]] = []
                for row in iter_report_rows(payload):
                    stats.rows_read += 1
                    prepared = prepare_row(row, region=_region_key(report.region))
                    if prepared is None:
                        continue
                    batch.append(prepared)
                    if len(batch) >= BATCH_SIZE:
                        stats.rows_staged += await stage_rows(session, batch)
                        batch.clear()
                stats.rows_staged += await stage_rows(session, batch)
                await load_staged(session, stats, raw_document_id=document_id)

            stats.regions += 1
            if progress is not None:
                progress(stats, report.region)
    finally:
        await client.aclose()
    return stats


def report_created_at(value: str) -> dt.date | None:
    try:
        return dt.date.fromisoformat(value[:10])
    except ValueError:
        return None
