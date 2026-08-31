"""Scalanie encji adresowych opisujących to samo miejsce.

Ten sam adres trafiał do bazy z kilku źródeł w różnym zapisie, bo kolumny
znaczyły co innego w każdym mapperze. Mappery są już naprawione, ale 12 032
zastane grupy zostają — a wspólny adres jest w tym produkcie **sygnałem
powiązania**, więc rozbicie go na duplikaty ten sygnał gasi: dwie firmy pod tym
samym adresem wyglądają jak niepowiązane.

Tożsamość adresu to miejscowość, ulica, numer budynku i lokalu. Kod pocztowy
do niej **nie należy** — Agatówka ma dwa kody dla tego samego budynku (37-450
i 37-464), a jeden budynek ma jeden adres.

Czego ta operacja **nie** robi, i to jest istotne:

* **Nie kasuje faktów.** Krawędź wskazującą na duplikat zamykamy w czasie
  systemowym (`superseded_at`) i tworzymy nową, wskazującą na ocalałego.
  Niezmiennik N1 mówi, że fakty są niezmienne — poprawka wiedzy o tożsamości
  encji jest nowym zapisem, nie przepisaniem starego.
* **Nie gubi pochodzenia.** Nowa krawędź dziedziczy wpisy `relationship_sources`
  z pierwotnej. Bez tego scalanie łamałoby N2 przy każdym przeniesieniu.
* **Nie scala miejscowości o tej samej nazwie.** Grupy rozpięte na kilka
  województw są pomijane — jest ich 272 i to nie są duplikaty. Scalenie ich
  byłoby dokładnie tą awarią N4, którą ten projekt miał już dwa razy.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, cast

from sqlalchemy import CursorResult, text
from sqlalchemy.ext.asyncio import AsyncSession

from business_osint.db.session import get_etl_sessionmaker

#: Ile grup scalamy w jednej transakcji. Każda grupa to kilka instrukcji, więc
#: partia trzyma transakcję krótką i pozwala przerwać przebieg bez cofania
#: wszystkiego, co już zrobione.
BATCH_SIZE = 500


@dataclass(slots=True)
class MergeStats:
    groups: int = 0
    merged_entities: int = 0
    edges_moved: int = 0
    skipped_cross_voivodeship: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "groups": self.groups,
            "merged_entities": self.merged_entities,
            "edges_moved": self.edges_moved,
            "skipped_cross_voivodeship": self.skipped_cross_voivodeship,
        }


# Ocalałego wybieramy deterministycznie, a nie „pierwszego z brzegu": ten sam
# przebieg na tych samych danych ma dać ten sam wynik, inaczej nie da się go
# ani powtórzyć, ani sprawdzić.
#
# Kolejność kryteriów: najwięcej powiązań (najmniej krawędzi do przeniesienia),
# potem komplet danych adresowych, na końcu identyfikator jako rozstrzygnięcie
# remisu.
_DUPLICATE_GROUPS = text("""
    WITH kandydaci AS (
        SELECT a.entity_id,
               lower(a.city) AS m, lower(a.street) AS u,
               lower(a.building) AS b, lower(coalesce(a.unit, '')) AS l,
               a.voivodeship, a.postal_code, e.degree
        FROM addresses a
        JOIN entities e ON e.id = a.entity_id AND e.merged_into_id IS NULL
        WHERE a.city IS NOT NULL AND a.street <> '' AND a.building IS NOT NULL
    ), grupy AS (
        SELECT m, u, b, l,
               count(*) AS ile,
               count(DISTINCT voivodeship) FILTER (WHERE voivodeship IS NOT NULL) AS wojewodztw,
               (array_agg(entity_id ORDER BY degree DESC,
                          (postal_code IS NOT NULL) DESC, entity_id))[1] AS ocalaly,
               array_agg(entity_id ORDER BY degree DESC,
                         (postal_code IS NOT NULL) DESC, entity_id) AS wszystkie
        FROM kandydaci
        GROUP BY m, u, b, l
        HAVING count(*) > 1
    )
    SELECT ocalaly, wszystkie, wojewodztw
    FROM grupy
    ORDER BY ocalaly
    LIMIT :batch_size OFFSET :offset
""")

# Krawędź przenosimy **przez zamknięcie i nowy wpis**, nie przez UPDATE.
# `ON CONFLICT DO NOTHING` obsługuje przypadek, w którym ocalały ma już
# identyczną krawędź: fakt jest wtedy reprezentowany, a duplikat trzeba tylko
# zamknąć.
_MOVE_EDGES = text("""
    WITH do_przeniesienia AS (
        SELECT r.*, gen_random_uuid() AS nowy_id
        FROM relationships r
        WHERE r.superseded_at IS NULL
          AND (r.source_entity_id = ANY(:losers) OR r.target_entity_id = ANY(:losers))
          -- Pętla własna powstałaby, gdyby obie strony krawędzi trafiły do tej
          -- samej encji; ograniczenie tabeli i tak by ją odrzuciło.
          AND NOT (r.source_entity_id = ANY(:losers) AND r.target_entity_id = ANY(:losers))
    ), nowe AS (
        INSERT INTO relationships (
            id, source_entity_id, target_entity_id, relationship_type, role,
            valid_from, valid_to, confidence, confidence_score, attributes
        )
        SELECT d.nowy_id,
               CASE WHEN d.source_entity_id = ANY(:losers)
                    THEN CAST(:survivor AS uuid) ELSE d.source_entity_id END,
               CASE WHEN d.target_entity_id = ANY(:losers)
                    THEN CAST(:survivor AS uuid) ELSE d.target_entity_id END,
               d.relationship_type, d.role, d.valid_from, d.valid_to,
               d.confidence, d.confidence_score, d.attributes
        FROM do_przeniesienia d
        ON CONFLICT DO NOTHING
        RETURNING id
    )
    -- Identyfikator nowej krawędzi niesiemy jawnie przez `nowy_id`, zamiast
    -- odtwarzać powiązanie po końcach i typie. Duplikat potrafi mieć kilka
    -- krawędzi tego samego typu i takie dopasowanie byłoby niejednoznaczne —
    -- pochodzenie trafiłoby wtedy pod niewłaściwy fakt.
    INSERT INTO relationship_sources (relationship_id, raw_document_id, locator)
    SELECT d.nowy_id, rs.raw_document_id, rs.locator
    FROM do_przeniesienia d
    JOIN nowe n ON n.id = d.nowy_id
    JOIN relationship_sources rs ON rs.relationship_id = d.id
    ON CONFLICT DO NOTHING
""")

_CLOSE_EDGES = text("""
    UPDATE relationships r
    SET superseded_at = now()
    WHERE r.superseded_at IS NULL
      AND (r.source_entity_id = ANY(:losers) OR r.target_entity_id = ANY(:losers))
""")

_MARK_MERGED = text("""
    UPDATE entities SET merged_into_id = CAST(:survivor AS uuid)
    WHERE id = ANY(:losers)
""")

_RECORD_MERGE = text("""
    INSERT INTO entity_merges (id, survivor_id, merged_id, score, reason, decided_by)
    SELECT gen_random_uuid(), CAST(:survivor AS uuid), unnest(CAST(:losers AS uuid[])),
           1.0, :reason, 'auto'
""")

#: Uzasadnienie trafia do `entity_merges.reason` i jest jedynym śladem, po którym
#: da się później zrozumieć, dlaczego dwie encje przestały być dwiema.
REASON = "identyczna miejscowość, ulica, numer budynku i lokalu"


async def merge_group(session: AsyncSession, survivor: uuid.UUID, losers: list[uuid.UUID]) -> int:
    """Scala jedną grupę. Zwraca liczbę zamkniętych krawędzi."""
    params = {"survivor": str(survivor), "losers": losers}
    await session.execute(_MOVE_EDGES, params)
    closed = cast(CursorResult[Any], await session.execute(_CLOSE_EDGES, params)).rowcount or 0
    await session.execute(_MARK_MERGED, params)
    await session.execute(_RECORD_MERGE, {**params, "reason": REASON})
    return closed


async def merge_batch(
    session: AsyncSession, *, batch_size: int, offset: int, stats: MergeStats
) -> tuple[int, int]:
    """Scala jedną partię grup na **podanej** sesji. Zwraca (nowy offset, ile grup).

    Wydzielone z `merge_duplicate_addresses`, żeby dało się to uruchomić na sesji
    testowej. Wariant produkcyjny otwiera własną sesję na silniku ETL i nie
    widziałby danych zapisanych w transakcji testu — a co gorsza, wywołany
    z testu pracowałby na bazie produkcyjnej. Zdarzyło się to raz i scaliło
    12 665 encji, zanim ktokolwiek o to poprosił.
    """
    groups = (
        await session.execute(_DUPLICATE_GROUPS, {"batch_size": batch_size, "offset": offset})
    ).all()
    processed = 0
    for row in groups:
        if row.wojewodztw > 1:
            # Miejscowości o tej samej nazwie w różnych województwach to różne
            # miejsca. Pomijamy i **przesuwamy offset**, inaczej ta sama grupa
            # wracałaby w każdej partii bez końca.
            stats.skipped_cross_voivodeship += 1
            offset += 1
            continue
        losers = [e for e in row.wszystkie if e != row.ocalaly]
        stats.edges_moved += await merge_group(session, row.ocalaly, losers)
        stats.merged_entities += len(losers)
        stats.groups += 1
        processed += 1
    return offset, len(groups)


async def merge_duplicate_addresses(
    *, limit: int | None = None, progress: Any = None
) -> MergeStats:
    """Scala adresy opisujące to samo miejsce **w bazie produkcyjnej**.

    ``limit`` ogranicza liczbę grup. Do testów służy `merge_batch`, które
    przyjmuje sesję.
    """
    stats = MergeStats()
    offset = 0
    factory = get_etl_sessionmaker()

    while True:
        batch = BATCH_SIZE if limit is None else min(BATCH_SIZE, limit - stats.groups)
        if batch <= 0:
            return stats

        async with factory() as session, session.begin():
            await session.execute(text("SET LOCAL statement_timeout = '30min'"))
            offset, seen = await merge_batch(session, batch_size=batch, offset=offset, stats=stats)
        if seen == 0:
            return stats
        if progress is not None:
            progress(stats)
