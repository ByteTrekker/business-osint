# ADR-0003: Bitemporalność i provenance jako fundament, nie dodatek

Data: 2026-08-29 · Status: przyjęte

## Kontekst

Produkt ma służyć do due diligence, compliance i dziennikarstwa śledczego.
W każdym z tych zastosowań kluczowe są dwa pytania, na które zwykła baza
„stanu bieżącego” nie odpowiada:

* *„Jak wyglądały powiązania tej spółki w dniu podpisania umowy?”*
* *„Skąd wiecie, że ta osoba była w zarządzie?”*

## Decyzja

**Bitemporalność.** Każda relacja ma dwie niezależne osie czasu:

* czas rzeczywisty — `valid_from`, `valid_to` (kiedy fakt obowiązywał),
* czas systemowy — `recorded_at`, `superseded_at` (kiedy my o nim wiedzieliśmy).

**Zakaz nadpisywania.** Zmiana faktu = zamknięcie starego wiersza
(`superseded_at = now()`) i wstawienie nowego. Żadnych `UPDATE` na faktach,
żadnych `DELETE`.

**Provenance na trzech poziomach.** `relationships` → `relationship_sources`
(z lokalizatorem wskazującym miejsce w dokumencie) → `raw_documents`
(niezmienna kopia odpowiedzi + sha256) → `sources` (rejestr, licencja).

## Uzasadnienie

* Odpowiedź na „stan na dzień X” to zwykły `WHERE`, nie osobny system.
* Rejestry potrafią zmieniać dane wstecz. Bez czasu systemowego nie da się
  wykazać, co pokazywaliśmy w danym dniu — a to jest podstawa obrony przy sporze.
* Provenance to jednocześnie wymóg RODO (art. 14 — informacja o źródle)
  i funkcja produktu (użytkownik due diligence musi móc zweryfikować).
* Surowy dokument przed parsowaniem pozwala odtworzyć wynik po poprawce
  w parserze — bez ponownego odpytywania rejestru.

## Konsekwencje

**Pozytywne:** pełny audyt, `as_of` za darmo, odporność na zmiany wsteczne
w rejestrach, cache podgrafów historycznych na dobę (są niezmienne).

**Negatywne:** tabela `relationships` rośnie i nigdy nie maleje; każde
zapytanie o stan bieżący musi filtrować po `superseded_at IS NULL`;
`raw_documents` zajmuje dużo miejsca.

**Mitygacja:** indeksy częściowe `WHERE superseded_at IS NULL` (historia jest
poza indeksem), dedup snapshotów po `content_sha256`, partycjonowanie
`raw_documents` po `fetched_at`, przenoszenie starych payloadów do S3.

## Pułapki wykryte przy projektowaniu

* KRS nie zawsze podaje datę wykreślenia. Gdy fakt znika z odpisu bez daty,
  zamykamy go datą importu i oznaczamy `{"valid_to_inferred": true}` —
  zgadywanie bez oznaczenia to produkowanie fałszywych faktów.
* `NULL != NULL` w kluczu unikalnym przepuszcza duplikaty relacji bez
  `valid_from`. Stąd `COALESCE(valid_from, 'epoch')` w `uq_relationships_active`.
