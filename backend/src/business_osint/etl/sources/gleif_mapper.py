"""Mapowanie rekordów GLEIF na encje i relacje.

Czysta funkcja: JSON/CSV -> struktury dziedzinowe. Bez bazy i bez sieci.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from business_osint.domain.enums import EntityType, IdentifierScheme, RelationshipType
from business_osint.domain.normalization import (
    is_valid_krs,
    is_valid_nip,
    is_valid_regon,
    normalize_company_name,
)
from business_osint.etl.sources.krs_mapper import (
    ParsedDocument,
    ParsedEntity,
    ParsedRelationship,
)

#: Typy relacji GLEIF, które przekładamy na krawędź „podmiot dominujący".
PARENT_RELATIONSHIP_TYPES = frozenset(
    {"IS_DIRECTLY_CONSOLIDATED_BY", "IS_ULTIMATELY_CONSOLIDATED_BY", "IS_SUBFUND_OF"}
)


def _identifier_scheme(value: str | None) -> IdentifierScheme | None:
    """GLEIF podaje krajowy identyfikator bez informacji, co to za schemat.

    Rozpoznajemy go po kształcie i sumie kontrolnej. Kluczowa reguła: **numer
    KRS jest dopełniany zerami do dziesięciu cyfr, a NIP nigdy nie zaczyna się
    od zera** (pierwsze trzy cyfry to kod urzędu skarbowego). Bez tej reguły
    co jedenasty numer KRS przypadkiem przechodzi sumę kontrolną NIP i zostaje
    zapisany jako cudzy NIP — a to prowadzi wprost do fałszywego scalenia
    dwóch różnych podmiotów, czyli do złamania niezmiennika N4.
    """
    if not value:
        return None
    digits = "".join(ch for ch in value if ch.isdigit())
    if len(digits) == 10 and digits.startswith("0"):
        return IdentifierScheme.KRS if is_valid_krs(digits) else None
    if len(digits) == 10 and is_valid_nip(digits):
        return IdentifierScheme.NIP
    if len(digits) in (9, 14) and is_valid_regon(digits):
        return IdentifierScheme.REGON
    return None


def parse_lei_page(payload: dict[str, Any]) -> ParsedDocument:
    """Strona rekordów LEI -> encje typu ``company`` z identyfikatorami."""
    result = ParsedDocument()
    for record in payload.get("data") or []:
        entity = _parse_lei_record(record)
        if entity is not None:
            result.entities.append(entity)
            address = _parse_address(record)
            if address is not None:
                result.entities.append(address)
                result.relationships.append(
                    ParsedRelationship(
                        source_key=entity.local_key,
                        target_key=address.local_key,
                        relationship_type=RelationshipType.REGISTERED_AT,
                        locator=f"/data/{record.get('id')}/attributes/entity/legalAddress",
                    )
                )
    return result


def parse_lei_registrations(payload: dict[str, Any]) -> list[dict[str, str | None]]:
    """Numer LEI razem ze **stanem rejestracji** i nazwą, pod którą go wydano.

    GLEIF nie gwarantuje jednego LEI na podmiot: wystawia rekordy oznaczone
    `DUPLICATE`, a rekord `LAPSED` zostaje pod **dawną nazwą** spółki po zmianie
    firmy. W bazie mamy 21 832 takich rekordów na 57 959 — czyli ponad jedna
    trzecia numerów LEI opisuje stan, który już nie obowiązuje.

    Bez tego pola dwa LEI-e przy jednej spółce wyglądają jak błąd scalania,
    a są normalnym stanem rejestru. Przy okazji rekord wygasły niesie historię
    nazwy dla podmiotów, których nie mamy w KRS.
    """
    records: list[dict[str, str | None]] = []
    for record in payload.get("data") or []:
        attributes = record.get("attributes") or {}
        lei = attributes.get("lei") or record.get("id")
        if not lei:
            continue
        entity = attributes.get("entity") or {}
        records.append(
            {
                "lei": str(lei),
                "status": (attributes.get("registration") or {}).get("status"),
                "name": (entity.get("legalName") or {}).get("name"),
            }
        )
    return records


def _parse_lei_record(record: dict[str, Any]) -> ParsedEntity | None:
    attributes = record.get("attributes") or {}
    lei = attributes.get("lei") or record.get("id")
    entity = attributes.get("entity") or {}
    name = ((entity.get("legalName") or {}).get("name") or "").strip()
    if not lei or not name:
        return None

    identifiers: dict[IdentifierScheme, str] = {IdentifierScheme.LEI: lei}
    national_id = entity.get("registeredAs")
    scheme = _identifier_scheme(national_id)
    if scheme is not None and national_id:
        identifiers[scheme] = "".join(ch for ch in national_id if ch.isdigit())

    return ParsedEntity(
        entity_type=EntityType.COMPANY,
        display_name=name,
        normalized_name=normalize_company_name(name),
        identifiers=identifiers,
        attributes={
            "status": (entity.get("status") or "").lower() or None,
            "legal_form": ((entity.get("legalForm") or {}).get("id")),
            "jurisdiction": entity.get("jurisdiction"),
            "registered_as": national_id,
        },
        local_key=f"lei:{lei}",
    )


def _parse_address(record: dict[str, Any]) -> ParsedEntity | None:
    entity = (record.get("attributes") or {}).get("entity") or {}
    address = entity.get("legalAddress") or {}
    city = address.get("city")
    if not city:
        return None
    lines = [line for line in (address.get("addressLines") or []) if line]
    display = ", ".join([*lines, address.get("postalCode") or "", city]).replace(", ,", ",")
    normalized = normalize_company_name(display).replace(" ", "")
    return ParsedEntity(
        entity_type=EntityType.ADDRESS,
        display_name=display.strip(", "),
        normalized_name=normalized,
        attributes={
            "city": city,
            "street": lines[0] if lines else None,
            "postal_code": address.get("postalCode"),
            "country": address.get("country") or "PL",
        },
        local_key=f"address:{normalized}",
    )


def _relationship_period(row: dict[str, str]) -> tuple[dt.date | None, dt.date | None]:
    """Okres obowiązywania relacji — a nie okres sprawozdawczy.

    GLEIF zapisuje w tych samych slotach kilka rodzajów okresów
    (``ACCOUNTING_PERIOD``, ``RELATIONSHIP_PERIOD``, ``DOCUMENT_FILING_PERIOD``),
    w kolejności, która nie jest ustalona. Wzięcie na ślepo slotu pierwszego
    daje najczęściej rok obrotowy — a wtedy każda relacja wygląda na zakończoną
    31 grudnia i znika z grafu stanu bieżącego.
    """
    for slot in range(1, 6):
        if (
            row.get(f"Relationship.Period.{slot}.periodType") or ""
        ).strip() != "RELATIONSHIP_PERIOD":
            continue
        return (
            _parse_date(row.get(f"Relationship.Period.{slot}.startDate")),
            _parse_date(row.get(f"Relationship.Period.{slot}.endDate")),
        )
    # Brak okresu relacji oznacza „obowiązuje, początek nieznany", a nie „zakończona".
    return None, None


def parse_relationship_row(row: dict[str, str]) -> ParsedRelationship | None:
    """Wiersz pliku Relationship Records -> krawędź ``parent_of``.

    Kierunek w GLEIF jest odwrotny do naszego: rekord mówi „A jest konsolidowane
    przez B", a my zapisujemy „B jest podmiotem dominującym wobec A".
    """
    rel_type = (row.get("Relationship.RelationshipType") or "").strip()
    if rel_type not in PARENT_RELATIONSHIP_TYPES:
        return None
    child = (row.get("Relationship.StartNode.NodeID") or "").strip()
    parent = (row.get("Relationship.EndNode.NodeID") or "").strip()
    if not child or not parent or child == parent:
        return None
    if (row.get("Relationship.RelationshipStatus") or "").strip() not in ("ACTIVE", ""):
        return None

    valid_from, valid_to = _relationship_period(row)
    return ParsedRelationship(
        source_key=f"lei:{parent}",
        target_key=f"lei:{child}",
        relationship_type=RelationshipType.PARENT_OF,
        role=rel_type,
        valid_from=valid_from,
        valid_to=valid_to,
        attributes={"gleif_relationship_type": rel_type},
        locator=f"rr/{child}/{rel_type}",
    )


def _parse_date(value: str | None) -> dt.date | None:
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return None
