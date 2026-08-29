import Link from "next/link";
import { notFound } from "next/navigation";
import { api } from "@/lib/api";
import { RelationshipGraph } from "@/components/RelationshipGraph";

export const dynamic = "force-dynamic";

function formatPeriod(from: string | null, to: string | null): string {
  if (!from && !to) return "—";
  return `${from ?? "?"} → ${to ?? "obecnie"}`;
}

export default async function EntityPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const [profile, relationships] = await Promise.all([
    api.entity(id).catch(() => null),
    api.relationships(id).catch(() => []),
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

      <section>
        <h2>Graf powiązań</h2>
        <RelationshipGraph rootId={id} depth={2} />
        <p className="hint">Kliknij dowolny węzeł, aby dociągnąć jego powiązania.</p>
      </section>

      <section>
        <h2>Powiązania ({relationships.length})</h2>
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
            {relationships.map((rel) => (
              <tr key={rel.id} className={rel.valid_to ? "rels__row--historical" : undefined}>
                <td>
                  <Link href={`/entity/${rel.other_id}`}>{rel.other_name}</Link>
                </td>
                <td>{rel.role ?? rel.type}</td>
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
      </section>
    </>
  );
}
