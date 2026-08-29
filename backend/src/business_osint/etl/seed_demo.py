"""Syntetyczny zestaw demonstracyjny.

Cel: `docker compose up` + `business-osint seed` ma dać działającą aplikację
bez dostępu do rejestrów. Dane są zmyślone — żadnych prawdziwych osób.

Zestaw celowo zawiera przypadki brzegowe, które chcemy widzieć w UI:
* łańcuch Firma A -> osoba -> Firma B -> osoba -> Firma C (główny scenariusz),
* powiązanie historyczne (zakończone w 2023),
* dwie różne osoby o identycznym imieniu i nazwisku (entity resolution),
* adres-hub z 200 spółkami (wirtualne biuro — test budżetu grafu).
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from business_osint.db.models import (
    Address,
    Company,
    Entity,
    EntityIdentifier,
    Person,
    RawDocument,
    Relationship,
    RelationshipSource,
)
from business_osint.db.session import get_sessionmaker
from business_osint.domain.enums import (
    Confidence,
    EntityType,
    IdentifierScheme,
    RelationshipType,
    SourceKind,
)
from business_osint.domain.normalization import normalize_company_name, normalize_person_name
from business_osint.etl.maintenance import recompute_degrees
from business_osint.etl.pipeline import get_or_create_source

HUB_COMPANY_COUNT = 200


def _nip_with_checksum(prefix9: str) -> str:
    """Syntetyczny NIP z poprawną sumą kontrolną (dane demo muszą przejść walidację).

    Dla ~1/11 prefiksów reszta wynosi 10 i cyfry kontrolnej nie da się zapisać —
    wtedy inkrementujemy prefiks, zamiast produkować niepoprawny numer.
    """
    weights = (6, 5, 7, 2, 3, 4, 5, 6, 7)
    candidate = int(prefix9)
    for _ in range(11):
        digits = f"{candidate:09d}"
        control = sum(int(d) * w for d, w in zip(digits, weights, strict=True)) % 11
        if control != 10:
            return digits + str(control)
        candidate += 1
    raise RuntimeError("nie udało się wygenerować poprawnego NIP")


async def run_seed(*, demo: bool = True) -> None:
    if not demo:
        return
    async with get_sessionmaker()() as session, session.begin():
        await _clear(session)
        await _build(session)
    await recompute_degrees()


async def _clear(session: AsyncSession) -> None:
    await session.execute(
        text(
            "TRUNCATE relationship_sources, entity_sources, relationships, "
            "entity_identifiers, companies, people, addresses, entities, "
            "raw_documents, ingestion_runs, sources RESTART IDENTITY CASCADE"
        )
    )


async def _build(session: AsyncSession) -> None:
    source_id = await get_or_create_source(
        session, SourceKind.MANUAL, "seed-demo", "https://example.invalid"
    )
    document = RawDocument(
        id=uuid.uuid4(),
        source_id=source_id,
        external_id="seed-demo-2026",
        url="https://example.invalid/seed",
        fetched_at=dt.datetime.now(dt.UTC),
        content_sha256="0" * 64,
        payload={"note": "dane demonstracyjne, nie pochodzą z rejestru"},
    )
    session.add(document)
    await session.flush()

    def company(name: str, krs: str, nip: str, city: str) -> uuid.UUID:
        entity_id = uuid.uuid4()
        session.add(
            Entity(
                id=entity_id,
                entity_type=EntityType.COMPANY,
                display_name=name,
                normalized_name=normalize_company_name(name),
                blocking_key=normalize_company_name(name).replace(" ", "")[:12],
            )
        )
        session.add(
            Company(
                entity_id=entity_id,
                krs=krs,
                nip=nip,
                legal_form="sp_zoo",
                status="active",
                registered_on=dt.date(2015, 3, 1),
                attributes={"city": city},
            )
        )
        session.add(EntityIdentifier(id=uuid.uuid4(), entity_id=entity_id,
                                     scheme=IdentifierScheme.KRS, value=krs))
        session.add(EntityIdentifier(id=uuid.uuid4(), entity_id=entity_id,
                                     scheme=IdentifierScheme.NIP, value=nip))
        return entity_id

    def person(first: str, last: str, birth_year: int | None) -> uuid.UUID:
        entity_id = uuid.uuid4()
        display = f"{first} {last}"
        session.add(
            Entity(
                id=entity_id,
                entity_type=EntityType.PERSON,
                display_name=display,
                normalized_name=normalize_person_name(display),
                blocking_key=f"{first.lower()}|{last.lower()}|{birth_year or ''}",
            )
        )
        session.add(
            Person(
                entity_id=entity_id, first_names=first, last_name=last, birth_year=birth_year
            )
        )
        return entity_id

    def address(street: str, city: str, postal: str) -> uuid.UUID:
        entity_id = uuid.uuid4()
        display = f"{street}, {postal} {city}"
        session.add(
            Entity(
                id=entity_id,
                entity_type=EntityType.ADDRESS,
                display_name=display,
                normalized_name=normalize_person_name(display),
            )
        )
        session.add(
            Address(
                entity_id=entity_id,
                city=city,
                street=street,
                postal_code=postal,
                normalized=normalize_person_name(display).replace(" ", ""),
            )
        )
        return entity_id

    edges: list[Relationship] = []

    def edge(
        src: uuid.UUID,
        dst: uuid.UUID,
        rel_type: RelationshipType,
        role: str | None = None,
        valid_from: dt.date | None = None,
        valid_to: dt.date | None = None,
        attributes: dict | None = None,
    ) -> None:
        edges.append(
            Relationship(
                id=uuid.uuid4(),
                source_entity_id=src,
                target_entity_id=dst,
                relationship_type=rel_type,
                role=role,
                valid_from=valid_from,
                valid_to=valid_to,
                confidence=Confidence.REGISTERED,
                confidence_score=1.0,
                attributes=attributes or {},
            )
        )

    # --- główny scenariusz z opisu produktu ---
    firma_a = company("ALFA TECHNOLOGIE Sp. z o.o.", "0000111111", "5252445170", "Warszawa")
    firma_b = company("BETA LOGISTYKA Sp. z o.o.", "0000222222", "7010012356", "Poznań")
    firma_c = company("GAMMA INVEST S.A.", "0000333333", "1132456789", "Warszawa")

    kowalski = person("Jan", "Kowalski", 1975)
    nowak = person("Anna", "Nowak", 1982)
    # Imiennik — ta sama nazwa, inna osoba. Nie wolno tego scalić automatycznie.
    kowalski_imiennik = person("Jan", "Kowalski", 1990)

    edge(kowalski, firma_a, RelationshipType.BOARD_MEMBER_OF, "PREZES ZARZĄDU",
         dt.date(2018, 5, 12))
    edge(kowalski, firma_b, RelationshipType.SHAREHOLDER_OF, "WSPÓLNIK", dt.date(2019, 1, 8),
         attributes={"share_percent": 40})
    # Powiązanie historyczne — było, minęło. Widoczne dopiero z include_historical=true.
    edge(kowalski, firma_c, RelationshipType.BOARD_MEMBER_OF, "CZŁONEK ZARZĄDU",
         dt.date(2020, 2, 1), dt.date(2023, 6, 30))
    edge(nowak, firma_b, RelationshipType.BOARD_MEMBER_OF, "PREZES ZARZĄDU", dt.date(2021, 9, 1))
    edge(nowak, firma_c, RelationshipType.SHAREHOLDER_OF, "AKCJONARIUSZ", dt.date(2022, 4, 15),
         attributes={"share_percent": 51})
    edge(kowalski_imiennik, firma_c, RelationshipType.PROXY_OF, "PROKURENT", dt.date(2024, 1, 10))
    edge(firma_c, firma_a, RelationshipType.PARENT_OF, "PODMIOT DOMINUJĄCY", dt.date(2021, 7, 1),
         attributes={"share_percent": 75})

    biuro = address("Aleje Jerozolimskie 100", "Warszawa", "00-807")
    edge(firma_a, biuro, RelationshipType.REGISTERED_AT, valid_from=dt.date(2015, 3, 1))
    edge(firma_c, biuro, RelationshipType.REGISTERED_AT, valid_from=dt.date(2016, 1, 1))

    # --- adres-hub: wirtualne biuro z setkami spółek ---
    hub = address("Ulica Wirtualna 1", "Warszawa", "01-001")
    for i in range(HUB_COMPANY_COUNT):
        shell = company(
            f"SPÓŁKA WIDMO {i:03d} Sp. z o.o.",
            f"00009{i:05d}",
            _nip_with_checksum(f"999{i * 16:06d}"),
            "Warszawa",
        )
        edge(shell, hub, RelationshipType.REGISTERED_AT, valid_from=dt.date(2022, 1, 1))
    edge(firma_b, hub, RelationshipType.REGISTERED_AT, valid_from=dt.date(2020, 1, 1))

    session.add_all(edges)
    await session.flush()

    session.add_all(
        RelationshipSource(
            relationship_id=e.id,
            raw_document_id=document.id,
            locator="/seed/demo",
        )
        for e in edges
    )
    await session.flush()
