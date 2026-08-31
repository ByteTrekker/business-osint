import Link from "next/link";
import { notFound } from "next/navigation";
import { api } from "@/lib/api";
import Pager from "@/components/Pager";
import CoLocated from "@/components/CoLocated";
import { RelationshipGraph } from "@/components/RelationshipGraph";
import { CompanyFacts } from "@/components/CompanyFacts";
import CompanyHistory from "@/components/CompanyHistory";

export const dynamic = "force-dynamic";

/** Surowe kody ról ze źródeł na czytelne etykiety. Kod zostaje, gdy go nie znamy —
 *  lepiej pokazać oryginał niż udawać, że rozumiemy każdą wartość z rejestru. */
const ROLE_LABELS: Record<string, string> = {
  IS_DIRECTLY_CONSOLIDATED_BY: "spółka zależna (bezpośrednio)",
  IS_ULTIMATELY_CONSOLIDATED_BY: "spółka zależna (ostatecznie)",
  IS_SUBFUND_OF: "subfundusz",
  parent_of: "podmiot dominujący",
  registered_at: "siedziba",
};

function formatRole(role: string | null, type: string): string {
  return ROLE_LABELS[role ?? ""] ?? ROLE_LABELS[type] ?? role ?? type;
}

function formatPeriod(from: string | null, to: string | null): string {
  if (!from && !to) return "—";
  return `${from ?? "?"} → ${to ?? "obecnie"}`;
}

export default async function EntityPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ rel?: string; loc?: string }>;
}) {
  const { id } = await params;
  const { rel, loc } = await searchParams;
  const relOffset = Math.max(0, Number.parseInt(rel ?? "0", 10) || 0);
  const locOffset = Math.max(0, Number.parseInt(loc ?? "0", 10) || 0);
  const [profile, relationships] = await Promise.all([
    api.entity(id).catch(() => null),
    api.relationships(id, relOffset).catch(() => null),
  ]);
  if (!profile) notFound();

  return (
    <>
      <nav className="crumbs">
        <Link href="/">← wyszukiwarka</Link>
      </nav>

      <h1>{profile.name}</h1>
      <p className="meta">
        <span className={`badge badge--${profile.type}`}>{profile.type}</span>
        {profile.identifiers.map((identifier) => (
          <span key={`${identifier.scheme}-${identifier.value}`} className="meta__id">
            {identifier.scheme.toUpperCase()} {identifier.value}
          </span>
        ))}
        <span>{profile.degree} powiązań</span>
      </p>

      <CompanyFacts profile={profile} />
      <CompanyHistory
        attributes={(profile.company?.attributes as Record<string, unknown> | undefined) ?? null}
      />

      <section>
        <h2>Graf powiązań</h2>
        <RelationshipGraph rootId={id} depth={2} />
        <p className="hint">Kliknij dowolny węzeł, aby dociągnąć jego powiązania.</p>
      </section>

      <section>
        <h2>Powiązania ({relationships?.meta.total ?? 0})</h2>
        <table className="rels">
          <thead>
            <tr>
              <th>Podmiot / osoba</th>
              <th>Rola</th>
              <th>Okres</th>
              <th>Źródło</th>
            </tr>
          </thead>
          <tbody>
            {(relationships?.items ?? []).map((rel) => (
              <tr key={rel.id} className={rel.valid_to ? "rels__row--historical" : undefined}>
                <td>
                  <Link href={`/entity/${rel.other_id}`}>{rel.other_name}</Link>
                </td>
                <td>{formatRole(rel.role, rel.type)}</td>
                <td>{formatPeriod(rel.valid_from, rel.valid_to)}</td>
                <td className="rels__source">
                  {/* Provenance jest częścią produktu, nie dodatkiem: użytkownik
                      due diligence musi wiedzieć, z czego wynika każda krawędź. */}
                  {rel.provenance.map((source, index) => (
                    <span key={`${rel.id}-${index}`}>
                      {source.url ? (
                        <a href={source.url} target="_blank" rel="noreferrer noopener">
                          {source.source.toUpperCase()}
                        </a>
                      ) : (
                        source.source.toUpperCase()
                      )}
                      {source.fetched_at && ` (${source.fetched_at.slice(0, 10)})`}
                    </span>
                  ))}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {relationships && (
          <Pager
            meta={relationships.meta}
            href={(next) => `/entity/${id}?rel=${next}`}
            noun="powiązań"
          />
        )}
      </section>

      <CoLocated entityId={id} offset={locOffset} href={(next) => `/entity/${id}?loc=${next}`} />
    </>
  );
}
