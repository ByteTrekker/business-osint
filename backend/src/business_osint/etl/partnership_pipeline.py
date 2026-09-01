"""Spółki cywilne z CEIDG — pierwsze powiązania między osobami.

Dlaczego to jest ważne mimo skromnej skali: w grafie jest dziś 6,4 mln krawędzi,
z czego 99,6% to `sole_proprietor_of` (relacja jeden do jednego, czyli druga
etykieta na tym samym wierzchołku) albo `registered_at` (adres). Podmiotów
z jakimkolwiek innym powiązaniem jest 16 182 na 3,6 mln — 0,45%. Spółki cywilne
są **jedynym** dostępnym dziś legalnie źródłem krawędzi osoba–osoba.

Model: spółka cywilna nie ma osobowości prawnej, ale **ma NIP i REGON**, więc
zakładamy dla niej encję i wiążemy wspólników krawędzią `partner_in`. Dwóch
wspólników tej samej spółki jest wtedy w odległości dwóch skoków, a zapytanie
„kto jeszcze jest w tej spółce" sprowadza się do sąsiadów węzła.

Skąd NIP spółki: **wyłącznie z pojedynczego wpisu** `/firma?nip=`. Raport
zbiorczy CEIDG ma 24 kolumny i żadna nie identyfikuje spółki — `StatusDzialalnosci`
mówi tylko „prowadzona wyłącznie w formie spółki cywilnej", czyli że ktoś
w jakiejś jest, nie z kim. Punkt zbiorczy `/firmy` przyjmuje pięć NIP-ów naraz,
ale pola `spolki` nie zwraca, więc partia nic by nie dała.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import json
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from business_osint.config import get_settings
from business_osint.db.session import get_etl_sessionmaker
from business_osint.domain.enums import Confidence, EntityType, RelationshipType, SourceKind
from business_osint.etl.loaders import store_raw_document
from business_osint.etl.pipeline import get_or_create_source
from business_osint.etl.sources.ceidg_reports import CeidgEntryClient, spolki_z_wpisu

#: Po tylu nieudanych wpisach z rzędu przerywamy przebieg — źródło, które
#: przestało odpowiadać, ma zatrzymać pracę, a nie mielić ją bez efektu.
#: Zadziałało już raz: przy `429` z CEIDG przerwało po 20 zamiast po 96 tysiącach.
MAX_KOLEJNYCH_BLEDOW = 20

#: Ile wpisów pobieramy równolegle.
#:
#: Limiter i tak trzyma tempo poniżej limitu rejestru, więc współbieżność nie
#: podnosi obciążenia serwera — likwiduje tylko **jałowe czekanie**. Przebieg
#: sekwencyjny wykorzystywał 453 zapytania na godzinę z dozwolonych 900: po
#: każdym żądaniu czekał najpierw na odpowiedź, a potem jeszcze na limiter.
#:
#: Paczkami, nie strumieniem: punktem wznowienia jest ostatni przetworzony NIP,
#: a przy odpowiedziach kończących się poza kolejnością „ostatni" przestałby
#: znaczyć „wszystko przed nim gotowe". Zapisujemy go dopiero, gdy cała paczka
#: się domknie.
ROWNOLEGLE = 4


@dataclass(slots=True)
class PartnershipStats:
    checked: int = 0
    partnerships_created: int = 0
    edges_created: int = 0
    without_partnership: int = 0
    errors: int = 0
    last_nip: str = ""
    aborted: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "checked": self.checked,
            "partnerships_created": self.partnerships_created,
            "edges_created": self.edges_created,
            "without_partnership": self.without_partnership,
            "errors": self.errors,
            "last_nip": self.last_nip,
            "aborted": self.aborted,
        }


#: Wpisy oznaczone jako prowadzone wyłącznie w formie spółki cywilnej.
#: `owner_id` to encja osoby — to ona jest wspólnikiem, nie jej działalność.
_DO_SPRAWDZENIA = text("""
    SELECT i.value AS nip, r.source_entity_id AS osoba
    FROM companies c
    JOIN entity_identifiers i ON i.entity_id = c.entity_id AND i.scheme = 'nip'
    JOIN relationships r ON r.target_entity_id = c.entity_id
                        AND r.relationship_type = 'sole_proprietor_of'
                        AND r.superseded_at IS NULL
    WHERE c.attributes ->> 'status_raw' ILIKE '%cywiln%'
      AND (CAST(:after AS text) IS NULL OR i.value > CAST(:after AS text))
    ORDER BY i.value
    LIMIT CAST(:limit AS bigint)
""")

_SPOLKA_PO_NIP = text("""
    SELECT entity_id FROM entity_identifiers WHERE scheme = 'nip' AND value = :nip
""")

_ISTNIEJE_KRAWEDZ = text("""
    SELECT 1 FROM relationships
    WHERE source_entity_id = :osoba AND target_entity_id = :spolka
      AND relationship_type = 'partner_in' AND superseded_at IS NULL
""")


async def _spolka_entity(session: AsyncSession, *, nip: str, regon: str) -> tuple[uuid.UUID, bool]:
    """Encja spółki cywilnej. Zwraca (id, czy właśnie powstała).

    Spółka bywa **już w bazie** jako wpis CEIDG — niektóre spółki cywilne mają
    własny wpis. Wtedy jej nie dublujemy, tylko dowiązujemy się do istniejącej:
    ten sam NIP to ta sama spółka, co jest twardym identyfikatorem w rozumieniu
    niezmiennika N4.
    """
    istniejaca = (await session.execute(_SPOLKA_PO_NIP, {"nip": nip})).scalar_one_or_none()
    if istniejaca is not None:
        return uuid.UUID(str(istniejaca)), False

    entity_id = uuid.uuid4()
    nazwa = f"Spółka cywilna NIP {nip}"
    await session.execute(
        text("""
            INSERT INTO entities (id, entity_type, display_name, normalized_name, degree)
            VALUES (:id, :typ, :nazwa, :norm, 0)
        """),
        {"id": entity_id, "typ": EntityType.COMPANY.value, "nazwa": nazwa, "norm": nazwa.lower()},
    )
    await session.execute(
        text("INSERT INTO companies (entity_id, legal_form, regon) VALUES (:id, :forma, :regon)"),
        {"id": entity_id, "forma": "spółka cywilna", "regon": regon or None},
    )
    await session.execute(
        text("""
            INSERT INTO entity_identifiers (id, entity_id, scheme, value)
            VALUES (gen_random_uuid(), :id, 'nip', :nip)
            ON CONFLICT ON CONSTRAINT uq_entity_identifiers_scheme_value DO NOTHING
        """),
        {"id": entity_id, "nip": nip},
    )
    return entity_id, True


async def import_partnerships(
    *, limit: int | None = None, after: str | None = None, progress: Any = None
) -> PartnershipStats:
    """Dopina wspólników do ich spółek cywilnych.

    `after` wznawia przebieg — pełny to 97 425 wpisów i kilka dób, więc
    przerwanie nie może oznaczać startu od zera.
    """
    stats = PartnershipStats()
    token = get_settings().ceidg_token or ""
    if not token:
        stats.aborted = "brak tokenu CEIDG w konfiguracji"
        return stats

    factory = get_etl_sessionmaker()
    async with factory() as session:
        cele = (await session.execute(_DO_SPRAWDZENIA, {"limit": limit, "after": after})).all()

    client = CeidgEntryClient(token)
    pod_rzad = 0
    try:
        for poczatek in range(0, len(cele), ROWNOLEGLE):
            paczka = cele[poczatek : poczatek + ROWNOLEGLE]
            wyniki = await asyncio.gather(
                *(client.fetch(cel.nip) for cel in paczka), return_exceptions=True
            )

            przerwij = False
            for cel, wynik in zip(paczka, wyniki, strict=True):
                if isinstance(wynik, BaseException):
                    stats.errors += 1
                    pod_rzad += 1
                    if pod_rzad >= MAX_KOLEJNYCH_BLEDOW:
                        stats.aborted = f"{MAX_KOLEJNYCH_BLEDOW} błędów z rzędu: {wynik}"
                        przerwij = True
                        break
                    continue
                pod_rzad = 0
                stats.checked += 1
                await _zapisz(factory, cel=cel, firma=wynik, stats=stats)

            # Dopiero teraz: cała paczka się domknęła, więc wszystko do tego
            # numeru jest naprawdę przetworzone i wznowienie go nie pominie.
            if przerwij:
                break
            stats.last_nip = paczka[-1].nip
            if progress is not None:
                progress(stats)
    finally:
        await client.aclose()
    return stats


async def _zapisz(
    factory: Any, *, cel: Any, firma: dict[str, Any] | None, stats: PartnershipStats
) -> None:
    """Zapisuje jeden wpis: dokument źródłowy, encję spółki i krawędzie."""
    spolki = spolki_z_wpisu(firma)
    if not spolki:
        stats.without_partnership += 1
        return

    async with factory() as session, session.begin():
        source_id = await get_or_create_source(
            session, SourceKind.CEIDG, "dane.biznes.gov.pl", "https://dane.biznes.gov.pl"
        )
        # Suma kontrolna z treści, bo `store_raw_document` dedupuje po niej —
        # ponowny przebieg nie ma tworzyć drugiego snapshotu tego samego wpisu.
        tresc = json.dumps(firma, ensure_ascii=False, sort_keys=True)
        raw_id, _ = await store_raw_document(
            session,
            source_id=source_id,
            external_id=f"ceidg/firma/{cel.nip}",
            url=f"https://dane.biznes.gov.pl/api/ceidg/v3/firma?nip={cel.nip}",
            fetched_at=dt.datetime.now(dt.UTC),
            content_sha256=hashlib.sha256(tresc.encode()).hexdigest(),
            payload=firma or {},
        )
        for nip_spolki, regon in spolki:
            spolka_id, nowa = await _spolka_entity(session, nip=nip_spolki, regon=regon)
            if nowa:
                stats.partnerships_created += 1
            stats.edges_created += await _dopnij(
                session, osoba=cel.osoba, spolka=spolka_id, raw_id=raw_id
            )


async def _dopnij(
    session: AsyncSession, *, osoba: uuid.UUID, spolka: uuid.UUID, raw_id: uuid.UUID
) -> int:
    """Krawędź wspólnik → spółka, wraz z pochodzeniem (niezmiennik N2)."""
    if (await session.execute(_ISTNIEJE_KRAWEDZ, {"osoba": osoba, "spolka": spolka})).first():
        return 0
    rel_id = (
        await session.execute(
            text("""
                INSERT INTO relationships
                    (id, source_entity_id, target_entity_id, relationship_type, confidence)
                VALUES (gen_random_uuid(), :osoba, :spolka, :typ, :pewnosc)
                RETURNING id
            """),
            {
                "osoba": osoba,
                "spolka": spolka,
                "typ": RelationshipType.PARTNER_IN.value,
                "pewnosc": Confidence.REGISTERED.value,
            },
        )
    ).scalar_one()
    await session.execute(
        text("""
            INSERT INTO relationship_sources (relationship_id, raw_document_id, locator)
            VALUES (:rel, :raw, 'spolki')
        """),
        {"rel": rel_id, "raw": raw_id},
    )
    return 1
