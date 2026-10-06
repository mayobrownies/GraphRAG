import { api } from "../api";
import GraphView from "./GraphView.jsx";

export async function openSource(docId) {
  const { url } = await api.sourceUrl(docId);
  window.open(url, "_blank", "noopener");
}

export default function Answer({ result, showGraph = true }) {
  if (!result) return null;
  const g = result.graph || { nodes: [], edges: [], paths: [] };
  const pathNodes = g.paths.flatMap((p) => p.nodes);
  const pathEdges = g.paths.flatMap((p) => p.rels);
  return (
    <div>
      <p style={{ whiteSpace: "pre-wrap" }}>{result.answer}</p>
      {result.no_context && <div className="warn">No supporting evidence was found, so no answer was generated.</div>}
      {result.support === "partial" && <div className="warn">Partial support: the evidence shown is insufficient.</div>}
      {result.sources?.length > 0 && <h3 style={{ fontSize: 14 }}>Sources</h3>}
      {result.sources?.map((s) => (
        <div className="src" key={s.chunk_id}>
          <strong>{s.doc_name}</strong>, page {s.page} <span className="muted">({s.origin})</span>
          <button className="link" onClick={() => openSource(s.doc_id)}>Open PDF</button>
          <div className="muted">{s.snippet}</div>
        </div>
      ))}
      {showGraph && g.nodes.length > 0 && (
        <>
          <h3 style={{ fontSize: 14 }}>Graph path used ({g.nodes.length} nodes, {g.edges.length} relationships)</h3>
          <GraphView nodes={g.nodes} edges={g.edges} highlightNodes={pathNodes} highlightEdges={pathEdges} />
        </>
      )}
    </div>
  );
}
