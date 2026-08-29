# ADR-0002: Hybryda `entities` + tabele szczegółów

Data: 2026-08-29 · Status: przyjęte

## Kontekst

Trzy warianty modelowania węzłów grafu o różnych typach (firma, osoba, adres,
a docelowo także przetarg, dotacja, fundacja):

1. **Generyczny EAV** — jedna tabela `entities` z `attributes jsonb`.
2. **Osobne tabele** — `companies`, `people`, `addresses` bez wspólnej tabeli.
3. **Hybryda** — wspólna `entities` (tożsamość + graf) + tabele atrybutów 1:1.

## Decyzja

Wariant 3. `entities` zawiera to, co wspólne dla wszystkich węzłów: UUID, typ,
nazwę wyświetlaną, nazwę znormalizowaną, klucz blokujący, stopień węzła,
wskaźnik scalenia. `companies` / `people` / `addresses` zawierają atrybuty
specyficzne, z `PK = FK` do `entities`.

## Uzasadnienie

**Przeciw EAV:** utrata typów, `NOT NULL`, kluczy obcych i sensownych indeksów.
Zapytanie „spółki z kapitałem > 1 mln zarejestrowane po 2020” staje się
rzeźbieniem w JSON-ie. Walidacja przenosi się z bazy do aplikacji, gdzie zawsze
przecieka.

**Przeciw osobnym tabelom:** `relationships` musiałoby mieć polimorficzne FK
(`source_type` + `source_id` bez integralności referencyjnej), a każdy traversal
byłby `UNION`-em po wszystkich typach. Dodanie typu węzła oznaczałoby zmianę
wszystkich zapytań grafowych — a plan zakłada dodawanie przetargów i dotacji.

**Za hybrydą:** integralność referencyjna, typowanie, jeden traversal dla
wszystkich typów, tanie dodawanie nowych typów węzłów.

## Konsekwencje

* Odczyt profilu wymaga `LEFT JOIN` do trzech tabel — koszt nieistotny, bo to
  jeden wiersz (`repositories/entities.py` robi to jednym zapytaniem z `to_jsonb`).
* Zapis encji to dwa `INSERT`-y — akceptowalne, dzieje się w ETL.
* Dodanie typu węzła: nowa tabela atrybutów + wartość w `CHECK`. Zapytania
  grafowe pozostają bez zmian.
