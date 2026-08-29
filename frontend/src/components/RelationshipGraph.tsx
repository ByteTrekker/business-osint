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
import cytoscape, { type Core, type ElementDefinition } from "cytoscape";
import fcose from "cytoscape-fcose";
import { api, type GraphResponse } from "@/lib/api";

cytoscape.use(fcose);

const NODE_COLORS: Record<string, string> = {
  company: "#2563eb",
  person: "#16a34a",
  address: "#a16207",
  foreign_entity: "#7c3aed",
  other: "#64748b",
};

const EDGE_LABELS: Record<string, string> = {
  board_member_of: "zarząd",
  supervisory_member_of: "rada nadzorcza",
  shareholder_of: "udziałowiec",
  partner_in: "wspólnik",
  ubo_of: "beneficjent rzecz.",
  proxy_of: "prokurent",
  parent_of: "podmiot dominujący",
  registered_at: "adres",
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

    const cy = cytoscape({
      container,
      elements: [],
      style: [
        {
          selector: "node",
          style: {
            "background-color": (el) => NODE_COLORS[el.data("type")] ?? NODE_COLORS.other,
            label: "data(label)",
            "font-size": "10px",
            "text-wrap": "ellipsis",
            "text-max-width": "120px",
            "text-valign": "bottom",
            "text-margin-y": 4,
            width: (el) => 18 + Math.min(22, Math.log2((el.data("degree") ?? 1) + 1) * 4),
            height: (el) => 18 + Math.min(22, Math.log2((el.data("degree") ?? 1) + 1) * 4),
          },
        },
        {
          // Hub, którego celowo nie rozwinęliśmy — sygnalizujemy to wizualnie.
          selector: "node[!expandable]",
          style: { "border-width": 3, "border-color": "#dc2626", "border-style": "dashed" },
        },
        { selector: `node[id = "${rootId}"]`, style: { "border-width": 4, "border-color": "#0f172a" } },
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
      layout: { name: "fcose", animate: false },
      wheelSensitivity: 0.2,
    });
    cyRef.current = cy;

    cy.on("tap", "node", (event) => {
      const id = event.target.id() as string;
      onSelect?.(id);
      void expand(id);
    });

    async function expand(entityId: string) {
      try {
        const neighbourhood = await api.graph(entityId, 1);
        const existing = new Set(cy.elements().map((el) => el.id()));
        const fresh = toElements(neighbourhood).filter((el) => !existing.has(el.data.id as string));
        if (fresh.length === 0) return;
        cy.add(fresh);
        cy.layout({ name: "fcose", animate: true, randomize: false }).run();
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : "Nie udało się rozwinąć węzła");
      }
    }

    api
      .graph(rootId, depth)
      .then((graph) => {
        cy.add(toElements(graph));
        cy.layout({ name: "fcose", animate: false }).run();
        setMeta(graph.meta);
      })
      .catch((cause: unknown) =>
        setError(cause instanceof Error ? cause.message : "Błąd pobierania grafu"),
      )
      .finally(() => setLoading(false));

    return () => {
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
