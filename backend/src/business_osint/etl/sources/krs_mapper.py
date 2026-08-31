"""Mapowanie odpisu KRS na encje i relacje.

Mapper jest czystą funkcją: JSON -> struktury dziedzinowe. Bez bazy, bez sieci.

Struktura odpisu **pełnego** różni się zasadniczo od aktualnego: każde pole jest
listą wersji z numerami wpisu wprowadzającego (``nrWpisuWprow``) i wykreślającego
(``nrWpisuWykr``). Nagłówek zawiera listę wszystkich wpisów z datami, więc numery
da się przełożyć na daty — i dopiero to czyni z odpisu **pełną, datowaną historię**
podmiotu od rejestracji.

Dwie decyzje, które warto znać:

* **Nie tworzymy encji osób.** Publiczne API KRS maskuje dane osobowe do pierwszej
  litery i długości (``K*******``). Taki węzeł nikogo nie identyfikuje, a jego
  utworzenie byłoby wymyśleniem tożsamości. Skład organów zapisujemy jako atrybut
  informacyjny, nie jako krawędzie do osób.
* **Historia adresów staje się krawędziami bitemporalnymi.** To jedyne źródło,
  które pozwala odpowiedzieć „gdzie ta spółka miała siedzibę w 2011 roku".
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

from business_osint.domain.enums import EntityType, IdentifierScheme, RelationshipType
from business_osint.domain.normalization import normalize_company_name, normalize_person_name


@dataclass(slots=True)
class ParsedEntity:
    entity_type: EntityType
    display_name: str
    normalized_name: str
    identifiers: dict[IdentifierScheme, str] = field(default_factory=dict)
    attributes: dict[str, Any] = field(default_factory=dict)
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
    locator: str | None = None


@dataclass(slots=True)
class ParsedDocument:
    entities: list[ParsedEntity] = field(default_factory=list)
    relationships: list[ParsedRelationship] = field(default_factory=list)


def _parse_date(value: str | None) -> dt.date | None:
    if not value:
        return None
    for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(value.strip()[:10], fmt).date()
        except ValueError:
            continue
    return None


def entry_dates(odpis: dict[str, Any]) -> dict[int, dt.date]:
    """Mapa numer wpisu -> data. Bez niej historia nie ma osi czasu."""
    header = odpis.get("naglowekP") or odpis.get("naglowekA") or {}
    dates: dict[int, dt.date] = {}
    for entry in header.get("wpis") or []:
        number = entry.get("numerWpisu")
        parsed = _parse_date(entry.get("dataWpisu"))
        if number is not None and parsed is not None:
            dates[int(number)] = parsed
    return dates


def _first(value: Any) -> Any:
    """Odpis pełny opakowuje pola w listy wersji, aktualny nie. Ujednolicamy."""
    if isinstance(value, list):
        return value[0] if value else None
    return value


def _versions(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [v for v in value if isinstance(v, dict)]
    return [value] if isinstance(value, dict) else []


def _period(
    version: dict[str, Any], dates: dict[int, dt.date]
) -> tuple[dt.date | None, dt.date | None]:
    """Okres obowiązywania wersji pola, przeliczony z numerów wpisów na daty."""
    start = version.get("nrWpisuWprow")
    end = version.get("nrWpisuWykr")
    return (
        dates.get(int(start)) if start is not None else None,
        dates.get(int(end)) if end is not None else None,
    )


def _is_current(version: dict[str, Any]) -> bool:
    return version.get("nrWpisuWykr") in (None, "", 0)


def parse_krs_document(payload: dict[str, Any]) -> ParsedDocument:
    """Zamienia odpis KRS na encje i relacje, z historią jeśli to odpis pełny."""
    odpis = payload.get("odpis") or {}
    root = odpis.get("dane") or {}
    dates = entry_dates(odpis)
    result = ParsedDocument()

    company = _parse_company(odpis, root, dates)
    if company is None:
        return result
    result.entities.append(company)

    _parse_addresses(root, dates, company, result)
    _parse_corporate_partners(root, dates, company, result)
    return result


def _parse_company(
    odpis: dict[str, Any], root: dict[str, Any], dates: dict[int, dt.date]
) -> ParsedEntity | None:
    dane = _first((root.get("dzial1") or {}).get("danePodmiotu")) or {}
    names = _versions(dane.get("nazwa"))
    current = next((n for n in names if _is_current(n)), names[-1] if names else None)
    name = (current or {}).get("nazwa") or dane.get("nazwa")
    if not isinstance(name, str) or not name:
        return None

    header = odpis.get("naglowekP") or odpis.get("naglowekA") or {}
    krs = header.get("numerKRS")
    ident = _first(dane.get("identyfikatory")) or {}

    identifiers: dict[IdentifierScheme, str] = {}
    if krs:
        identifiers[IdentifierScheme.KRS] = str(krs)
    if nip := ident.get("nip"):
        identifiers[IdentifierScheme.NIP] = str(nip)
    if regon := ident.get("regon"):
        identifiers[IdentifierScheme.REGON] = str(regon)

    forma = _first(dane.get("formaPrawna")) or {}
    kapital = _first((root.get("dzial1") or {}).get("kapital")) or {}

    return ParsedEntity(
        entity_type=EntityType.COMPANY,
        display_name=name,
        normalized_name=normalize_company_name(name),
        identifiers=identifiers,
        attributes={
            "legal_form": forma.get("formaPrawna") if isinstance(forma, dict) else forma,
            "registered_on": _iso(_earliest_entry(dates)),
            # Historia, której nie ma żadne inne dostępne źródło.
            "name_history": _history(names, "nazwa", dates),
            "capital_history": _history(
                _versions(kapital.get("wysokoscKapitaluZakladowego")), "wartosc", dates
            ),
            "board_size": _board_size(root),
            "board_note": "dane osobowe zanonimizowane przez rejestr",
        },
        local_key=f"company:{krs}" if krs else f"company:{normalize_company_name(name)}",
    )


def _history(
    versions: list[dict[str, Any]], value_key: str, dates: dict[int, dt.date]
) -> list[dict[str, Any]]:
    """Lista wersji pola z datami obowiązywania, od najstarszej."""
    out: list[dict[str, Any]] = []
    for version in versions:
        valid_from, valid_to = _period(version, dates)
        value = version.get(value_key)
        if value is None:
            continue
        out.append({"value": value, "from": _iso(valid_from), "to": _iso(valid_to)})
    return out


def _iso(value: dt.date | None) -> str | None:
    return value.isoformat() if value else None


def _earliest_entry(dates: dict[int, dt.date]) -> dt.date | None:
    return dates.get(min(dates)) if dates else None


def _board_size(root: dict[str, Any]) -> int:
    reprezentacja = _first((root.get("dzial2") or {}).get("reprezentacja")) or {}
    return len(reprezentacja.get("sklad") or [])


def _parse_addresses(
    root: dict[str, Any], dates: dict[int, dt.date], company: ParsedEntity, out: ParsedDocument
) -> None:
    """Każdy historyczny adres siedziby to osobny węzeł i krawędź z okresem.

    Dzięki temu „gdzie ta spółka miała siedzibę w 2011 roku" jest zwykłym
    zapytaniem z parametrem `as_of`, a nie rekonstrukcją z dokumentu.
    """
    siedziba = _first((root.get("dzial1") or {}).get("siedzibaIAdres")) or {}
    for index, version in enumerate(_versions(siedziba.get("adres"))):
        parts = [
            version.get("ulica"),
            version.get("nrDomu"),
            version.get("nrLokalu"),
            version.get("kodPocztowy"),
            version.get("miejscowosc"),
        ]
        display = ", ".join(str(p) for p in parts if p)
        if not display:
            continue
        normalized = normalize_person_name(display).replace(" ", "")
        valid_from, valid_to = _period(version, dates)
        out.entities.append(
            ParsedEntity(
                entity_type=EntityType.ADDRESS,
                display_name=display,
                normalized_name=normalized,
                attributes={
                    "city": version.get("miejscowosc"),
                    "street": version.get("ulica"),
                    "postal_code": version.get("kodPocztowy"),
                    "country": version.get("kraj") or "PL",
                },
                local_key=f"address:{normalized}",
            )
        )
        out.relationships.append(
            ParsedRelationship(
                source_key=company.local_key,
                target_key=f"address:{normalized}",
                relationship_type=RelationshipType.REGISTERED_AT,
                valid_from=valid_from,
                valid_to=valid_to,
                locator=f"/odpis/dane/dzial1/siedzibaIAdres/adres/{index}",
            )
        )


def _parse_corporate_partners(
    root: dict[str, Any], dates: dict[int, dt.date], company: ParsedEntity, out: ParsedDocument
) -> None:
    """Wspólnicy będący spółkami — jedyne krawędzie osobowo-kapitałowe, które
    KRS ujawnia bez maskowania, bo dotyczą podmiotów, nie osób fizycznych."""
    for index, partner in enumerate(_versions((root.get("dzial1") or {}).get("wspolnicySpzoo"))):
        name = partner.get("nazwa") or partner.get("nazwaPodmiotu")
        krs = partner.get("numerKRS") or (partner.get("identyfikator") or {}).get("numerKRS")
        if not isinstance(name, str) or not name:
            continue
        key = f"company:{krs}" if krs else f"company:{normalize_company_name(name)}"
        identifiers = {IdentifierScheme.KRS: str(krs)} if krs else {}
        out.entities.append(
            ParsedEntity(
                entity_type=EntityType.COMPANY,
                display_name=name,
                normalized_name=normalize_company_name(name),
                identifiers=identifiers,
                local_key=key,
            )
        )
        valid_from, valid_to = _period(partner, dates)
        udzialy = partner.get("posiadaneUdzialy") or (partner.get("udzialy") or {})
        out.relationships.append(
            ParsedRelationship(
                source_key=key,
                target_key=company.local_key,
                relationship_type=RelationshipType.SHAREHOLDER_OF,
                role="WSPÓLNIK",
                valid_from=valid_from,
                valid_to=valid_to,
                attributes={"shares": udzialy if isinstance(udzialy, str) else None},
                locator=f"/odpis/dane/dzial1/wspolnicySpzoo/{index}",
            )
        )
