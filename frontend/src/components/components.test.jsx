import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";

vi.mock("../supabase", () => ({
  supabase: { auth: { getSession: async () => ({ data: { session: { access_token: "t" } } }) } },
}));
vi.mock("./GraphView.jsx", () => ({
  default: ({ nodes, edges }) => <div data-testid="graph">{nodes.length} nodes {edges.length} edges</div>,
}));
vi.mock("../api", () => ({
  api: {
    documents: vi.fn(), upload: vi.fn(), retry: vi.fn(), remove: vi.fn(), query: vi.fn(), benchmark: vi.fn(),
    graph: vi.fn(), graphTypes: vi.fn(), node: vi.fn(), expand: vi.fn(), sourceUrl: vi.fn(),
  },
}));

import { api } from "../api";
import Workspace from "./Workspace.jsx";
import Benchmarks from "./Benchmarks.jsx";
import GraphExplorer from "./GraphExplorer.jsx";
import Answer from "./Answer.jsx";

const DOCS = [
  { id: "1", name: "ready.pdf", status: "ready", is_global: false },
  { id: "2", name: "bad.pdf", status: "failed", error: "The document is empty, has unreadable text, or is image-only.", is_global: false },
  { id: "3", name: "corpus.pdf", status: "ready", is_global: true },
];

beforeEach(() => vi.clearAllMocks());

describe("Workspace", () => {
  it("lists documents with states, errors, and only lets ready documents be selected", async () => {
    api.documents.mockResolvedValue(DOCS);
    const setDocs = vi.fn();
    render(<Workspace docs={DOCS} setDocs={setDocs} selected={[]} setSelected={vi.fn()} setLastGraph={vi.fn()} />);
    expect(await screen.findByText("ready.pdf")).toBeTruthy();
    expect(screen.getByText(/image-only/)).toBeTruthy();
    expect(screen.getByText("(global corpus)")).toBeTruthy();
    const boxes = screen.getAllByRole("checkbox");
    expect(boxes.map((b) => b.disabled)).toEqual([false, true, false]);
    expect(screen.getByText("Retry")).toBeTruthy();
  });

  it("asks a question and renders answer, sources and graph path", async () => {
    api.documents.mockResolvedValue(DOCS);
    api.query.mockResolvedValue({
      answer: "Metformin treats type 2 diabetes.", support: "partial", no_context: false,
      sources: [{ chunk_id: "c1", doc_id: "1", doc_name: "ready.pdf", page: 2, origin: "vector", snippet: "text" }],
      graph: { nodes: [{ id: "a", name: "A", type: "Drug" }], edges: [], paths: [{ nodes: ["a"], rels: [] }] },
    });
    const setLastGraph = vi.fn();
    render(<Workspace docs={DOCS} setDocs={vi.fn()} selected={["1"]} setSelected={vi.fn()} setLastGraph={setLastGraph} />);
    fireEvent.change(screen.getByPlaceholderText(/Ask about/), { target: { value: "What does metformin treat?" } });
    fireEvent.click(screen.getByText("Ask"));
    expect(await screen.findByText("Metformin treats type 2 diabetes.")).toBeTruthy();
    expect(screen.getByText(/page 2/)).toBeTruthy();
    expect(screen.getByText(/Partial support/)).toBeTruthy();
    expect(screen.getByTestId("graph").textContent).toContain("1 nodes");
    expect(api.query).toHaveBeenCalledWith("What does metformin treat?", ["1"], "graph");
    expect(setLastGraph).toHaveBeenCalled();
  });

  it("disables Ask until a document is selected", async () => {
    api.documents.mockResolvedValue(DOCS);
    render(<Workspace docs={DOCS} setDocs={vi.fn()} selected={[]} setSelected={vi.fn()} setLastGraph={vi.fn()} />);
    fireEvent.change(screen.getByPlaceholderText(/Ask about/), { target: { value: "long enough question" } });
    expect(screen.getByText("Ask").disabled).toBe(true);
  });
});

describe("Answer", () => {
  it("shows the no-context message", () => {
    render(<Answer result={{ answer: "No usable context", support: "none", no_context: true, sources: [], graph: { nodes: [], edges: [], paths: [] } }} />);
    expect(screen.getByText(/No supporting evidence/)).toBeTruthy();
  });
});

describe("Benchmarks", () => {
  it("runs both pipelines side by side", async () => {
    const mk = (mode, n) => ({ mode, answer: `${mode} answer`, support: "full", no_context: false, latency_ms: 12, sources: [],
      graph: { nodes: Array(n).fill({ id: "x", name: "X", type: "Drug" }), edges: [], paths: [] } });
    api.benchmark.mockResolvedValue({ standard: mk("standard", 0), graph: mk("graph", 2) });
    render(<Benchmarks docs={DOCS} selected={["1"]} />);
    fireEvent.change(screen.getByPlaceholderText(/one question/), { target: { value: "compare these" } });
    fireEvent.click(screen.getByText("Compare"));
    expect(await screen.findByText("standard answer")).toBeTruthy();
    expect(screen.getByText("graph answer")).toBeTruthy();
    expect(screen.getAllByText("12 ms").length).toBe(2);
  });
});

describe("GraphExplorer", () => {
  it("loads the graph, inspects a node's sources and expands it", async () => {
    api.graphTypes.mockResolvedValue(["Drug", "Disease"]);
    api.graph.mockResolvedValue({ nodes: [{ id: "a", name: "Metformin", type: "Drug" }], edges: [] });
    render(<GraphExplorer docs={DOCS} selected={["1"]} highlight={null} />);
    await waitFor(() => expect(screen.getByTestId("graph").textContent).toContain("1 nodes"));
    expect(screen.getByText("Drug")).toBeTruthy();
    fireEvent.change(screen.getByPlaceholderText("Search nodes"), { target: { value: "metf" } });
    fireEvent.click(screen.getByText("Apply"));
    await waitFor(() => expect(api.graph).toHaveBeenLastCalledWith(["1"], "metf", []));
  });
});
