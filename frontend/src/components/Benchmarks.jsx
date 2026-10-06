import { useState } from "react";
import { api } from "../api";
import Answer from "./Answer.jsx";

export default function Benchmarks({ docs, selected }) {
  const [question, setQuestion] = useState("");
  const [res, setRes] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const ready = docs.filter((d) => d.status === "ready").map((d) => d.id);
  const scope = selected.length ? selected : ready;

  async function run() {
    setBusy(true); setError(""); setRes(null);
    try { setRes(await api.benchmark(question, scope)); } catch (e) { setError(e.message); }
    setBusy(false);
  }

  return (
    <>
      <section className="card">
        <h2>Benchmarks: Standard RAG vs GraphRAG</h2>
        <textarea value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="Enter one question to run through both pipelines" />
        <div className="row" style={{ marginTop: 8 }}>
          <button className="primary" disabled={busy || question.trim().length < 3 || scope.length === 0} onClick={run}>
            {busy ? "Running both pipelines..." : "Compare"}
          </button>
          <span className="muted">{scope.length} document(s) in scope</span>
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
