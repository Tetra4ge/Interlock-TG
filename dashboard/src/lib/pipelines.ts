import type { PipelineKey } from "./types";

export interface PipelineMeta {
  key: PipelineKey;
  label: string;
  short: string;
  color: string; // colourblind-friendly: blue / emerald / purple
  blurb: string;
}

export const PIPELINES: Record<PipelineKey, PipelineMeta> = {
  rag: {
    key: "rag",
    label: "RAG",
    short: "RAG",
    color: "#60a5fa",
    blurb: "Vector + keyword retrieval, one answer call.",
  },
  graphrag: {
    key: "graphrag",
    label: "GraphRAG",
    short: "GraphRAG",
    color: "#34d399",
    blurb: "Links entities, expands a bounded subgraph, one answer call.",
  },
  agent: {
    key: "agent",
    label: "Agentic GraphRAG",
    short: "Agent",
    color: "#a78bfa",
    blurb: "Tool-using loop under budgets, then a verified answer.",
  },
};

export const PIPELINE_ORDER: PipelineKey[] = ["rag", "graphrag", "agent"];

export function isPipelineKey(value: string): value is PipelineKey {
  return value === "rag" || value === "graphrag" || value === "agent";
}

export const DISCLAIMER =
  "Research demo. Facts are extracted automatically from public filings and may contain errors; " +
  "verify against the cited source. Not investment advice.";
