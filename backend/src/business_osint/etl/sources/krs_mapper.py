"""Mapowanie odpisu KRS na encje i relacje.

Mapper jest CZYSTĄ funkcją: JSON -> struktury dziedzinowe. Bez bazy, bez sieci.
Dzięki temu regresje testuje się na zapisanych plikach JSON (fixture'ach),
a zmiana schematu po stronie ministerstwa objawia się czerwonym testem,
a nie ciszą i pustym grafem.

Ostrzeżenie: kształt JSON-a z api-krs.ms.gov.pl trzeba potwierdzić na żywym
odpisie — poniższe ścieżki odpowiadają strukturze `odpis.dane.dzialN.*`.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

from business_osint.domain.enums import EntityType, IdentifierScheme, RelationshipType
from business_osint.domain.normalization import normalize_company_name, normalize_person_name

#: Mapowanie nazw organów KRS na typ relacji.
ORGAN_TO_RELATION = {
    "ZARZĄD": RelationshipType.BOARD_MEMBER_OF,
    "RADA NADZORCZA": RelationshipType.SUPERVISORY_MEMBER_OF,
    "KOMISJA REWIZYJNA": RelationshipType.SUPERVISORY_MEMBER_OF,
    "PROKURA": RelationshipType.PROXY_OF,
    "LIKWIDATOR": RelationshipType.LIQUIDATOR_OF,
}


@dataclass(slots=True)
class ParsedEntity:
    entity_type: EntityType
    display_name: str
    normalized_name: str
    identifiers: dict[IdentifierScheme, str] = field(default_factory=dict)
    attributes: dict[str, Any] = field(default_factory=dict)
    #: Klucz lokalny w obrębie dokumentu — spina encje z relacjami przed zapisem.
    local_key: str = ""


@dataclass(slots=True)
class ParsedRelationship:
    source_key: str
    target_key: str
    relationship_type: RelationshipType
    role: str | None = None
    valid_from: dt.date | None = None
    valid_to: dt.date | None = None
    attributes: dict[str, Any] = field(default_factory=dict)
    #: JSON Pointer do miejsca w odpisie, z którego wzięliśmy fakt.
    locator: str | None = None


@dataclass(slots=True)
class ParsedDocument:
    entities: list[ParsedEntity] = field(default_factory=list)
    relationships: list[ParsedRelationship] = field(default_factory=list)


def _get(data: dict, *path: str, default: Any = None) -> Any:
    node: Any = data
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return default
        node = node[key]
    return node


def _parse_date(value: str | None) -> dt.date | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return dt.datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def parse_krs_document(payload: dict) -> ParsedDocument:
    """Zamienia odpis KRS na listę encji i relacji gotowych do zapisu."""
    root = _get(payload, "odpis", "dane", default={})
    result = ParsedDocument()

    company = _parse_company(root)
    if company is None:
        return result
    result.entities.append(company)

    address = _parse_address(root)
    if address is not None:
        result.entities.append(address)
        result.relationships.append(
            ParsedRelationship(
                source_key=company.local_key,
                target_key=address.local_key,
                relationship_type=RelationshipType.REGISTERED_AT,
                locator="/odpis/dane/dzial1/siedzibaIAdres",
            )
        )

    result.entities.extend(_parse_people(root, company, result.relationships))
    result.entities.extend(_parse_shareholders(root, company, result.relationships))
    return result


def _parse_company(root: dict) -> ParsedEntity | None:
    dane = _get(root, "dzial1", "danePodmiotu", default={})
    name = dane.get("nazwa")
    if not name:
        return None
    krs = _get(root, "naglowekA", "numerKRS") or dane.get("numerKRS")
    identyfikatory = dane.get("identyfikatory", {})
    identifiers: dict[IdentifierScheme, str] = {}
    if krs:
        identifiers[IdentifierScheme.KRS] = krs
    if nip := identyfikatory.get("nip"):
        identifiers[IdentifierScheme.NIP] = nip
    if regon := identyfikatory.get("regon"):
        identifiers[IdentifierScheme.REGON] = regon
    return ParsedEntity(
        entity_type=EntityType.COMPANY,
        display_name=name,
        normalized_name=normalize_company_name(name),
        identifiers=identifiers,
        attributes={
            "legal_form": dane.get("formaPrawna"),
            "registered_on": _get(root, "naglowekA", "dataRejestracjiWKRS"),
        },
        local_key=f"company:{krs or normalize_company_name(name)}",
    )


def _parse_address(root: dict) -> ParsedEntity | None:
    adres = _get(root, "dzial1", "siedzibaIAdres", "adres", default={})
    siedziba = _get(root, "dzial1", "siedzibaIAdres", "siedziba", default={})
    city = adres.get("miejscowosc") or siedziba.get("miejscowosc")
    if not city:
        return None
    parts = [
        adres.get("ulica"),
        adres.get("nrDomu"),
        adres.get("nrLokalu"),
        adres.get("kodPocztowy"),
        city,
    ]
    display = ", ".join(str(p) for p in parts if p)
    normalized = normalize_person_name(display).replace(" ", "")
    return ParsedEntity(
        entity_type=EntityType.ADDRESS,
        display_name=display,
        normalized_name=normalized,
        attributes={
            "city": city,
            "street": adres.get("ulica"),
            "building": adres.get("nrDomu"),
            "unit": adres.get("nrLokalu"),
            "postal_code": adres.get("kodPocztowy"),
            "voivodeship": siedziba.get("wojewodztwo"),
        },
        local_key=f"address:{normalized}",
    )


def _parse_people(
    root: dict, company: ParsedEntity, out: list[ParsedRelationship]
) -> list[ParsedEntity]:
    people: list[ParsedEntity] = []
    reprezentacja = _get(root, "dzial2", "reprezentacja", default={}) or {}
    organ_name = (reprezentacja.get("nazwaOrganu") or "ZARZĄD").upper()
    relation = ORGAN_TO_RELATION.get(organ_name, RelationshipType.REPRESENTS)

    for index, member in enumerate(reprezentacja.get("sklad", []) or []):
        person = _person_from_member(member)
        if person is None:
            continue
        people.append(person)
        out.append(
            ParsedRelationship(
                source_key=person.local_key,
                target_key=company.local_key,
                relationship_type=relation,
                role=member.get("funkcjaWOrganie") or organ_name,
                valid_from=_parse_date(member.get("dataOd")),
                valid_to=_parse_date(member.get("dataDo") or member.get("dataWykreslenia")),
                locator=f"/odpis/dane/dzial2/reprezentacja/sklad/{index}",
            )
        )
    return people


def _parse_shareholders(
    root: dict, company: ParsedEntity, out: list[ParsedRelationship]
) -> list[ParsedEntity]:
    entities: list[ParsedEntity] = []
    for index, wspolnik in enumerate(_get(root, "dzial1", "wspolnicy", default=[]) or []):
        person = _person_from_member(wspolnik)
        if person is None:
            continue
        entities.append(person)
        udzialy = wspolnik.get("udzialy") or {}
        out.append(
            ParsedRelationship(
                source_key=person.local_key,
                target_key=company.local_key,
                relationship_type=RelationshipType.SHAREHOLDER_OF,
                role="WSPÓLNIK",
                valid_from=_parse_date(wspolnik.get("dataOd")),
                valid_to=_parse_date(wspolnik.get("dataDo")),
                attributes={
                    "shares_count": udzialy.get("liczbaUdzialow"),
                    "shares_value": udzialy.get("wartoscUdzialow"),
                },
                locator=f"/odpis/dane/dzial1/wspolnicy/{index}",
            )
        )
    return entities


def _person_from_member(member: dict) -> ParsedEntity | None:
    """Osoba fizyczna albo podmiot (wspólnikiem bywa spółka)."""
    nazwisko = _get(member, "nazwisko", "nazwiskoICzlonPierwszyNazwiskaZlozonego") or member.get(
        "nazwisko"
    )
    imiona = _get(member, "imiona", "imiePierwsze") or member.get("imiePierwsze")

    if isinstance(nazwisko, str) and nazwisko and isinstance(imiona, str) and imiona:
        display = f"{imiona} {nazwisko}"
        return ParsedEntity(
            entity_type=EntityType.PERSON,
            display_name=display,
            normalized_name=normalize_person_name(display),
            attributes={"first_names": imiona, "last_name": nazwisko},
            # Bez PESEL-a klucz lokalny jest słaby — właściwe scalenie robi
            # dopiero entity resolution po stronie loadera.
            local_key=f"person:{normalize_person_name(display).replace(' ', '_')}",
        )

    name = member.get("nazwa") or member.get("nazwaPodmiotu")
    if name:
        return ParsedEntity(
            entity_type=EntityType.COMPANY,
            display_name=name,
            normalized_name=normalize_company_name(name),
            identifiers=(
                {IdentifierScheme.KRS: member["numerKRS"]} if member.get("numerKRS") else {}
            ),
            local_key=f"company:{member.get('numerKRS') or normalize_company_name(name)}",
        )
    return None
