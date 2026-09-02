"""Mapowanie ogłoszeń BZP na encje i relacje.

Z ogłoszenia o wyniku wyciągamy dwie strony: zamawiającego i wykonawcę, obu
z numerem NIP. To jest jedyne źródło w projekcie, które łączy podmiot publiczny
z firmą — i jedyne, które daje firmy spoza rejestru LEI.

**Czego w tym API nie ma: wartości zamówienia.** Kwota jest w treści ogłoszenia,
czyli w PDF-ie pod `pdfUrl`. Zapisujemy więc sam odnośnik — parsowanie PDF-a to
osobna decyzja, a link bez kwoty jest wciąż lepszy niż nic, bo prowadzi
człowieka do źródła.
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Any

from business_osint.domain.enums import EntityType, IdentifierScheme, RelationshipType
from business_osint.domain.normalization import is_valid_nip, normalize_company_name
from business_osint.etl.sources.krs_mapper import (
    ParsedDocument,
    ParsedEntity,
    ParsedRelationship,
)

#: Nazwa wykonawcy bywa sklejona z całym adresem i numerami — bierzemy część
#: przed pierwszym przecinkiem, o ile wygląda na nazwę, a nie na ulicę.
_ADDRESS_TAIL = re.compile(r",\s*(ul\.|al\.|pl\.|os\.|\d{2}-\d{3}).*$", re.IGNORECASE)


def _clean_name(raw: str | None) -> str:
    if not raw:
        return ""
    name = _ADDRESS_TAIL.sub("", raw.strip())
    return name.split(",")[0].strip() if len(name) > 80 else name.strip()


def _digits(value: str | None) -> str:
    return "".join(ch for ch in (value or "") if ch.isdigit())


def parse_notices(payload: dict[str, Any]) -> ParsedDocument:
    """Strona ogłoszeń -> zamawiający, wykonawcy i krawędzie między nimi."""
    result = ParsedDocument()
    seen: set[str] = set()

    for notice in payload.get("items") or []:
        buyer = _entity_from(
            _clean_name(notice.get("organizationName")),
            _digits(notice.get("organizationNationalId")),
            city=notice.get("organizationCity"),
        )
        if buyer is None:
            continue
        if buyer.local_key not in seen:
            seen.add(buyer.local_key)
            result.entities.append(buyer)

        published = _parse_date(notice.get("publicationDate"))
        for contractor in notice.get("contractors") or []:
            supplier = _entity_from(
                _clean_name(contractor.get("contractorName")),
                _digits(contractor.get("contractorNationalId")),
                city=contractor.get("contractorCity"),
            )
            if supplier is None or supplier.local_key == buyer.local_key:
                continue
            if supplier.local_key not in seen:
                seen.add(supplier.local_key)
                result.entities.append(supplier)
            result.relationships.append(
                ParsedRelationship(
                    source_key=supplier.local_key,
                    target_key=buyer.local_key,
                    relationship_type=RelationshipType.CONTRACTOR_OF,
                    role=notice.get("noticeType"),
                    # Zamówienie jest zdarzeniem, nie stanem trwającym: data
                    # publikacji jest jednocześnie początkiem i końcem okresu.
                    valid_from=published,
                    valid_to=published,
                    attributes=_atrybuty(notice),
                    locator=f"bzp/{notice.get('noticeNumber')}",
                )
            )
    return result


#: Pola ogłoszenia, które przepisujemy wprost. Odpowiedź niesie ich trzydzieści
#: kilka; te są tym, co da się wykorzystać bez sięgania po treść ogłoszenia.
#:
#: `notice_type_ted` jest tu najważniejszy mimo niepozornej nazwy: to numer tego
#: samego postępowania w TED. Gdy dojdzie integracja z TED, będzie gotowym
#: łącznikiem — bez niego trzeba by je zestawiać po nazwie zamawiającego i dacie.
_PRZEPISYWANE = {
    "notice_number": "noticeNumber",
    "notice_type": "noticeType",
    "notice_type_ted": "noticeTypeTed",
    "cpv": "cpvCode",
    "order_type": "orderType",
    "client_type": "clientType",
    "tender_id": "tenderId",
    "procedure_result": "procedureResult",
    "offers_deadline": "submittingOffersDate",
    "pdf_url": "pdfUrl",
    "buyer_province": "organizationProvince",
    "below_eu_threshold": "isTenderAmountBelowEU",
}


def _atrybuty(notice: dict[str, Any]) -> dict[str, Any]:
    """Atrybuty krawędzi z ogłoszenia — bez pustych, żeby nie zaśmiecać JSON-a."""
    wynik: dict[str, Any] = {
        klucz: notice.get(pole)
        for klucz, pole in _PRZEPISYWANE.items()
        if notice.get(pole) not in (None, "")
    }
    # Przedmiot zamówienia bywa długi; przycinamy, bo to opis, a nie dana
    # do porównywania — i mówimy o tym w nazwie klucza.
    przedmiot = (notice.get("orderObject") or "").strip()
    if przedmiot:
        wynik["order_object"] = przedmiot[:500]
        if len(przedmiot) > 500:
            wynik["order_object_truncated"] = True
    return wynik


def _entity_from(name: str, nip: str, *, city: str | None = None) -> ParsedEntity | None:
    """Encja tylko wtedy, gdy mamy nazwę i poprawny NIP.

    Bez NIP-u nie da się jej wiarygodnie połączyć z podmiotem z innego rejestru,
    a tworzenie węzła po samej nazwie prowadziłoby do fałszywych scaleń.
    """
    if not name or not is_valid_nip(nip):
        return None
    return ParsedEntity(
        entity_type=EntityType.COMPANY,
        display_name=name,
        normalized_name=normalize_company_name(name),
        identifiers={IdentifierScheme.NIP: nip},
        attributes={"city": city},
        local_key=f"nip:{nip}",
    )


def _parse_date(value: str | None) -> dt.date | None:
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return None
