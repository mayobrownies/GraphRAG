import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { useState } from "react";

vi.mock("../supabase", () => ({
  supabase: { auth: { getSession: async () => ({ data: { session: { access_token: "t" } } }) } },
}));
vi.mock("./GraphView.jsx", () => ({
  default: ({ nodes, edges, onSelect }) => (
    <div data-testid="graph">
      {nodes.length} nodes {edges.length} edges
      {nodes.map((n) => <button key={n.doc_id} onClick={() => onSelect && onSelect(n.doc_id)}>node {n.name}</button>)}
    </div>
  ),
}));
vi.mock("../api", () => ({
  api: {
    documents: vi.fn(), upload: vi.fn(), retry: vi.fn(), remove: vi.fn(), sourceUrl: vi.fn(),
    groups: vi.fn(), createGroup: vi.fn(), renameGroup: vi.fn(), deleteGroup: vi.fn(),
    addToGroup: vi.fn(), removeFromGroup: vi.fn(), groupGraph: vi.fn(),
    query: vi.fn(), benchmark: vi.fn(),
  },
}));

import { api } from "../api";
import Workspace from "./Workspace.jsx";
import Benchmarks from "./Benchmarks.jsx";
import GraphExplorer from "./GraphExplorer.jsx";
import Answer from "./Answer.jsx";

const DOCS = [
  { id: "1", name: "ready.pdf", status: "ready" },
  { id: "2", name: "bad.pdf", status: "failed", error: "The document is empty, has unreadable text, or is image-only." },
  { id: "3", name: "other.pdf", status: "ready" },
];
const G1 = { id: "g1", name: "Group 1", document_ids: ["1"] };
const EMPTY = { id: "g2", name: "AI research", document_ids: ["2"] };

beforeEach(() => {
  vi.clearAllMocks();
  api.documents.mockResolvedValue(DOCS);
  api.groupGraph.mockResolvedValue({ nodes: [], edges: [] });
});

// Hosts the group state like App.jsx does, so components see the records the API returns.
function WithGroups({ initial, children }) {
  const [groups, setGroups] = useState(initial);
  const [activeId, setActiveGroupId] = useState(initial[0].id);
  const activeGroup = groups.find((g) => g.id === activeId) || groups[0];
  const refreshGroups = () => api.groups().then(setGroups);
  return children({ groups, setGroups, activeGroup, setActiveGroupId, refreshGroups });
}

function renderWorkspace(groups) {
  return render(
    <WithGroups initial={groups}>
      {(p) => <Workspace docs={DOCS} setDocs={vi.fn()} setLastGraph={vi.fn()} {...p} />}
    </WithGroups>,
  );
}

function renderExplorer(groups, highlight = null) {
  return render(
    <WithGroups initial={groups}>
      {(p) => <GraphExplorer docs={DOCS} setDocs={vi.fn()} highlight={highlight} {...p} />}
    </WithGroups>,
  );
}

describe("Workspace", () => {
  it("lists library papers with states and errors, offering Retry only for failed ones", async () => {
    renderWorkspace([G1]);
    expect(await screen.findByText("ready.pdf")).toBeTruthy();
    expect(screen.getByText(/image-only/)).toBeTruthy();
    expect(screen.getAllByText("Retry").length).toBe(1);
    expect(screen.getAllByText("Delete").length).toBe(3);
  });

  it("asks over the active group and renders answer, sources and graph path", async () => {
    api.query.mockResolvedValue({
      answer: "Metformin treats type 2 diabetes.", support: "partial", no_context: false,
      sources: [{ chunk_id: "c1", doc_id: "1", doc_name: "ready.pdf", page: 2, origin: "vector", snippet: "text" }],
      graph: { nodes: [{ doc_id: "1", name: "ready.pdf" }], edges: [], paths: [{ nodes: ["1"], rels: [] }] },
    });
    renderWorkspace([G1]);
    expect(screen.getByText("1 ready paper(s) in this group")).toBeTruthy();
    fireEvent.change(screen.getByPlaceholderText(/Ask about/), { target: { value: "What does metformin treat?" } });
    fireEvent.click(screen.getByText("Ask"));
    expect(await screen.findByText("Metformin treats type 2 diabetes.")).toBeTruthy();
    expect(screen.getByText(/page 2/)).toBeTruthy();
    expect(screen.getByText(/Partial support/)).toBeTruthy();
    expect(screen.getByTestId("graph").textContent).toContain("1 nodes");
    expect(api.query).toHaveBeenCalledWith("What does metformin treat?", "g1");
  });

  it("disables Ask until the active group has a ready paper", async () => {
    renderWorkspace([EMPTY, G1]);
    fireEvent.change(screen.getByPlaceholderText(/Ask about/), { target: { value: "long enough question" } });
    expect(screen.getByText("Ask").disabled).toBe(true);
    expect(screen.getByText(/Add ready papers to it in the Graph Explorer/)).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Ask over group"), { target: { value: "g1" } });
    expect(screen.getByText("Ask").disabled).toBe(false);
  });
});

describe("GraphExplorer", () => {
  it("creates a group and makes it active", async () => {
    api.createGroup.mockResolvedValue({ id: "g3", name: "Medical research", document_ids: [] });
    vi.spyOn(window, "prompt").mockReturnValue("Medical research");
    renderExplorer([G1]);
    fireEvent.click(screen.getByText("New group"));
    expect(await screen.findByText('Papers in "Medical research"')).toBeTruthy();
    expect(api.createGroup).toHaveBeenCalledWith("Medical research");
  });

  it("shows API errors such as a taken group name", async () => {
    api.createGroup.mockRejectedValue(new Error("A group with that name already exists"));
    vi.spyOn(window, "prompt").mockReturnValue("Group 1");
    renderExplorer([G1]);
    fireEvent.click(screen.getByText("New group"));
    expect(await screen.findByText("A group with that name already exists")).toBeTruthy();
  });

  it("adds and removes papers, with the checkbox following the returned group", async () => {
    api.addToGroup.mockResolvedValue({ ...G1, document_ids: ["1", "3"] });
    api.removeFromGroup.mockResolvedValue({ ...G1, document_ids: ["3"] });
    renderExplorer([G1]);
    const other = screen.getByLabelText("other.pdf in this group");
    const ready = screen.getByLabelText("ready.pdf in this group");
    expect(other.checked).toBe(false);
    expect(ready.checked).toBe(true);
    fireEvent.click(other);
    await waitFor(() => expect(other.checked).toBe(true));
    expect(api.addToGroup).toHaveBeenCalledWith("g1", "3");
    fireEvent.click(ready);
    await waitFor(() => expect(ready.checked).toBe(false));
    expect(api.removeFromGroup).toHaveBeenCalledWith("g1", "1");
    // Membership changes reload the group's graph
    await waitFor(() => expect(api.groupGraph).toHaveBeenCalledTimes(3));
  });

  it("renders the group graph counts, searches it, and inspects a paper's links", async () => {
    api.groupGraph.mockResolvedValue({
      nodes: [{ doc_id: "1", name: "ready.pdf" }, { doc_id: "3", name: "other.pdf" }],
      edges: [{ source: "1", target: "3", weight: 0.8123 }],
    });
    renderExplorer([{ ...G1, document_ids: ["1", "3"] }]);
    expect(await screen.findByText(/2 papers, 1 links/)).toBeTruthy();
    fireEvent.change(screen.getByPlaceholderText("Search papers"), { target: { value: "ready" } });
    fireEvent.click(screen.getByText("Apply"));
    await waitFor(() => expect(api.groupGraph).toHaveBeenLastCalledWith("g1", "ready"));
    fireEvent.click(screen.getByText("node ready.pdf"));
    expect(await screen.findByText("0.81")).toBeTruthy();
    expect(screen.getByText("Open PDF")).toBeTruthy();
    expect(screen.getByText("Remove from group")).toBeTruthy();
  });

  it("deletes a group only after confirming, then reloads groups", async () => {
    api.groups.mockResolvedValue([{ id: "g9", name: "Group 1", document_ids: [] }]);
    const confirm = vi.spyOn(window, "confirm").mockReturnValueOnce(false).mockReturnValueOnce(true);
    renderExplorer([EMPTY]);
    fireEvent.click(screen.getByText("Delete"));
    expect(confirm.mock.calls[0][0]).toMatch(/papers stay in your library/);
    expect(api.deleteGroup).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText("Delete"));
    await waitFor(() => expect(api.deleteGroup).toHaveBeenCalledWith("g2"));
    expect(await screen.findByText('Papers in "Group 1"')).toBeTruthy();
  });
});

describe("Answer", () => {
  it("shows the no-context message", () => {
    render(<Answer result={{ answer: "No usable context", support: "none", no_context: true, sources: [], graph: { nodes: [], edges: [], paths: [] } }} />);
    expect(screen.getByText(/No supporting evidence/)).toBeTruthy();
  });
});

describe("Benchmarks", () => {
  it("runs both pipelines side by side over the active group", async () => {
    const mk = (mode, n) => ({ mode, answer: `${mode} answer`, support: "full", no_context: false, latency_ms: 12, sources: [],
      graph: { nodes: Array.from({ length: n }, (_, i) => ({ doc_id: `${i}`, name: `p${i}` })), edges: [], paths: [] } });
    api.benchmark.mockResolvedValue({ standard: mk("standard", 0), graph: mk("graph", 2) });
    render(<Benchmarks docs={DOCS} activeGroup={G1} />);
    expect(screen.getByText(/1 ready paper\(s\) in group "Group 1"/)).toBeTruthy();
    fireEvent.change(screen.getByPlaceholderText(/one question/), { target: { value: "compare these" } });
    fireEvent.click(screen.getByText("Compare"));
    expect(await screen.findByText("standard answer")).toBeTruthy();
    expect(screen.getByText("graph answer")).toBeTruthy();
    expect(screen.getAllByText("12 ms").length).toBe(2);
    expect(api.benchmark).toHaveBeenCalledWith("compare these", "g1");
  });

  it("is disabled when the active group has no ready paper", () => {
    render(<Benchmarks docs={DOCS} activeGroup={EMPTY} />);
    fireEvent.change(screen.getByPlaceholderText(/one question/), { target: { value: "compare these" } });
    expect(screen.getByText("Compare").disabled).toBe(true);
  });
});
