"""Zadania utrzymaniowe uruchamiane po każdym większym imporcie."""

from __future__ import annotations

import uuid
from typing import Any, cast

from sqlalchemy import CursorResult, text

from business_osint.db.session import get_etl_sessionmaker

#: Wielkość partii przy przeliczaniu stopni. Dobrana tak, żeby pojedynczy
#: UPDATE kończył się w sekundach — dzięki temu limit czasu instrukcji nigdy
#: nie ucina pracy w połowie, a postęp jest widoczny.
DEGREE_BATCH_SIZE = 200_000

# asyncpg wykonuje jedną instrukcję na wywołanie (przygotowuje ją po stronie
# serwera), więc budowa tabeli pomocniczej musi być rozbita na osobne kroki —
# `cannot insert multiple commands into a prepared statement`.
_BUILD_DEGREES: tuple[Any, ...] = (
    text("DROP TABLE IF EXISTS entity_degree_tmp"),
    text("""
        CREATE UNLOGGED TABLE entity_degree_tmp AS
        SELECT entity_id, count(*)::int AS degree
        FROM (
            SELECT source_entity_id AS entity_id FROM relationships WHERE superseded_at IS NULL
            UNION ALL
            SELECT target_entity_id FROM relationships WHERE superseded_at IS NULL
        ) x
        GROUP BY entity_id
    """),
    text("ALTER TABLE entity_degree_tmp ADD PRIMARY KEY (entity_id)"),
)

# Aktualizacja partiami. Pojedynczy UPDATE na 8 mln wierszy trwał ponad pół
# godziny i został ucięty przez statement_timeout: kolumna `degree` występuje
# w dwóch indeksach, więc każdy wiersz wymusza ich przepisanie i mechanizm HOT
# nie działa.
_UPDATE_BATCH = text("""
    WITH partia AS (
        SELECT d.entity_id, d.degree
        FROM entity_degree_tmp d
        JOIN entities e ON e.id = d.entity_id
        WHERE e.degree IS DISTINCT FROM d.degree
        LIMIT :batch_size
    )
    UPDATE entities e
    SET degree = p.degree
    FROM partia p
    WHERE e.id = p.entity_id
""")

#: Encje, które wypadły ze wszystkich relacji, muszą wrócić do zera.
_RESET_ORPHANS = text("""
    UPDATE entities e
    SET degree = 0
    WHERE e.degree <> 0
      AND NOT EXISTS (SELECT 1 FROM entity_degree_tmp d WHERE d.entity_id = e.id)
""")


async def recompute_degrees(*, progress: Any = None) -> int:
    """Przelicza zdenormalizowany stopień węzłów. Zwraca liczbę zmienionych encji."""
    updated = 0
    factory = get_etl_sessionmaker()

    async with factory() as session, session.begin():
        await session.execute(text("SET LOCAL statement_timeout = '60min'"))
        for statement in _BUILD_DEGREES:
            await session.execute(statement)

    while True:
        async with factory() as session, session.begin():
            await session.execute(text("SET LOCAL statement_timeout = '15min'"))
            result = await session.execute(_UPDATE_BATCH, {"batch_size": DEGREE_BATCH_SIZE})
            changed = cast(CursorResult[Any], result).rowcount or 0
        updated += changed
        if progress is not None:
            progress(updated)
        if changed == 0:
            break

    async with factory() as session, session.begin():
        await session.execute(text("SET LOCAL statement_timeout = '30min'"))
        result = await session.execute(_RESET_ORPHANS)
        updated += cast(CursorResult[Any], result).rowcount or 0
        await session.execute(text("DROP TABLE IF EXISTS entity_degree_tmp"))

    return updated


#: Wielkość partii przy przepisywaniu nazw adresów. Ta sama zasada co przy
#: stopniach: pojedynczy UPDATE ma kończyć się w sekundach.
ADDRESS_BATCH_SIZE = 20_000

# Adresy zaimportowane wcześniej mają w `entities.normalized_name` klucz
# naturalny — ciąg bez spacji, np. `chemikow709411plock`. Indeks pełnotekstowy
# widzi tam **jeden token**, więc zapytanie „chemikow plock" nie ma czego
# dopasować i wyszukiwanie adresu nie działa w ogóle.
#
# Klucz naturalny zostaje tam, gdzie jest jego miejsce: w `addresses.normalized`,
# gdzie służy do scalania. `entities.normalized_name` przechodzi na postać
# wyszukiwalną.
#
# Przeliczamy **w Pythonie**, funkcją `address_search_key`, zamiast odtwarzać
# składanie napisu w SQL-u. Druga implementacja tej samej reguły rozjechałaby
# się z pierwszą przy pierwszej zmianie normalizacji, a wtedy część adresów
# byłaby wyszukiwalna inaczej niż reszta — bez żadnego sygnału, że tak jest.
# Postęp śledzimy **kursorem po id**, nie warunkiem „nazwa bez spacji".
# Ten drugi wygląda naturalnie i jest pętlą nieskończoną: adres jednowyrazowy
# po przeliczeniu nadal nie ma spacji, więc wracałby w każdej kolejnej partii.
_ADDRESSES_TO_RESPLIT = text("""
    SELECT e.id, e.display_name
    FROM entities e
    WHERE e.entity_type = 'address'
      AND e.id > CAST(:after AS uuid)
    ORDER BY e.id
    LIMIT :batch_size
""")

_APPLY_ADDRESS_NAMES = text("""
    UPDATE entities e
    SET normalized_name = nowa.wartosc
    FROM (SELECT unnest(CAST(:ids AS uuid[])) AS id,
                 unnest(CAST(:values AS text[])) AS wartosc) AS nowa
    WHERE e.id = nowa.id
""")


async def resplit_address_names(*, progress: Any = None) -> int:
    """Przepisuje nazwy encji adresowych na postać wyszukiwalną. Zwraca liczbę zmian."""
    from business_osint.domain.normalization import address_search_key

    updated = 0
    after = uuid.UUID(int=0)
    factory = get_etl_sessionmaker()
    while True:
        async with factory() as session, session.begin():
            await session.execute(text("SET LOCAL statement_timeout = '15min'"))
            rows = (
                await session.execute(
                    _ADDRESSES_TO_RESPLIT,
                    {"batch_size": ADDRESS_BATCH_SIZE, "after": str(after)},
                )
            ).all()
            if not rows:
                return updated

            ids = [row.id for row in rows]
            values = [address_search_key(row.display_name) for row in rows]
            await session.execute(_APPLY_ADDRESS_NAMES, {"ids": ids, "values": values})

        after = ids[-1]
        updated += len(rows)
        if progress is not None:
            progress(updated)


# Stan rejestracji LEI leży w pobranych dokumentach GLEIF i nie był z nich nigdy
# wyciągnięty. Wszystkie 45 530 numerów LEI w bazie mają pokrycie w dokumentach,
# więc to jest przepisanie danych, które już mamy — bez ani jednego zapytania
# do sieci.
_LEI_DOCUMENTS = text("""
    SELECT d.payload
    FROM raw_documents d
    JOIN sources s ON s.id = d.source_id
    WHERE s.kind = 'gleif' AND d.payload ? 'data'
    ORDER BY d.id
    LIMIT :batch_size OFFSET :offset
""")

_APPLY_LEI_RECORDS = text("""
    UPDATE companies c
    SET attributes = c.attributes || jsonb_build_object('lei_records', wpisy.rekordy)
    FROM (
        SELECT i.entity_id, jsonb_agg(nowe.rekord ORDER BY nowe.rekord->>'lei') AS rekordy
        FROM (SELECT unnest(CAST(:leis AS text[])) AS lei,
                     unnest(CAST(:records AS jsonb[])) AS rekord) AS nowe
        JOIN entity_identifiers i ON i.scheme = 'lei' AND i.value = nowe.lei
        GROUP BY i.entity_id
    ) AS wpisy
    WHERE c.entity_id = wpisy.entity_id
""")


async def backfill_lei_records(*, progress: Any = None) -> int:
    """Przepisuje stan rejestracji LEI z pobranych dokumentów do atrybutów firm.

    Rekordy zbieramy **w całości przed zapisem**, a nie partia po partii. Zapis
    partiami nadpisywałby `lei_records` przy każdym przebiegu, więc spółka,
    której numery LEI trafiły do różnych dokumentów, zachowałaby tylko te
    z ostatniej partii. Przy 57 959 rekordach zebranie wszystkiego w pamięci
    kosztuje kilka megabajtów i usuwa całą klasę tego błędu.

    Deduplikujemy po numerze LEI: strony wyników GLEIF zachodzą na siebie, więc
    ten sam rekord bywa w kilku dokumentach.

    Zwraca liczbę **różnych** numerów LEI, które udało się opisać.
    """
    import json as _json

    from business_osint.etl.sources.gleif_mapper import parse_lei_registrations

    unique: dict[str, dict[str, str | None]] = {}
    offset = 0
    batch = 200
    factory = get_etl_sessionmaker()

    while True:
        async with factory() as session:
            await session.execute(text("SET statement_timeout = '15min'"))
            payloads = list(
                (
                    await session.execute(_LEI_DOCUMENTS, {"batch_size": batch, "offset": offset})
                ).scalars()
            )
        if not payloads:
            break
        for payload in payloads:
            for record in parse_lei_registrations(payload):
                unique[str(record["lei"])] = record
        offset += batch
        if progress is not None:
            progress(len(unique))

    if not unique:
        return 0

    records = list(unique.values())
    async with factory() as session, session.begin():
        await session.execute(text("SET LOCAL statement_timeout = '15min'"))
        await session.execute(
            _APPLY_LEI_RECORDS,
            {
                "leis": [str(r["lei"]) for r in records],
                "records": [_json.dumps(r, ensure_ascii=False) for r in records],
            },
        )
    return len(records)


async def refresh_map_grid() -> int:
    """Przelicza siatkę mapy. Zwraca liczbę komórek.

    Wołane po każdym imporcie, który zmienia adresy albo współrzędne. Siatka
    jest **kopią** stanu `addresses`, więc pominięcie tego kroku nie psuje
    żadnego zapytania — mapa po prostu po cichu pokazuje poprzedni import.
    Dlatego `/map/coverage` zwraca datę przeliczenia: rozjazd ma być widoczny.
    """
    factory = get_etl_sessionmaker()
    async with factory() as session, session.begin():
        await session.execute(text("SET LOCAL statement_timeout = '30min'"))
        wynik = await session.execute(text("SELECT odswiez_siatke_adresow()"))
        return int(wynik.scalar_one())
