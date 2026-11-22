import { WorkflowGraph } from "@/features/workflow-graph";

export default async function WorkflowPage({
  searchParams,
}: {
  searchParams: Promise<{ job?: string | string[] }>;
}) {
  const { job } = await searchParams;
  const targetJobId =
    typeof job === "string" &&
    /^[\da-f]{8}(?:-[\da-f]{4}){3}-[\da-f]{12}$/i.test(job)
      ? job
      : undefined;
  return <WorkflowGraph targetJobId={targetJobId} />;
}
