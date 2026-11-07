import { useState } from "react";
import { api } from "../api";
import Answer from "./Answer.jsx";

// Runs one question through both pipelines over the active group's papers and shows them side by side.
export default function Benchmarks({ docs, activeGroup }) {
  const [question, setQuestion] = useState("");
  const [res, setRes] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  // Only ready papers of the active group can be searched
  const members = new Set(activeGroup?.document_ids || []);
  const readyCount = docs.filter((d) => d.status === "ready" && members.has(d.id)).length;

  async function run() {
    setBusy(true); setError(""); setRes(null);
    try { setRes(await api.benchmark(question, activeGroup.id)); } catch (e) { setError(e.message); }
    setBusy(false);
  }

  return (
    <>
      <section className="card">
        <h2>Benchmarks: Standard RAG vs GraphRAG</h2>
        <textarea value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="Enter one question to run through both pipelines" />
        <div className="row" style={{ marginTop: 8 }}>
          <button className="primary" disabled={busy || question.trim().length < 3 || readyCount === 0} onClick={run}>
            {busy ? "Running both pipelines..." : "Compare"}
          </button>
          <span className="muted">{readyCount} ready paper(s) in group "{activeGroup?.name}"</span>
        </div>
        {error && <div className="err">{error}</div>}
      </section>
      {res && (
        <div className="cols">
          <section className="card">
            <h2>Standard RAG <span className="muted">{res.standard.latency_ms} ms</span></h2>
            <Answer result={res.standard} showGraph={false} />
          </section>
          <section className="card">
            <h2>GraphRAG <span className="muted">{res.graph.latency_ms} ms</span></h2>
            <Answer result={res.graph} />
          </section>
        </div>
      )}
    </>
  );
}
