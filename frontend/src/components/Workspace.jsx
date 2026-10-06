import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import Answer from "./Answer.jsx";

export default function Workspace({ docs, setDocs, selected, setSelected, setLastGraph }) {
  const fileRef = useRef(null);
  const [msg, setMsg] = useState("");
  const [question, setQuestion] = useState("");
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const [qError, setQError] = useState("");

  const refresh = () => api.documents().then(setDocs).catch((e) => setMsg(e.message));
  useEffect(() => { refresh(); }, []);
  useEffect(() => {
    if (!docs.some((d) => d.status === "processing")) return;
    const t = setInterval(refresh, 3000);
    return () => clearInterval(t);
  }, [docs]);

  async function upload(e) {
    const file = e.target.files[0];
    e.target.value = "";
    if (!file) return;
    setMsg("");
    try { await api.upload(file); refresh(); }
    catch (err) {
      if (err.status === 409) {
        setMsg(err.message);
        if (window.confirm("This document already exists. Replace it and re-index?")) {
          try { await api.upload(file, true); setMsg(""); refresh(); } catch (e2) { setMsg(e2.message); }
        }
      } else setMsg(err.message);
    }
  }

  const toggle = (id) => setSelected(selected.includes(id) ? selected.filter((x) => x !== id) : [...selected, id]);

  async function ask() {
    setBusy(true); setQError(""); setResult(null);
    try {
      const r = await api.query(question, selected, "graph");
      setResult(r); setLastGraph(r.graph);
    } catch (e) { setQError(e.message); }
    setBusy(false);
  }

  return (
    <>
      <section className="card">
        <h2>Documents</h2>
        <div className="row">
          <input ref={fileRef} type="file" accept="application/pdf" onChange={upload} />
        </div>
        {msg && <div className="err">{msg}</div>}
        <table>
          <thead><tr><th></th><th>Name</th><th>State</th><th></th></tr></thead>
          <tbody>
            {docs.map((d) => (
              <tr key={d.id}>
                <td><input type="checkbox" disabled={d.status !== "ready"} checked={selected.includes(d.id)} onChange={() => toggle(d.id)} /></td>
                <td>{d.name} {d.is_global && <span className="muted">(global corpus)</span>}</td>
                <td>
                  <span className={`badge ${d.status}`}>{d.status}</span>
                  {d.status === "processing" && <div className="muted">{d.stage}</div>}
                  {d.status === "failed" && <div className="err">{d.error}</div>}
                </td>
                <td>
                  {d.status === "failed" && !d.is_global && <button className="link" onClick={() => api.retry(d.id).then(refresh)}>Retry</button>}
                  {!d.is_global && <button className="link" onClick={() => window.confirm("Delete this document and its index?") && api.remove(d.id).then(refresh)}>Delete</button>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
      <section className="card">
        <h2>Ask a question</h2>
        <textarea value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="Ask about the selected documents" />
        <div className="row" style={{ marginTop: 8 }}>
          <button className="primary" disabled={busy || question.trim().length < 3 || selected.length === 0} onClick={ask}>
            {busy ? "Working..." : "Ask"}
          </button>
          <span className="muted">{selected.length} document(s) selected</span>
        </div>
        {qError && <div className="err">{qError}</div>}
      </section>
      {result && <section className="card"><h2>Answer</h2><Answer result={result} /></section>}
    </>
  );
}
