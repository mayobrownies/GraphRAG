import { useEffect, useRef } from "react";
import cytoscape from "cytoscape";

// One color per node type in backend/app/graph_schema.py
const COLORS = { Gene: "#099250", Protein: "#7a5af8", Disease: "#d92d20", Drug: "#2457d6" };

export default function GraphView({ nodes, edges, highlightNodes = [], highlightEdges = [], onSelect }) {
  const box = useRef(null);
  const cy = useRef(null);

  useEffect(() => {
    cy.current = cytoscape({
      container: box.current,
      style: [
        { selector: "node", style: { label: "data(name)", "font-size": 10, "background-color": "data(color)", width: 18, height: 18, "text-valign": "bottom", "text-margin-y": 4 } },
        { selector: "edge", style: { label: "data(type)", "font-size": 8, width: 1.5, "line-color": "#c0c6d0", "target-arrow-color": "#c0c6d0", "target-arrow-shape": "triangle", "curve-style": "bezier" } },
        { selector: ".hl", style: { "line-color": "#f04438", "target-arrow-color": "#f04438", width: 3, "border-width": 3, "border-color": "#f04438" } },
      ],
    });
    cy.current.on("tap", "node", (e) => onSelect && onSelect(e.target.id()));
    return () => cy.current && cy.current.destroy();
  }, []);

  useEffect(() => {
    const c = cy.current;
    if (!c) return;
    const nodeIds = new Set(nodes.map((n) => n.id));
    const els = [
      ...nodes.map((n) => ({ data: { id: n.id, name: n.name, color: COLORS[n.type] || "#667085" } })),
      ...edges.filter((e) => nodeIds.has(e.source) && nodeIds.has(e.target))
        .map((e, i) => ({ data: { id: `e${i}-${e.source}-${e.target}-${e.type}`, source: e.source, target: e.target, type: e.type } })),
    ];
    c.elements().remove();
    c.add(els);
    c.layout({ name: "cose", animate: false, fit: true, padding: 20 }).run();
    const hn = new Set(highlightNodes);
    const he = new Set(highlightEdges.map((e) => `${e.source}|${e.target}|${e.type}`));
    c.nodes().forEach((n) => hn.has(n.id()) && n.addClass("hl"));
    c.edges().forEach((e) => he.has(`${e.data("source")}|${e.data("target")}|${e.data("type")}`) && e.addClass("hl"));
  }, [nodes, edges, highlightNodes, highlightEdges]);

  return <div ref={box} className="graph" />;
}
