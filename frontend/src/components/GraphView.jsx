import { useEffect, useRef } from "react";
import cytoscape from "cytoscape";

// Undirected edges are matched by their unordered pair of paper ids.
const pairKey = (a, b) => (a < b ? `${a}|${b}` : `${b}|${a}`);

// Paper graph: one node per paper (id = doc_id), undirected edges weighted by embedding similarity.
// Edge width grows with the weight; the label shows it to 2 decimals.
export default function GraphView({ nodes, edges, highlightNodes = [], highlightEdges = [], onSelect }) {
  const box = useRef(null);
  const cy = useRef(null);
  // Cytoscape's tap handler is registered once, so it reads the latest callback through a ref.
  const onSelectRef = useRef(onSelect);
  useEffect(() => { onSelectRef.current = onSelect; });

  useEffect(() => {
    cy.current = cytoscape({
      container: box.current,
      style: [
        { selector: "node", style: { label: "data(name)", "font-size": 10, "background-color": "#2457d6", width: 18, height: 18, "text-valign": "bottom", "text-margin-y": 4 } },
        { selector: "edge", style: { label: "data(label)", "font-size": 8, width: "mapData(weight, 0.3, 1, 1, 6)", "line-color": "#c0c6d0", "curve-style": "bezier" } },
        { selector: ".hl", style: { "line-color": "#f04438", "border-width": 3, "border-color": "#f04438" } },
      ],
    });
    cy.current.on("tap", "node", (e) => onSelectRef.current && onSelectRef.current(e.target.id()));
    return () => cy.current && cy.current.destroy();
  }, []);

  useEffect(() => {
    const c = cy.current;
    if (!c) return;
    const nodeIds = new Set(nodes.map((n) => n.doc_id));
    const els = [
      ...nodes.map((n) => ({ data: { id: n.doc_id, name: n.name } })),
      ...edges.filter((e) => nodeIds.has(e.source) && nodeIds.has(e.target))
        .map((e, i) => ({ data: { id: `e${i}-${e.source}-${e.target}`, source: e.source, target: e.target, weight: e.weight, label: e.weight.toFixed(2) } })),
    ];
    c.elements().remove();
    c.add(els);
    c.layout({ name: "cose", animate: false, fit: true, padding: 20 }).run();
    const hn = new Set(highlightNodes);
    const he = new Set(highlightEdges.map((e) => pairKey(e.source, e.target)));
    c.nodes().forEach((n) => hn.has(n.id()) && n.addClass("hl"));
    c.edges().forEach((e) => he.has(pairKey(e.data("source"), e.data("target"))) && e.addClass("hl"));
  }, [nodes, edges, highlightNodes, highlightEdges]);

  return <div ref={box} className="graph" />;
}
