import LiveAsk from "@/components/LiveAsk";
import { PageHeader } from "@/components/ui";
import { fetchExamples, fetchHealth } from "@/lib/api";

export default async function LivePage() {
  const [examples, health] = await Promise.all([fetchExamples(), fetchHealth()]);
  return (
    <>
      <PageHeader
        title="Live ask"
        subtitle="Ask one question and watch RAG, GraphRAG and the agent answer it side by side. Each answer cites its evidence; click a marker to read it."
      />
      <LiveAsk
        examples={examples.ok ? examples.data : []}
        demoMode={health.ok ? health.data.demo_mode : false}
        hasKey={health.ok ? health.data.llm_key : true}
      />
    </>
  );
}
