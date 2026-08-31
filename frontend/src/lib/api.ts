/** Klient REST API. Typy odzwierciedlają kontrakt z backendu (schemas/*.py). */

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";

export type EntityType = "company" | "person" | "address" | "foreign_entity" | "other";

export interface SearchHit {
  id: string;
  type: EntityType;
  name: string;
  subtitle: string | null;
  score: number;
  degree: number;
}

export interface GraphNode {
  id: string;
  type: EntityType;
  label: string;
  degree: number;
  depth: number;
  /** false = węzeł jest hubem i nie został rozwinięty automatycznie */
  expandable: boolean;
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  type: string;
  role: string | null;
  valid_from: string | null;
  valid_to: string | null;
  current: boolean;
  confidence: string;
  attributes: Record<string, unknown>;
}

export interface GraphResponse {
  nodes: GraphNode[];
  edges: GraphEdge[];
  meta: {
    root_id: string;
    depth: number;
    as_of: string | null;
    node_count: number;
    edge_count: number;
    truncated: boolean;
    suppressed_hubs: number;
  };
}

export interface Provenance {
  source: string;
  external_id: string | null;
  url: string | null;
  fetched_at: string | null;
  locator: string | null;
}

export interface Relationship {
  id: string;
  direction: "in" | "out";
  type: string;
  role: string | null;
  other_id: string;
  other_type: EntityType;
  other_name: string;
  valid_from: string | null;
  valid_to: string | null;
  confidence: string;
  attributes: Record<string, unknown>;
  provenance: Provenance[];
}

export interface FinancialReport {
  period_from: string;
  period_to: string;
  revenue: number | null;
  costs: number | null;
  income: number | null;
  loss: number | null;
  tax_base: number | null;
  tax_due: number | null;
  currency: string;
}

export interface EntityProfile {
  id: string;
  type: EntityType;
  name: string;
  degree: number;
  identifiers: { scheme: string; value: string }[];
  company: Record<string, unknown> | null;
  person: Record<string, unknown> | null;
  address: Record<string, unknown> | null;
  financials: FinancialReport[];
  updated_at: string | null;
}

async function get<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: { Accept: "application/json", ...init?.headers },
    next: { revalidate: 60 },
  });
  if (!response.ok) {
    throw new Error(`API ${response.status}: ${path}`);
  }
  return response.json() as Promise<T>;
}

/**
 * Ile poprosiliśmy, ile dostaliśmy i czy zostało coś dalej.
 *
 * `total` bywa `null` świadomie: dla powiązań policzenie jest tanie, dla
 * wyszukiwania oznaczałoby przejście przez wszystkie dopasowania. Interfejs
 * musi umieć powiedzieć „jest więcej" bez podawania liczby.
 */
export type PageMeta = {
  limit: number;
  offset: number;
  returned: number;
  has_more: boolean;
  total: number | null;
};

export const SEARCH_PAGE_SIZE = 20;
export const RELATIONSHIP_PAGE_SIZE = 50;

export const api = {
  search: (q: string, { fuzzy = false, offset = 0 } = {}) =>
    get<{ query: string; hits: SearchHit[]; meta: PageMeta }>(
      `/search?q=${encodeURIComponent(q)}&limit=${SEARCH_PAGE_SIZE}&offset=${offset}` +
        (fuzzy ? "&fuzzy=true" : ""),
    ),
  entity: (id: string) => get<EntityProfile>(`/entities/${id}`),
  relationships: (id: string, offset = 0) =>
    get<{ items: Relationship[]; meta: PageMeta }>(
      `/entities/${id}/relationships?limit=${RELATIONSHIP_PAGE_SIZE}&offset=${offset}`,
    ),
  graph: (id: string, depth = 2, includeHistorical = false) =>
    get<GraphResponse>(`/graph/${id}?depth=${depth}&include_historical=${includeHistorical}`),
};
