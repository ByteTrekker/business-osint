import Link from "next/link";
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

/** Kolumny listy. `sort` puste = kolumna nie jest sortowalna. */
const COLUMNS = [
  { key: "name", label: "Podmiot", sort: "name" },
  { key: "status", label: "Stan", sort: "status" },
  { key: "city", label: "Miejscowość", sort: "city" },
  { key: "pkd", label: "PKD", sort: "" },
  { key: "registered", label: "Od kiedy", sort: "registered" },
  { key: "degree", label: "Powiązania", sort: "degree" },
] as const;

const SORT_VALUES = ["", "name", "status", "city", "registered", "degree"] as const;

/** Etykiety stanów — takie same jak w filtrze, żeby lista i filtr mówiły to samo. */
const STATUS_LABELS: Record<string, string> = {
  active: "aktywna",
  suspended: "zawieszona",
  inactive: "wykreślona",
};

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
    pkd?: string;
  }>;
}) {
  const {
    q,
    offset: rawOffset,
    status: rawStatus,
    voivodeship: rawVoivodeship,
    sort: rawSort,
    pkd: rawPkd,
  } = await searchParams;
  const offset = Math.max(0, Number.parseInt(rawOffset ?? "0", 10) || 0);
  // Nieznana wartość statusu jest odrzucana, a nie przekazywana dalej: API ma
  // na to wzorzec i odpowiedziałoby błędem walidacji zamiast wynikami.
  const status = STATUSES.some((s) => s.value === rawStatus) ? (rawStatus as string) : "";
  const voivodeship = VOIVODESHIPS.includes(rawVoivodeship as (typeof VOIVODESHIPS)[number])
    ? (rawVoivodeship as string)
    : "";
  const sort = SORT_VALUES.includes(rawSort as (typeof SORT_VALUES)[number])
    ? (rawSort as string)
    : "";
  // Wpisany ręcznie PKD może być z kropkami albo bez — API przyjmuje obie
  // postaci, więc przepuszczamy to, co przypomina numer, i nic więcej.
  const pkd = /^[0-9]{2}\.?[0-9]{0,2}\.?[A-Za-z]?$/.test(rawPkd ?? "") ? (rawPkd as string) : "";
  const results =
    q && q.length >= 2
      ? await api.search(q, { offset, status, voivodeship, sort, pkd }).catch(() => null)
      : null;

  const adres = (zmiany: { offset?: number; sort?: string }) => {
    const p = new URLSearchParams();
    p.set("q", q ?? "");
    if (zmiany.offset) p.set("offset", String(zmiany.offset));
    if (status) p.set("status", status);
    if (voivodeship) p.set("voivodeship", voivodeship);
    if (pkd) p.set("pkd", pkd);
    const s = zmiany.sort ?? sort;
    if (s) p.set("sort", s);
    return `/?${p}`;
  };

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
        <input
          type="search"
          name="pkd"
          defaultValue={pkd}
          placeholder="PKD, np. 62"
          pattern="[0-9]{2}\.?[0-9]{0,2}\.?[A-Za-z]?"
          aria-label="Kod PKD"
          size={10}
        />
        <button type="submit">Szukaj</button>
      </form>

      {voivodeship && (
        <p className="hint">
          Filtr województwa jest zawężający: podmioty bez zapisanego województwa — czyli wszystko
          spoza CEIDG, a także 714 183 przedsiębiorców, którzy nie podali adresu — nie pojawią się w
          wyniku.
        </p>
      )}
      {pkd && (
        <p className="hint">
          Filtr PKD dopasowuje po początku kodu: „62” to cała informatyka, „62.01.Z” jedna klasa.
          Zawężający tak samo jak województwo.
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
        <div className="scroller">
          <table className="hits-table">
            <thead>
              <tr>
                {COLUMNS.map((col) => (
                  <th key={col.key} scope="col">
                    {col.sort ? (
                      <Link
                        href={adres({ sort: col.sort === sort ? "" : col.sort })}
                        aria-sort={col.sort === sort ? "ascending" : "none"}
                        className={col.sort === sort ? "sorted" : undefined}
                      >
                        {col.label}
                        {col.sort === sort ? " ↓" : ""}
                      </Link>
                    ) : (
                      col.label
                    )}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {results.hits.map((hit) => (
                <tr key={hit.id}>
                  <td>
                    <Link href={`/entity/${hit.id}`}>{hit.name}</Link>
                    <span className={`badge badge--${hit.type}`}>{hit.type}</span>
                    {(hit.nip || hit.krs) && (
                      <span className="hits__sub">
                        {[hit.krs && `KRS ${hit.krs}`, hit.nip && `NIP ${hit.nip}`]
                          .filter(Boolean)
                          .join(" · ")}
                      </span>
                    )}
                  </td>
                  <td>{hit.status ? (STATUS_LABELS[hit.status] ?? hit.status) : "—"}</td>
                  <td>{hit.city ?? "—"}</td>
                  <td>{hit.pkd ?? "—"}</td>
                  <td className="num">{hit.registered_on ?? "—"}</td>
                  <td className="num">{hit.degree}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {results && <Pager meta={results.meta} href={(next) => adres({ offset: next })} />}
    </>
  );
}
