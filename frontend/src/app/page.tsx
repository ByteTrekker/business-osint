import Link from "next/link";
import { counted } from "@/lib/plural";
import { api } from "@/lib/api";
import Pager from "@/components/Pager";

/** Stany działalności, którymi da się zawęzić wynik. Nazwy po polsku, bo to etykiety. */
const STATUSES = [
  { value: "", label: "dowolny stan" },
  { value: "active", label: "aktywne" },
  { value: "suspended", label: "zawieszone" },
  { value: "inactive", label: "wykreślone" },
] as const;

/** Województwa zapisane w CEIDG. Wartości są dokładnie takie jak w danych. */
const VOIVODESHIPS = [
  "dolnośląskie",
  "kujawsko-pomorskie",
  "lubelskie",
  "lubuskie",
  "łódzkie",
  "małopolskie",
  "mazowieckie",
  "opolskie",
  "podkarpackie",
  "podlaskie",
  "pomorskie",
  "śląskie",
  "świętokrzyskie",
  "warmińsko-mazurskie",
  "wielkopolskie",
  "zachodniopomorskie",
] as const;

const SORTS = [
  { value: "", label: "wg trafności" },
  { value: "degree", label: "wg liczby powiązań" },
  { value: "name", label: "wg nazwy" },
] as const;

export const dynamic = "force-dynamic";

export default async function HomePage({
  searchParams,
}: {
  searchParams: Promise<{
    q?: string;
    offset?: string;
    status?: string;
    voivodeship?: string;
    sort?: string;
  }>;
}) {
  const {
    q,
    offset: rawOffset,
    status: rawStatus,
    voivodeship: rawVoivodeship,
    sort: rawSort,
  } = await searchParams;
  const offset = Math.max(0, Number.parseInt(rawOffset ?? "0", 10) || 0);
  // Nieznana wartość statusu jest odrzucana, a nie przekazywana dalej: API ma
  // na to wzorzec i odpowiedziałoby błędem walidacji zamiast wynikami.
  const status = STATUSES.some((s) => s.value === rawStatus) ? (rawStatus as string) : "";
  const voivodeship = VOIVODESHIPS.includes(rawVoivodeship as (typeof VOIVODESHIPS)[number])
    ? (rawVoivodeship as string)
    : "";
  const sort = SORTS.some((s) => s.value === rawSort) ? (rawSort as string) : "";
  const results =
    q && q.length >= 2
      ? await api.search(q, { offset, status, voivodeship, sort }).catch(() => null)
      : null;

  return (
    <>
      <h1>Kto stoi za tą firmą?</h1>
      <p className="lead">
        Wyszukaj po nazwie, NIP, KRS lub REGON, a następnie klikaj kolejne węzły grafu, żeby
        prześledzić powiązania osobowe i kapitałowe.
      </p>

      <form action="/" method="get" className="search">
        <input
          type="search"
          name="q"
          defaultValue={q ?? ""}
          placeholder="np. ALFA TECHNOLOGIE albo 5252445170"
          minLength={2}
          required
          autoFocus
        />
        <select name="status" defaultValue={status} aria-label="Stan działalności">
          {STATUSES.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
        <select name="voivodeship" defaultValue={voivodeship} aria-label="Województwo">
          <option value="">całą Polskę</option>
          {VOIVODESHIPS.map((w) => (
            <option key={w} value={w}>
              {w}
            </option>
          ))}
        </select>
        <select name="sort" defaultValue={sort} aria-label="Kolejność wyników">
          {SORTS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
        <button type="submit">Szukaj</button>
      </form>

      {voivodeship && (
        <p className="hint">
          Filtr województwa jest zawężający: podmioty bez zapisanego województwa — czyli wszystko
          spoza CEIDG, a także 714 183 przedsiębiorców, którzy nie podali adresu — nie pojawią się w
          wyniku.
        </p>
      )}
      {sort && (
        <p className="hint">
          Sortowanie porządkuje 200 najlepszych trafień, a nie cały zbiór dopasowań. Wyszukiwarka
          jest etapowa i nie zna go — dla prefiksu „a” dopasowań jest 830 tysięcy.
        </p>
      )}

      {results && results.hits.length === 0 && <p>Brak wyników dla „{q}”.</p>}

      {/* Trafienie z niskim wynikiem znaczy, że nazwa nie pasuje dosłownie
          i zadziałało dopasowanie rozmyte. Bez tej informacji użytkownik
          czyta przybliżenie jak dokładną odpowiedź. Próg 0,40 to granica
          pasma trigramowego — patrz `_BY_TRIGRAM` w repozytorium. */}
      {results && results.hits.length > 0 && results.hits[0].score < 0.4 && (
        <p className="hint">
          Nie znaleziono nazwy „{q}”. Poniżej podmioty o&nbsp;najbardziej zbliżonych nazwach.
        </p>
      )}

      {results && results.hits.length > 0 && (
        <ul className="hits">
          {results.hits.map((hit) => (
            <li key={hit.id}>
              <Link href={`/entity/${hit.id}`}>
                <span className={`badge badge--${hit.type}`}>{hit.type}</span>
                <strong>{hit.name}</strong>
                {hit.subtitle && <span className="hits__sub">{hit.subtitle}</span>}
                <span className="hits__degree">
                  {counted(hit.degree, "powiązanie", "powiązania", "powiązań")}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}

      {results && (
        <Pager
          meta={results.meta}
          href={(next) =>
            `/?q=${encodeURIComponent(q ?? "")}&offset=${next}` +
            (status ? `&status=${status}` : "") +
            (voivodeship ? `&voivodeship=${encodeURIComponent(voivodeship)}` : "") +
            (sort ? `&sort=${sort}` : "")
          }
        />
      )}
    </>
  );
}
