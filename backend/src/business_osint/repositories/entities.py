"""Odczyt profili podmiotów i wyszukiwarka."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from business_osint.domain.normalization import (
    is_valid_krs,
    is_valid_nip,
    is_valid_regon,
    normalize_company_name,
)


@dataclass(slots=True)
class SearchHit:
    id: uuid.UUID
    entity_type: str
    display_name: str
    score: float
    subtitle: str | None
    degree: int


# Wyszukiwanie jest **etapowe**, a nie jednym zapytaniem trigramowym.
#
# Powód jest zmierzony: przy 9,5 mln encji operator `%` na indeksie GIN zwraca
# stratną bitmapę i zapytanie trwa 1,7–4,3 s, czyli ginie na `statement_timeout`.
# Wyszukiwanie po najbliższych sąsiadach na indeksie GiST to 2,9 s — też za wolno.
#
# Tymczasem dopasowanie prefiksowe na indeksie btree kosztuje 0,3 ms, a dokładne
# nazwisko w `people` — 1,3 ms. Dlatego idziemy od najtańszego do najdroższego
# i zatrzymujemy się, gdy mamy komplet wyników. Trigram zostaje jako świadomie
# wybierana ostateczność, nie domyślna ścieżka.
#
# Etapy prefiksowe są **trzy, nie jeden**, i to jest istota rankingu. Zapytanie
# „orlen" na jednym szerokim `LIKE 'orlen%'` zwracało „Orlena Hintzke" przed
# ORLEN TERMIKA, bo jedynym kryterium był stopień węzła — a ten mówi, ile
# krawędzi zdążyliśmy zaimportować, nie jak istotny jest podmiot. Rozbicie na
# dopasowanie dokładne → do granicy słowa → dowolny prefiks porządkuje to
# strukturalnie: „orlena" nie jest tym samym słowem co „orlen" i trafia dopiero
# do etapu ostatniego.

# Trafność w obrębie etapu. Cztery sygnały, każdy znormalizowany do 0–1:
#
# * **pokrycie** — jaką część nazwy zajmuje zapytanie. „orlen" pokrywa „orlen"
#   w całości, a „orlen synthos green energy" w jednej czwartej.
# * **KRS** — ma go 23 683 podmiotów z 3,6 mln. W praktyce odróżnia spółkę
#   z rejestru od jednoosobowej działalności. To *proxy* istotności, nie miara:
#   duża JDG istnieje, tyle że w tych danych nie mamy czym jej wyróżnić.
# * **status** — zawieszona i wykreślona schodzą niżej. NULL (osoby, adresy)
#   jest neutralny, bo brak statusu nie jest informacją negatywną.
# * **stopień** — z nasyceniem przy 20. Bez niego różnica 3 vs 4000 krawędzi
#   przytłacza wszystkie pozostałe sygnały, a różnica 3 vs 4 nic nie znaczy.
# Ilu kandydatów trafia do rankingu w obrębie etapu. Dwadzieścia wyników
# dobieranych z trzystu daje zapas na przetasowanie, a wciąż mieści się
# w kilku milisekundach.
_CANDIDATE_POOL = 300

#: Ile trafień bierzemy pod uwagę przy sortowaniu innym niż trafność.
#:
#: Wyszukiwarka jest etapowa i **nie zna** pełnego zbioru dopasowań — dla
#: prefiksu „a" jest ich 830 tys. i policzenie ich oznaczałoby przejście przez
#: wszystkie. Sortowanie może więc uporządkować tylko to, co etapy zdążyły
#: znaleźć. Bierzemy stałą, większą pulę i sortujemy ją w całości, zamiast
#: przestawiać wiersze na jednej stronie i udawać, że to sortowanie zbioru.
#: Kontrakt API mówi to wprost.
_SORT_POOL = 200

#: Klucze sortowania. Trafność jest kolejnością naturalną etapów i nie ma
#: własnego klucza — nie ruszamy wtedy wierszy w ogóle.
SORT_KEYS = ("relevance", "degree", "name")

_RELEVANCE = """
    0.40 * LEAST(length(:normalized)::float8
                 / GREATEST(length(e.normalized_name), 1), 1.0)
  + 0.35 * (CASE WHEN c.krs IS NOT NULL THEN 1.0 ELSE 0.0 END)
  + 0.15 * (CASE WHEN c.status = 'active' THEN 1.0
                 WHEN c.status IS NULL THEN 0.5 ELSE 0.0 END)
  + 0.10 * (LEAST(e.degree, 20)::float8 / 20.0)
"""

_BY_IDENTIFIER = text("""
    SELECT e.id, e.entity_type, e.display_name, e.degree, 1.0::float8 AS score
    FROM entity_identifiers i
    JOIN entities e ON e.id = i.entity_id AND e.merged_into_id IS NULL
    WHERE i.value = :identifier
    LIMIT :limit
""")


def _name_stage(condition: str, base: float, span: float) -> Any:
    """Buduje etap nazwowy: warunek na `normalized_name` plus wspólna trafność.

    ``condition`` trafia do **podzapytania**, więc pisze się je bez aliasu
    tabeli — `normalized_name = :normalized`, nie `e.normalized_name`.

    ``base`` i ``span`` mieszczą wynik etapu w rozłącznym przedziale, żeby
    kolejność między etapami była widoczna także w samej wartości `score`,
    a nie tylko w kolejności doklejania wyników.

    Kandydatów **ogranicza podzapytanie**, i to nie jest optymalizacja, tylko
    warunek działania. `ORDER BY score` na pełnym dopasowaniu zmusza bazę do
    policzenia trafności dla każdego trafienia: dla prefiksu „a" to 830 tys.
    wierszy i 338 ms. Wewnętrzne `ORDER BY degree DESC LIMIT` idzie po indeksie
    stopnia i kończy po znalezieniu kompletu — 2,5 ms.

    Cena: w etapie szerokiego prefiksu podmiot o niskim stopniu może wypaść
    z puli, zanim dojdzie do rankingu. Jest to akceptowalne, bo trafienia
    dokładne i do granicy słowa mają własne, wcześniejsze etapy — tutaj ląduje
    to, co pasuje wyłącznie środkiem wyrazu.

    Interpolujemy do SQL-a wyłącznie stałe zdefiniowane w tym module — warunek,
    próg i rozpiętość. Wejście użytkownika nie ma tu żadnej drogi: idzie
    wyłącznie przez parametry wiązane (`:normalized`, `:prefix`, `:limit`).
    """
    return text(
        f"""
        SELECT e.id, e.entity_type, e.display_name, e.degree,
               ({base} + ({_RELEVANCE}) * {span})::float8 AS score
        FROM (
            SELECT id, entity_type, display_name, degree, normalized_name
            FROM entities
            WHERE {condition}
              AND merged_into_id IS NULL
              AND (CAST(:entity_type AS text) IS NULL
                   OR entity_type = CAST(:entity_type AS text))
            ORDER BY degree DESC
            LIMIT :candidates
        ) e
        LEFT JOIN companies c ON c.entity_id = e.id
        -- Filtr statusu **po** złączeniu, bo status mieszka w `companies`.
        -- Wciągnięcie go do podzapytania oznaczałoby złączenie na całej puli
        -- kandydatów zamiast na wycinku, który i tak przechodzi przez ranking.
        -- Województwo trzymamy w `companies.attributes`, bo pochodzi z CEIDG
        -- i nie ma go dla podmiotów z pozostałych źródeł. Filtr jest więc
        -- **zawężający**: włączenie go usuwa z wyniku wszystko, o czym nie
        -- wiemy, gdzie jest — i tak ma być, bo pytanie brzmiało „w tym
        -- województwie", a nie „może w tym województwie".
        WHERE (CAST(:status AS text) IS NULL OR c.status = CAST(:status AS text))
          AND (CAST(:voivodeship AS text) IS NULL
               OR c.attributes ->> 'wojewodztwo' = CAST(:voivodeship AS text))
        -- `e.id` na końcu nie jest ozdobnikiem: bez niego wiersze o równej
        -- trafności wracają w kolejności zależnej od planu, a wtedy przy
        -- stronicowaniu ten sam podmiot potrafi pojawić się dwa razy albo
        -- zniknąć między stronami.
        ORDER BY score DESC, length(e.normalized_name), e.degree DESC, e.id
        LIMIT :limit
    """  # noqa: S608
    )


# Dokładne dopasowanie znormalizowanej nazwy. „ORLEN S.A." i „ORLEN" normalizują
# się do tego samego, więc ten etap trafia w spółkę mimo różnicy w zapisie.
_BY_EXACT_NAME = _name_stage("normalized_name = :normalized", 0.90, 0.09)

# Dopasowanie po **zbiorze słów**, niezależne od kolejności. „termika orlen"
# trafia w ORLEN TERMIKA, czego żaden prefiks nie zrobi, a trigram robi
# w setkach milisekund zamiast w 0,15 ms.
#
# Semantyka jest koniunkcyjna: wszystkie słowa zapytania muszą wystąpić.
# Alternatywa („którekolwiek") dla „jan kowalski" zwróciłaby setki tysięcy
# wierszy, więc zapytania z wyrazami spoza nazwy — jak „PKN ORLEN", gdzie
# w bazie jest samo „orlen" — obsługuje dopiero trigram na końcu.
_BY_WORDS = _name_stage(
    "to_tsvector('simple', normalized_name) @@ plainto_tsquery('simple', :normalized)",
    0.55,
    0.14,
)

# Prefiks kończący się na granicy słowa: „orlen termika" tak, „orlena" nie.
# Spacja to najniższy drukowalny znak, więc `LIKE 'orlen %'` to wąski zakres
# na tym samym indeksie btree co prefiks szeroki — dodatkowy etap nic nie kosztuje.
_BY_WORD_PREFIX = _name_stage("normalized_name LIKE :word_prefix", 0.70, 0.19)

# Prefiks dowolny — obsługuje pisanie w trakcie („orlen ter") i wpadające przy
# okazji „orlena". Świadomie ostatni z etapów prefiksowych.
_BY_PREFIX = _name_stage("normalized_name LIKE :prefix", 0.40, 0.14)

_BY_SURNAME = text("""
    SELECT e.id, e.entity_type, e.display_name, e.degree, 0.35::float8 AS score
    FROM people p
    JOIN entities e ON e.id = p.entity_id AND e.merged_into_id IS NULL
    WHERE p.last_name = :surname
    ORDER BY e.degree DESC, e.id
    LIMIT :limit
""")

# Filtr statusu obowiązuje także tutaj. Etap ostatni, który po cichu ignoruje
# zawężenie wybrane przez użytkownika, jest gorszy niż brak wyników.
_BY_TRIGRAM = text("""
    SELECT e.id, e.entity_type, e.display_name, e.degree,
           (0.30 + similarity(e.normalized_name, :normalized) * 0.09)::float8 AS score
    FROM entities e
    LEFT JOIN companies c ON c.entity_id = e.id
    WHERE e.merged_into_id IS NULL
      AND e.normalized_name % :normalized
      AND (CAST(:entity_type AS text) IS NULL OR e.entity_type = CAST(:entity_type AS text))
      AND (CAST(:status AS text) IS NULL OR c.status = CAST(:status AS text))
      AND (CAST(:voivodeship AS text) IS NULL
           OR c.attributes ->> 'wojewodztwo' = CAST(:voivodeship AS text))
    ORDER BY score DESC, e.degree DESC, e.id
    LIMIT :limit
""")

_ENRICH = text("""
    SELECT e.id, c.nip, c.krs, c.status, a.city
    FROM entities e
    LEFT JOIN companies c ON c.entity_id = e.id
    LEFT JOIN addresses a ON a.entity_id = e.id
    WHERE e.id = ANY(:ids)
""")


class EntityRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def search(
        self,
        query: str,
        *,
        entity_type: str | None = None,
        status: str | None = None,
        voivodeship: str | None = None,
        sort: str = "relevance",
        limit: int = 20,
        offset: int = 0,
        fuzzy: bool = False,
    ) -> tuple[list[SearchHit], bool]:
        """Szuka podmiotu, przechodząc od najtańszej metody do najdroższej.

        ``status`` zawęża do podmiotów o danym stanie (`active`, `suspended`,
        `inactive`). Nie dotyczy wyszukiwania po identyfikatorze: kto podał NIP,
        chce tę encję, a nie komunikat, że jest zawieszona.

        ``fuzzy`` wymusza dopasowanie trigramowe. Domyślnie uruchamia się ono
        wyłącznie wtedy, gdy tańsze etapy nie zwróciły nic — kosztuje
        setki milisekund, a nie jednostki, więc nie może być ścieżką pierwszą.

        Zwraca stronę wyników i informację, **czy jest coś dalej**. Nie zwraca
        liczby wszystkich dopasowań: policzenie ich oznaczałoby przejście przez
        cały zbiór, a dla prefiksu „a" to 830 tys. wierszy. Stronicowanie jest
        przesunięciem, nie kursorem — etapy mają rozłączne przedziały wyniku,
        więc kolejność jest stabilna, a przy realnym przeglądaniu (kilka stron)
        koszt pobrania `offset + limit + 1` pozostaje w milisekundach. Głębokie
        przesunięcia są świadomie ograniczone w warstwie HTTP.
        """
        # Pobieramy o jeden więcej, niż zwrócimy: obecność tego wiersza jest
        # jedyną tanią odpowiedzią na pytanie „czy jest następna strona".
        needed = offset + limit + 1
        # Sortowanie inne niż trafność wymaga zobaczenia większej puli, zanim
        # cokolwiek uporządkujemy — inaczej „najwięcej powiązań" znaczyłoby
        # tylko „najwięcej na tej stronie".
        if sort != "relevance":
            needed = max(needed, _SORT_POOL)
        cleaned = query.strip()
        if not cleaned:
            return [], False

        rows: list[Any] = []
        seen: set[uuid.UUID] = set()

        def take(new_rows: list[Any]) -> None:
            for row in new_rows:
                if row["id"] not in seen:
                    seen.add(row["id"])
                    rows.append(row)

        identifier = self._identifier_candidate(cleaned)
        if identifier:
            take(await self._fetch(_BY_IDENTIFIER, {"identifier": identifier, "limit": needed}))

        normalized = normalize_company_name(cleaned) or cleaned.lower()
        if normalized:
            # Trzy etapy nazwowe od najwęższego do najszerszego. Każdy dostaje
            # ten sam komplet parametrów, bo `_name_stage` buduje je z jednego
            # szablonu — różni je wyłącznie warunek i przedział wyniku.
            params = {
                "normalized": normalized,
                "word_prefix": f"{normalized} %",
                "prefix": f"{normalized}%",
                "entity_type": entity_type,
                "status": status,
                "voivodeship": voivodeship,
                # Pula kandydatów musi pomieścić stronę, do której schodzimy —
                # inaczej przy większym przesunięciu ranking miałby z czego
                # wybierać mniej, niż wynosi żądany wycinek.
                "candidates": max(_CANDIDATE_POOL, needed),
            }
            # Każdy etap pyta o **pełną** liczbę wierszy, nie o brakującą różnicę.
            # Etap szerokiego prefiksu zwraca nadzbiór dwóch poprzednich, więc
            # limit pomniejszony o to, co już mamy, zjadały duplikaty odrzucane
            # dopiero po pobraniu. Objawiało się to gubieniem wyników na dalszych
            # stronach: przy `offset=20` wracał jeden wiersz zamiast trzech.
            for stage in (_BY_EXACT_NAME, _BY_WORD_PREFIX, _BY_WORDS, _BY_PREFIX):
                if len(rows) >= needed:
                    break
                take(await self._fetch(stage, {**params, "limit": needed}))

        # Nazwiska w CEIDG są zapisane wielkimi literami; szukamy ostatniego słowa,
        # bo użytkownik pisze „Jan Kowalski", a indeks stoi na samym nazwisku.
        # Przy filtrze województwa etap nazwiskowy odpada: encje osób nie mają
        # województwa, więc każde jego trafienie zostałoby i tak odrzucone —
        # a filtr jest zawężający, nie „może".
        if len(rows) < needed and entity_type in (None, "person") and voivodeship is None:
            surname = cleaned.split()[-1].upper()
            if len(surname) > 2:
                take(
                    await self._fetch(
                        _BY_SURNAME, {"surname": surname, "limit": needed - len(rows)}
                    )
                )

        # Trigram włączamy także **bez** prośby użytkownika, o ile tanie etapy
        # nie znalazły niczego. „PKN ORLEN" nie jest prefiksem żadnej nazwy
        # w bazie, więc dawało pustą listę mimo że ORLEN S.A. tam jest. Koszt
        # 140–250 ms płacimy wyłącznie za wynik, który i tak byłby pusty.
        if (fuzzy or not rows) and len(rows) < needed and len(normalized) >= 3:
            take(
                await self._fetch(
                    _BY_TRIGRAM,
                    {
                        "normalized": normalized,
                        "entity_type": entity_type,
                        "status": status,
                        "voivodeship": voivodeship,
                        "limit": needed,
                    },
                )
            )

        if sort == "degree":
            rows.sort(key=lambda row: (-int(row["degree"] or 0), row["display_name"] or ""))
        elif sort == "name":
            rows.sort(key=lambda row: (row["display_name"] or "").lower())

        has_more = len(rows) > offset + limit
        page = rows[offset : offset + limit]
        return await self._to_hits(page), has_more

    async def co_located(
        self, entity_id: uuid.UUID, *, limit: int = 50, offset: int = 0
    ) -> list[dict[str, Any]]:
        """Inne podmioty pod tym samym adresem. Przyjmuje id podmiotu albo id adresu."""
        rows = await self._session.execute(
            _CO_LOCATED, {"id": entity_id, "limit": limit, "offset": offset}
        )
        return [dict(row) for row in rows.mappings()]

    async def count_co_located(self, entity_id: uuid.UUID) -> int:
        """Ilu sąsiadów ma podmiot pod swoim adresem."""
        return int((await self._session.execute(_CO_LOCATED_COUNT, {"id": entity_id})).scalar_one())

    async def changes(
        self, entity_id: uuid.UUID, *, limit: int = 50, offset: int = 0
    ) -> list[dict[str, Any]]:
        """Oś czasu zmian podmiotu: atrybuty z dziennika plus powiązania z relacji."""
        rows = await self._session.execute(
            _CHANGES, {"id": entity_id, "limit": limit, "offset": offset}
        )
        return [dict(row) for row in rows.mappings()]

    async def count_changes(self, entity_id: uuid.UUID) -> int:
        return int((await self._session.execute(_CHANGES_COUNT, {"id": entity_id})).scalar_one())

    @staticmethod
    def _identifier_candidate(query: str) -> str | None:
        """Zwraca numer, jeżeli zapytanie wygląda na identyfikator rejestrowy."""
        digits = "".join(ch for ch in query if ch.isdigit())
        if digits and (is_valid_nip(digits) or is_valid_regon(digits) or is_valid_krs(digits)):
            return digits
        return None

    async def _fetch(self, statement: Any, params: dict[str, Any]) -> list[Any]:
        if params.get("limit", 1) <= 0:
            return []
        return list((await self._session.execute(statement, params)).mappings().all())

    async def _to_hits(self, rows: list[Any]) -> list[SearchHit]:
        """Dokłada identyfikatory i miasto jednym zapytaniem, nie N+1."""
        if not rows:
            return []
        extra: dict[uuid.UUID, Any] = {}
        enriched = await self._session.execute(_ENRICH, {"ids": [r["id"] for r in rows]})
        for row in enriched.mappings():
            extra[row["id"]] = row
        return [
            SearchHit(
                id=row["id"],
                entity_type=row["entity_type"],
                display_name=row["display_name"],
                score=float(row["score"]),
                subtitle=self._subtitle(extra.get(row["id"])),
                degree=row["degree"],
            )
            for row in rows
        ]

    @staticmethod
    def _subtitle(row: Any | None) -> str | None:
        """Podtytuł wyniku: identyfikatory i miasto, o ile są."""
        if row is None:
            return None
        parts = [
            row.get("krs") and f"KRS {row['krs']}",
            row.get("nip") and f"NIP {row['nip']}",
            row.get("city"),
        ]
        return " · ".join(p for p in parts if p) or None

    async def get_profile(self, entity_id: uuid.UUID) -> dict[str, Any] | None:
        """Profil podmiotu razem z atrybutami typu i licznikiem powiązań."""
        row = (
            (
                await self._session.execute(
                    text(
                        """
                    SELECT
                        e.id, e.entity_type, e.display_name, e.degree, e.merged_into_id,
                        e.created_at, e.updated_at,
                        to_jsonb(c) - 'entity_id' AS company,
                        to_jsonb(p) - 'entity_id' AS person,
                        to_jsonb(a) - 'entity_id' AS address,
                        (SELECT jsonb_agg(jsonb_build_object('scheme', i.scheme, 'value', i.value)
                                          ORDER BY i.scheme)
                         FROM entity_identifiers i WHERE i.entity_id = e.id) AS identifiers
                    FROM entities e
                    LEFT JOIN companies c ON c.entity_id = e.id
                    LEFT JOIN people p ON p.entity_id = e.id
                    LEFT JOIN addresses a ON a.entity_id = e.id
                    WHERE e.id = :id
                    """
                    ),
                    {"id": entity_id},
                )
            )
            .mappings()
            .first()
        )
        return dict(row) if row else None

    async def locate(self, entity_id: uuid.UUID) -> dict[str, Any] | None:
        """Współrzędne adresu podmiotu — z bazy albo z jednorazowego geokodowania.

        Przyjmuje id adresu albo id podmiotu; w drugim przypadku sięga po adres
        wskazany krawędzią `registered_at`.
        """
        row = (
            (
                await self._session.execute(
                    text(
                        """
                    SELECT a.entity_id, a.street, a.building, a.postal_code, a.city,
                           a.latitude, a.longitude, e.display_name
                    FROM addresses a
                    JOIN entities e ON e.id = a.entity_id
                    WHERE a.entity_id = :id
                       OR a.entity_id = (
                            SELECT r.target_entity_id FROM relationships r
                            WHERE r.source_entity_id = :id
                              AND r.relationship_type = 'registered_at'
                              AND r.superseded_at IS NULL
                            ORDER BY (r.valid_to IS NULL) DESC, r.valid_from DESC NULLS LAST
                            LIMIT 1)
                    LIMIT 1
                    """
                    ),
                    {"id": entity_id},
                )
            )
            .mappings()
            .first()
        )

        if row is None:
            return None
        if row["latitude"] is not None and row["longitude"] is not None:
            return {
                "latitude": float(row["latitude"]),
                "longitude": float(row["longitude"]),
                "label": row["display_name"],
            }

        from business_osint.etl.sources.geocoder import Geocoder

        geocoder = Geocoder()
        try:
            coordinates = await geocoder.locate(
                street=row["street"],
                building=row["building"],
                postal_code=row["postal_code"],
                city=row["city"],
            )
        finally:
            await geocoder.aclose()

        if coordinates is None:
            return None

        await self._session.execute(
            text(
                """
                UPDATE addresses SET latitude = :lat, longitude = :lon, geocoded_at = now()
                WHERE entity_id = :id
                """
            ),
            {"lat": coordinates.latitude, "lon": coordinates.longitude, "id": row["entity_id"]},
        )
        await self._session.commit()
        return {
            "latitude": coordinates.latitude,
            "longitude": coordinates.longitude,
            "label": row["display_name"],
        }

    async def financials(self, entity_id: uuid.UUID) -> list[dict[str, Any]]:
        """Sprawozdania finansowe podmiotu, od najnowszego."""
        rows = await self._session.execute(
            text(
                """
                SELECT period_from, period_to, revenue, costs, income, loss,
                       tax_base, tax_due, currency
                FROM financial_reports
                WHERE entity_id = :id
                ORDER BY period_to DESC
                """
            ),
            {"id": entity_id},
        )
        return [dict(row) for row in rows.mappings()]

    async def count_relationships(
        self, entity_id: uuid.UUID, *, include_historical: bool = True
    ) -> int:
        """Ile powiązań ma podmiot. Liczymy dokładnie, bo to jedno tanie zapytanie.

        `entities.degree` tu nie wystarczy: liczy obie strony krawędzi bez
        filtra historyczności, a zakładka pokazuje kierunek wychodzący i potrafi
        ukryć zakończone. Podanie stopnia jako liczby wyników byłoby liczbą
        wyglądającą na prawdziwą.
        """
        return int(
            (
                await self._session.execute(
                    text("""
                    SELECT count(*)
                    FROM graph_edges e
                    JOIN entities n ON n.id = e.to_id AND n.merged_into_id IS NULL
                    WHERE e.from_id = :id
                      AND e.superseded_at IS NULL
                      AND (:include_historical
                           OR e.valid_to IS NULL OR e.valid_to >= CURRENT_DATE)
                    """),
                    {"id": entity_id, "include_historical": include_historical},
                )
            ).scalar_one()
        )

    async def relationships(
        self,
        entity_id: uuid.UUID,
        *,
        include_historical: bool = True,
        limit: int = 200,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Płaska lista powiązań podmiotu wraz z provenance — do zakładki „Powiązania”."""
        rows = (
            (
                await self._session.execute(
                    text(
                        """
                    SELECT
                        e.relationship_id, e.direction, e.relationship_type, e.role,
                        e.valid_from, e.valid_to, e.confidence,
                        e.attributes, n.id AS other_id, n.entity_type AS other_type,
                        n.display_name AS other_name,
                        (SELECT jsonb_agg(jsonb_build_object(
                                    'source', s.kind,
                                    'external_id', d.external_id,
                                    'url', d.url,
                                    'fetched_at', d.fetched_at,
                                    'locator', rs.locator))
                         FROM relationship_sources rs
                         JOIN raw_documents d ON d.id = rs.raw_document_id
                         JOIN sources s ON s.id = d.source_id
                         WHERE rs.relationship_id = e.relationship_id) AS provenance
                    FROM graph_edges e
                    JOIN entities n ON n.id = e.to_id AND n.merged_into_id IS NULL
                    WHERE e.from_id = :id
                      AND e.superseded_at IS NULL
                      AND (:include_historical OR e.valid_to IS NULL OR e.valid_to >= CURRENT_DATE)
                    ORDER BY (e.valid_to IS NULL) DESC, e.valid_from DESC NULLS LAST,
                             e.relationship_id
                    LIMIT :limit OFFSET :offset
                    """
                    ),
                    {
                        "id": entity_id,
                        "include_historical": include_historical,
                        "limit": limit,
                        "offset": offset,
                    },
                )
            )
            .mappings()
            .all()
        )
        return [dict(row) for row in rows]


# „Kto jeszcze siedzi pod tym adresem" jest w tym produkcie pytaniem pierwszej
# kategorii, nie ciekawostką: wspólny adres to najczęstszy widoczny ślad
# powiązania między spółkami, których nie łączy ani wspólnik, ani nazwa.
#
# Zapytanie przyjmuje **id podmiotu albo id adresu**. Użytkownik ogląda profil
# firmy i chce sąsiadów jej siedziby; wymaganie, żeby najpierw kliknął w adres,
# byłoby przerzuceniem na niego pracy, którą baza umie wykonać jednym złączeniem.
_CO_LOCATED = text("""
    WITH adres AS (
        SELECT CASE
                 WHEN EXISTS (SELECT 1 FROM addresses a WHERE a.entity_id = :id) THEN :id
                 ELSE (SELECT r.target_entity_id FROM relationships r
                       WHERE r.source_entity_id = :id
                         AND r.relationship_type = 'registered_at'
                         AND r.superseded_at IS NULL
                       ORDER BY (r.valid_to IS NULL) DESC, r.valid_from DESC NULLS LAST
                       LIMIT 1)
               END AS id
    )
    SELECT e.id, e.entity_type, e.display_name, e.degree,
           c.nip, c.krs, c.status, r.valid_from, r.valid_to
    FROM adres
    JOIN relationships r ON r.target_entity_id = adres.id
                        AND r.relationship_type = 'registered_at'
                        AND r.superseded_at IS NULL
    JOIN entities e ON e.id = r.source_entity_id AND e.merged_into_id IS NULL
    LEFT JOIN companies c ON c.entity_id = e.id
    WHERE e.id <> :id
    ORDER BY (r.valid_to IS NULL) DESC, e.degree DESC, e.display_name
    LIMIT :limit OFFSET :offset
""")

_CO_LOCATED_COUNT = text("""
    WITH adres AS (
        SELECT CASE
                 WHEN EXISTS (SELECT 1 FROM addresses a WHERE a.entity_id = :id) THEN :id
                 ELSE (SELECT r.target_entity_id FROM relationships r
                       WHERE r.source_entity_id = :id
                         AND r.relationship_type = 'registered_at'
                         AND r.superseded_at IS NULL
                       ORDER BY (r.valid_to IS NULL) DESC, r.valid_from DESC NULLS LAST
                       LIMIT 1)
               END AS id
    )
    SELECT count(*)
    FROM adres
    JOIN relationships r ON r.target_entity_id = adres.id
                        AND r.relationship_type = 'registered_at'
                        AND r.superseded_at IS NULL
    JOIN entities e ON e.id = r.source_entity_id AND e.merged_into_id IS NULL
    WHERE e.id <> :id
""")


# Kanał zmian łączy dwa **różne** źródła prawdy i to jest jego istota.
#
# Zmiany atrybutów muszą być logowane w chwili zapisu, bo import nadpisuje je
# w miejscu — bez dziennika poprzednia wartość znika bezpowrotnie.
#
# Zmiany powiązań są odtwarzalne **wstecz**, bo relacje są bitemporalne:
# `recorded_at` mówi, kiedy fakt do nas trafił, a `superseded_at`, kiedy
# przestał obowiązywać. Dublowanie ich w dzienniku podwoiłoby zapis przy
# imporcie milionów krawędzi i nie dołożyło ani jednej informacji.
#
# Dlatego dziennik obejmuje tylko to, czego inaczej nie da się odzyskać —
# a odczyt scala jedno z drugim w jedną oś czasu.
_CHANGES = text("""
    (
        SELECT c.observed_at, c.field AS rodzaj, c.old_value AS z, c.new_value AS na,
               NULL::text AS podmiot, c.id AS kolejnosc
        FROM entity_changes c
        WHERE c.entity_id = :id
    )
    UNION ALL
    (
        SELECT r.recorded_at, 'powiazanie_dodane', NULL, r.relationship_type,
               e.display_name, NULL::bigint
        FROM relationships r
        JOIN entities e ON e.id = CASE WHEN r.source_entity_id = :id
                                       THEN r.target_entity_id ELSE r.source_entity_id END
        WHERE (r.source_entity_id = :id OR r.target_entity_id = :id)
    )
    UNION ALL
    (
        SELECT r.superseded_at, 'powiazanie_zamkniete', r.relationship_type, NULL,
               e.display_name, NULL::bigint
        FROM relationships r
        JOIN entities e ON e.id = CASE WHEN r.source_entity_id = :id
                                       THEN r.target_entity_id ELSE r.source_entity_id END
        WHERE (r.source_entity_id = :id OR r.target_entity_id = :id)
          AND r.superseded_at IS NOT NULL
    )
    -- `now()` w PostgreSQL zwraca czas **rozpoczęcia transakcji**, więc wszystkie
    -- zmiany z jednego importu mają identyczny znacznik. To jest użyteczne —
    -- widać, co przyszło razem — ale nie porządkuje ich między sobą. Remis
    -- rozstrzyga rosnący klucz dziennika.
    ORDER BY observed_at DESC, kolejnosc DESC NULLS LAST
    LIMIT :limit OFFSET :offset
""")

_CHANGES_COUNT = text("""
    SELECT
        (SELECT count(*) FROM entity_changes WHERE entity_id = :id)
      + (SELECT count(*) FROM relationships
         WHERE source_entity_id = :id OR target_entity_id = :id)
      + (SELECT count(*) FROM relationships
         WHERE (source_entity_id = :id OR target_entity_id = :id)
           AND superseded_at IS NOT NULL)
""")
