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

export const dynamic = "force-dynamic";

export default async function HomePage({
  searchParams,
}: {
  searchParams: Promise<{ q?: string; offset?: string; status?: string }>;
}) {
  const { q, offset: rawOffset, status: rawStatus } = await searchParams;
  const offset = Math.max(0, Number.parseInt(rawOffset ?? "0", 10) || 0);
  // Nieznana wartość statusu jest odrzucana, a nie przekazywana dalej: API ma
  // na to wzorzec i odpowiedziałoby błędem walidacji zamiast wynikami.
  const status = STATUSES.some((s) => s.value === rawStatus) ? (rawStatus as string) : "";
  const results =
    q && q.length >= 2 ? await api.search(q, { offset, status }).catch(() => null) : null;

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
        <button type="submit">Szukaj</button>
      </form>

      {results && results.hits.length === 0 && <p>Brak wyników dla „{q}”.</p>}

      {results && results.hits.length > 0 && (
        <ul className="hits">
          {results.hits.map((hit) => (
            <li key={hit.id}>
              <Link href={`/entity/${hit.id}`}>
                <span className={`badge badge--${hit.type}`}>{hit.type}</span>
                <strong>{hit.name}</strong>
                {hit.subtitle && <span className="hits__sub">{hit.subtitle}</span>}
                <span className="hits__degree">{hit.degree} powiązań</span>
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
            (status ? `&status=${status}` : "")
          }
        />
      )}
    </>
  );
}
