import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import GraphView from "./GraphView.jsx";
import { openSource } from "./Answer.jsx";

/**
 * Graph Explorer tab: manage groups, choose which library papers belong to the active group,
 * and explore the group's paper graph (papers linked by embedding similarity).
 *
 * Props (state owned by App.jsx):
 *   docs, setDocs                 - the user's library
 *   groups, setGroups             - the user's groups; membership calls return the updated group
 *   activeGroup, setActiveGroupId - the group being edited/explored
 *   refreshGroups                 - re-fetches groups (after deleting one the server may create "Group 1")
 *   highlight                     - the last answer's graph, whose paths can be highlighted
 */
export default function GraphExplorer({ docs, setDocs, groups, setGroups, activeGroup, setActiveGroupId, refreshGroups, highlight }) {
  const [search, setSearch] = useState("");
  const [graph, setGraph] = useState({ nodes: [], edges: [] });
  const [nodeId, setNodeId] = useState(null);
  const [error, setError] = useState("");
  const [showPath, setShowPath] = useState(true);

  const groupId = activeGroup?.id;
  const members = activeGroup?.document_ids || [];
  const memberKey = members.join(",");

  // Load the library so the papers panel is current even if the Workspace tab was never opened.
  useEffect(() => { api.documents().then(setDocs).catch((e) => setError(e.message)); }, []);

  async function load() {
    if (!groupId) return;
    setError("");
    try { setGraph(await api.groupGraph(groupId, search)); setNodeId(null); }
    catch (e) { setError(e.message); }
  }
  // Reload whenever the active group or its membership changes.
  useEffect(() => { load(); }, [groupId, memberKey]);

  // Run a group call and surface any API error (e.g. 409 name already taken) in the error line.
  async function attempt(fn) {
    setError("");
    try { await fn(); } catch (e) { setError(e.message); }
  }
  // Swap one group in state for the record the server returned.
  const replaceGroup = (g) => setGroups((gs) => gs.map((x) => (x.id === g.id ? g : x)));

  const createGroup = () => {
    const name = window.prompt("Name for the new group");
    if (!name?.trim()) return;
    attempt(async () => {
      const g = await api.createGroup(name.trim());
      setGroups((gs) => [...gs, g]);
      setActiveGroupId(g.id);
    });
  };
  const renameGroup = () => {
    const name = window.prompt("Rename group", activeGroup.name);
    if (!name?.trim() || name.trim() === activeGroup.name) return;
    attempt(async () => replaceGroup(await api.renameGroup(groupId, name.trim())));
  };
  const deleteGroup = () => {
    if (!window.confirm(`Delete group "${activeGroup.name}"? Its papers stay in your library.`)) return;
    attempt(async () => { await api.deleteGroup(groupId); await refreshGroups(); });
  };

  // Tick adds the paper to the active group, untick removes it (it stays in the library).
  const setMember = (docId, inGroup) =>
    attempt(async () => replaceGroup(await (inGroup ? api.addToGroup : api.removeFromGroup)(groupId, docId)));

  const hl = useMemo(() => (showPath && highlight ? highlight : null), [showPath, highlight]);

  // Details of the clicked paper: its name and its links in the current graph, strongest first.
  const node = graph.nodes.find((n) => n.doc_id === nodeId);
  const names = new Map(graph.nodes.map((n) => [n.doc_id, n.name]));
  const links = node
    ? graph.edges
      .filter((e) => e.source === nodeId || e.target === nodeId)
      .map((e) => {
        const other = e.source === nodeId ? e.target : e.source;
        return { id: other, name: names.get(other) || other, weight: e.weight };
      })
      .sort((a, b) => b.weight - a.weight)
    : [];

  return (
    <>
      <section className="card">
        <h2>Groups</h2>
        <div className="row">
          {groups.map((g) => (
            <button key={g.id} className={`tab ${g.id === groupId ? "active" : ""}`} onClick={() => setActiveGroupId(g.id)}>{g.name}</button>
          ))}
          <button className="link" onClick={createGroup}>New group</button>
          <button className="link" disabled={!activeGroup} onClick={renameGroup}>Rename</button>
          <button className="link" disabled={!activeGroup} onClick={deleteGroup}>Delete</button>
        </div>
        {error && <div className="err">{error}</div>}
      </section>
      <section className="card">
        <h2>Papers in "{activeGroup?.name}"</h2>
        <p className="muted">Tick the library papers that belong to this group. Only ready papers appear in the graph.</p>
        <table>
          <tbody>
            {docs.map((d) => {
              const inGroup = members.includes(d.id);
              return (
                <tr key={d.id}>
                  <td>
                    <label>
                      <input type="checkbox" aria-label={`${d.name} in this group`} disabled={!activeGroup}
                             checked={inGroup} onChange={() => setMember(d.id, !inGroup)} /> {d.name}
                    </label>
                  </td>
                  <td><span className={`badge ${d.status}`}>{d.status}</span></td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {docs.length === 0 && <p className="muted">Your library is empty. Upload a PDF in the Workspace tab.</p>}
      </section>
      <section className="card">
        <h2>Paper graph</h2>
        <div className="row" style={{ marginBottom: 8 }}>
          <input type="text" style={{ maxWidth: 320 }} placeholder="Search papers" value={search}
                 onChange={(e) => setSearch(e.target.value)} onKeyDown={(e) => e.key === "Enter" && load()} />
          <button className="primary" onClick={load}>Apply</button>
          <label className="muted"><input type="checkbox" checked={showPath} onChange={(e) => setShowPath(e.target.checked)} /> Highlight last answer path</label>
        </div>
        <GraphView nodes={graph.nodes} edges={graph.edges}
                   highlightNodes={hl ? hl.paths.flatMap((p) => p.nodes) : []}
                   highlightEdges={hl ? hl.paths.flatMap((p) => p.rels) : []}
                   onSelect={setNodeId} />
        <p className="muted">{graph.nodes.length} papers, {graph.edges.length} links. Click a paper to inspect it.</p>
      </section>
      {node && (
        <section className="card">
          <h2>{node.name}</h2>
          <div className="row">
            <button className="link" onClick={() => openSource(node.doc_id)}>Open PDF</button>
            <button className="link" onClick={() => setMember(node.doc_id, false)}>Remove from group</button>
          </div>
          {links.length === 0 && <p className="muted">No linked papers in this graph.</p>}
          <table>
            <tbody>
              {links.map((l) => (
                <tr key={l.id}><td>{l.name}</td><td>{l.weight.toFixed(2)}</td></tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
    </>
  );
}
