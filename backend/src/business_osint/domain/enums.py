"""Słowniki domenowe. Wartości są stabilne — trafiają do bazy i do API."""

from __future__ import annotations

from enum import StrEnum


class EntityType(StrEnum):
    """Typ węzła grafu."""

    COMPANY = "company"
    PERSON = "person"
    ADDRESS = "address"
    FOREIGN_ENTITY = "foreign_entity"
    OTHER = "other"


class RelationshipType(StrEnum):
    """Typ krawędzi.

    Nazewnictwo: SOURCE --TYPE--> TARGET, czytane jako zdanie.
    np. PERSON --BOARD_MEMBER_OF--> COMPANY
    """

    BOARD_MEMBER_OF = "board_member_of"  # osoba -> spółka (zarząd)
    SUPERVISORY_MEMBER_OF = "supervisory_member_of"  # osoba -> spółka (rada nadzorcza)
    PARTNER_IN = "partner_in"  # wspólnik -> spółka
    SHAREHOLDER_OF = "shareholder_of"  # udziałowiec -> spółka (z % w attributes)
    UBO_OF = "ubo_of"  # beneficjent rzeczywisty (CRBR)
    PROXY_OF = "proxy_of"  # prokurent
    LIQUIDATOR_OF = "liquidator_of"
    REPRESENTS = "represents"  # inna forma reprezentacji
    PARENT_OF = "parent_of"  # spółka -> spółka zależna
    REGISTERED_AT = "registered_at"  # podmiot -> adres
    SUCCESSOR_OF = "successor_of"  # przekształcenie / połączenie
    # Krawędzie wyprowadzone (nie pochodzą wprost z rejestru):
    SHARES_ADDRESS_WITH = "shares_address_with"
    SHARES_PERSON_WITH = "shares_person_with"


#: Typy relacji wyliczane przez nas, a nie pochodzące z rejestru.
DERIVED_RELATIONSHIP_TYPES = frozenset(
    {RelationshipType.SHARES_ADDRESS_WITH, RelationshipType.SHARES_PERSON_WITH}
)


class IdentifierScheme(StrEnum):
    """Przestrzenie identyfikatorów używane przy entity resolution."""

    KRS = "krs"
    NIP = "nip"
    REGON = "regon"
    CEIDG = "ceidg"
    PESEL_HASH = "pesel_hash"  # nigdy nie trzymamy PESEL jawnie
    LEI = "lei"
    INTERNAL = "internal"  # klucz syntetyczny z blokowania nazw


class SourceKind(StrEnum):
    """Rejestr / dostawca danych."""

    KRS = "krs"
    REGON = "regon"
    CEIDG = "ceidg"
    CRBR = "crbr"
    MF_WHITELIST = "mf_whitelist"  # biała lista podatników VAT
    TED = "ted"  # zamówienia publiczne UE
    BZP = "bzp"  # Biuletyn Zamówień Publicznych
    EU_FUNDS = "eu_funds"
    MANUAL = "manual"
    DERIVED = "derived"  # wynik naszego przetwarzania


class Confidence(StrEnum):
    """Skąd wiemy — poziom pewności krawędzi."""

    REGISTERED = "registered"  # wprost z rejestru urzędowego
    HIGH = "high"  # dopasowanie po twardym identyfikatorze
    MEDIUM = "medium"  # dopasowanie heurystyczne (nazwa + adres)
    LOW = "low"  # wyprowadzone, wymaga weryfikacji


CONFIDENCE_SCORE: dict[Confidence, float] = {
    Confidence.REGISTERED: 1.0,
    Confidence.HIGH: 0.9,
    Confidence.MEDIUM: 0.6,
    Confidence.LOW: 0.3,
}
