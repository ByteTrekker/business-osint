"use client";

/**
 * Wizualizacja grafu powiązań (Cytoscape.js).
 *
 * Zasada UX, która wynika wprost z modelu danych: NIE ładujemy głębokiego grafu
 * jednym zapytaniem. Start = depth 1-2, a każde kliknięcie w węzeł dociąga jego
 * sąsiedztwo (`/graph/{id}?depth=1`) i scala je z bieżącym stanem. Dzięki temu
 * użytkownik steruje kosztem, a backend nigdy nie liczy „całego internetu”.
 */

import { useEffect, useRef, useState } from "react";
import cytoscape, {
  type Core,
  type ElementDefinition,
  type EventObject,
  type LayoutOptions,
  type NodeSingular,
  type SingularElementArgument,
} from "cytoscape";
import fcose from "cytoscape-fcose";
import { api, type GraphResponse } from "@/lib/api";

cytoscape.use(fcose);

/**
 * fcose jest rozszerzeniem bez typów, więc jego opcje (`animate`, `randomize`)
 * nie mieszczą się w `LayoutOptions` z @types/cytoscape. Jedno rzutowanie
 * w jednym miejscu jest uczciwsze niż `as any` przy każdym wywołaniu layoutu.
 */
function fcoseLayout(animate: boolean, randomize = true): LayoutOptions {
  // Domyślne odpychanie zlepia etykiety w nieczytelną plamę przy kilkunastu
  // węzłach — nazwy polskich spółek są długie.
  return {
    name: "fcose",
    animate,
    randomize,
    nodeRepulsion: 12000,
    idealEdgeLength: 160,
    padding: 40,
  } as unknown as LayoutOptions;
}

const NODE_COLORS: Record<string, string> = {
  company: "#2563eb",
  person: "#16a34a",
  address: "#a16207",
  foreign_entity: "#7c3aed",
  other: "#64748b",
};

// Musi pokrywać **cały** `RelationshipType` z backendu. Brak wpisu nie psuje
// rysowania — krawędź dostaje wtedy surową nazwę typu, więc obok „wspólnik"
// pojawia się „sole_proprietor_of". Brakowało akurat najczęstszego typu
// w bazie: jednoosobowych działalności jest 3,55 mln.
const EDGE_LABELS: Record<string, string> = {
  sole_proprietor_of: "właściciel",
  contractor_of: "wykonawca",
  represents: "reprezentuje",
  successor_of: "następca prawny",
  board_member_of: "zarząd",
  supervisory_member_of: "rada nadzorcza",
  shareholder_of: "udziałowiec",
  partner_in: "wspólnik",
  ubo_of: "beneficjent rzecz.",
  proxy_of: "prokurent",
  parent_of: "podmiot dominujący",
  registered_at: "adres",
  shares_address_with: "wspólny adres",
  shares_person_with: "wspólna osoba",
  liquidator_of: "likwidator",
};

function toElements(graph: GraphResponse): ElementDefinition[] {
  const nodes = graph.nodes.map((node) => ({
    data: {
      id: node.id,
      label: node.label,
      type: node.type,
      degree: node.degree,
      expandable: node.expandable,
    },
  }));
  const edges = graph.edges.map((edge) => ({
    data: {
      id: edge.id,
      source: edge.source,
      target: edge.target,
      label: EDGE_LABELS[edge.type] ?? edge.type,
      current: edge.current,
    },
  }));
  return [...nodes, ...edges];
}

/** Wielkość węzła rośnie logarytmicznie ze stopniem — huby mają być widoczne,
 *  ale nie mogą zdominować widoku. */
function nodeSize(el: NodeSingular): number {
  const degree = (el.data("degree") as number | undefined) ?? 1;
  return 18 + Math.min(22, Math.log2(degree + 1) * 4);
}

interface Props {
  rootId: string;
  depth?: number;
  onSelect?: (entityId: string) => void;
}

export function RelationshipGraph({ rootId, depth = 2, onSelect }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);
  const [meta, setMeta] = useState<GraphResponse["meta"] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    // React w trybie strict montuje efekt dwukrotnie. Bez tej flagi odpowiedź
    // z API dolatuje do instancji Cytoscape, która została już zniszczona,
    // i wywala się na wewnętrznym `isHeadless`.
    let cancelled = false;

    const cy = cytoscape({
      container,
      elements: [],
      style: [
        {
          selector: "node",
          style: {
            "background-color": (el: NodeSingular) =>
              NODE_COLORS[el.data("type") as string] ?? NODE_COLORS.other,
            label: "data(label)",
            "font-size": "10px",
            "text-wrap": "ellipsis",
            "text-max-width": "120px",
            "text-valign": "bottom",
            "text-margin-y": 4,
            width: (el: NodeSingular) => nodeSize(el),
            height: (el: NodeSingular) => nodeSize(el),
          },
        },
        {
          // Hub, którego celowo nie rozwinęliśmy — sygnalizujemy to wizualnie.
          selector: "node[!expandable]",
          style: { "border-width": 3, "border-color": "#dc2626", "border-style": "dashed" },
        },
        {
          selector: `node[id = "${rootId}"]`,
          style: { "border-width": 4, "border-color": "#0f172a" },
        },
        {
          selector: "edge",
          style: {
            width: 1.5,
            "line-color": "#94a3b8",
            "target-arrow-color": "#94a3b8",
            "target-arrow-shape": "triangle",
            "curve-style": "bezier",
            label: "data(label)",
            "font-size": "8px",
            "text-rotation": "autorotate",
            color: "#475569",
          },
        },
        // Powiązanie zakończone rysujemy przerywaną linią — „było, minęło”.
        { selector: "edge[!current]", style: { "line-style": "dashed", opacity: 0.55 } },
      ],
      layout: fcoseLayout(false),
      wheelSensitivity: 0.2,
    });
    cyRef.current = cy;

    // Cytoscape mierzy kontener przy tworzeniu i przy uruchamianiu układu.
    // Jeżeli w tym momencie kontener nie ma jeszcze docelowego rozmiaru —
    // a nie ma go, dopóki nie ustali się układ strony i nie dojadą kroje —
    // wszystkie węzły lądują w rogu, na kanwie 1900×1036 zajmując 120×68 px.
    // Nic tego nie zgłasza: konsola jest czysta, kanwa ma poprawne wymiary.
    //
    // Ta sama klasa błędu co przy mapie (`ClusterMap`), i to samo lekarstwo:
    // po każdej zmianie rozmiaru przeliczamy i dopasowujemy widok.
    const obserwator = new ResizeObserver(() => {
      cy.resize();
      if (cy.elements().length > 0) cy.fit(undefined, 40);
    });
    obserwator.observe(container);

    cy.on("tap", "node", (event: EventObject) => {
      const id = event.target.id() as string;
      onSelect?.(id);
      void expand(id);
    });

    async function expand(entityId: string) {
      try {
        const neighbourhood = await api.graph(entityId, 1);
        if (cancelled) return;
        const existing = new Set(cy.elements().map((el: SingularElementArgument) => el.id()));
        const fresh = toElements(neighbourhood).filter((el) => !existing.has(el.data.id as string));
        if (fresh.length === 0) return;
        cy.add(fresh);
        cy.layout(fcoseLayout(true, false)).run();
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : "Nie udało się rozwinąć węzła");
      }
    }

    api
      .graph(rootId, depth)
      .then((graph) => {
        if (cancelled) return;
        cy.add(toElements(graph));
        // `resize()` przed układem, bo dane przychodzą asynchronicznie i do
        // tego czasu kontener zdążył urosnąć.
        cy.resize();
        cy.layout(fcoseLayout(false)).run();
        setMeta(graph.meta);
      })
      .catch((cause: unknown) => {
        if (cancelled) return;
        setError(cause instanceof Error ? cause.message : "Błąd pobierania grafu");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
      obserwator.disconnect();
      cy.destroy();
      cyRef.current = null;
    };
  }, [rootId, depth, onSelect]);

  return (
    <div className="graph">
      <div ref={containerRef} className="graph__canvas" />
      {loading && <p className="graph__status">Ładowanie grafu…</p>}
      {error && <p className="graph__status graph__status--error">{error}</p>}
      {meta?.truncated && (
        <p className="graph__status graph__status--warning">
          Wynik przycięty do {meta.node_count} węzłów
          {meta.suppressed_hubs > 0 && ` · pominięto ${meta.suppressed_hubs} hub(ów)`}. Kliknij
          węzeł, aby rozwinąć go ręcznie.
        </p>
      )}
    </div>
  );
}
