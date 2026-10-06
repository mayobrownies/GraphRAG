import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import GraphView from "./GraphView.jsx";
import { openSource } from "./Answer.jsx";

export default function GraphExplorer({ docs, selected, highlight }) {
  const ready = docs.filter((d) => d.status === "ready").map((d) => d.id);
  const scope = selected.length ? selected : ready;
  const [types, setTypes] = useState([]);
  const [activeTypes, setActiveTypes] = useState([]);
  const [search, setSearch] = useState("");
  const [graph, setGraph] = useState({ nodes: [], edges: [] });
  const [node, setNode] = useState(null);
  const [error, setError] = useState("");
  const [showPath, setShowPath] = useState(true);

  useEffect(() => { api.graphTypes().then(setTypes).catch(() => {}); }, []);

  async function load() {
    setError("");
    try { setGraph(await api.graph(scope, search, activeTypes)); setNode(null); }
    catch (e) { setError(e.message); }
  }
  useEffect(() => { if (scope.length) load(); }, [scope.join(",")]);

  async function select(id) {
    try { setNode(await api.node(id, scope)); } catch (e) { setError(e.message); }
  }

  async function expand() {
    if (!node) return;
    const more = await api.expand(node.id, scope);
    const nodes = new Map(graph.nodes.map((n) => [n.id, n]));
    more.nodes.forEach((n) => nodes.set(n.id, n));
    const key = (e) => `${e.source}|${e.type}|${e.target}|${e.chunk_id}`;
    const edges = new Map(graph.edges.map((e) => [key(e), e]));
    more.edges.forEach((e) => edges.set(key(e), e));
    setGraph({ nodes: [...nodes.values()], edges: [...edges.values()] });
  }

  const hl = useMemo(() => (showPath && highlight ? highlight : null), [showPath, highlight]);
  const toggleType = (t) => setActiveTypes(activeTypes.includes(t) ? activeTypes.filter((x) => x !== t) : [...activeTypes, t]);

  return (
    <>
      <section className="card">
        <h2>Graph Explorer</h2>
        <div className="row">
          <input type="text" style={{ maxWidth: 320 }} placeholder="Search nodes" value={search}
                 onChange={(e) => setSearch(e.target.value)} onKeyDown={(e) => e.key === "Enter" && load()} />
          <button className="primary" onClick={load}>Apply</button>
          <label className="muted"><input type="checkbox" checked={showPath} onChange={(e) => setShowPath(e.target.checked)} /> Highlight last answer path</label>
        </div>
        <div className="row" style={{ marginTop: 8 }}>
          {types.map((t) => (
            <label key={t} className="muted"><input type="checkbox" checked={activeTypes.includes(t)} onChange={() => toggleType(t)} /> {t}</label>
          ))}
        </div>
        {error && <div className="err">{error}</div>}
        {scope.length === 0 && <p className="muted">No ready documents yet. Upload one in the Workspace tab.</p>}
      </section>
      <section className="card">
        <GraphView nodes={graph.nodes} edges={graph.edges}
                   highlightNodes={hl ? hl.paths.flatMap((p) => p.nodes) : []}
                   highlightEdges={hl ? hl.paths.flatMap((p) => p.rels) : []}
                   onSelect={select} />
        <p className="muted">{graph.nodes.length} nodes, {graph.edges.length} relationships. Click a node to inspect it.</p>
      </section>
      {node && (
        <section className="card">
          <h2>{node.name} <span className="muted">({node.type})</span></h2>
          <button className="primary" onClick={expand}>Expand connected nodes</button>
          {node.sources.map((s) => (
            <div className="src" key={s.chunk_id}>
              <strong>{s.doc_name}</strong>, page {s.page}
              <button className="link" onClick={() => openSource(s.doc_id)}>Open PDF</button>
              <div className="muted">{s.snippet}</div>
            </div>
          ))}
        </section>
      )}
    </>
  );
}
