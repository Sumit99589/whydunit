import { Suspense } from "react";
import { CaseBoard } from "./CaseBoard";

export default function CasePage({ params, searchParams }: PageProps<"/cases/[id]">) {
  const replay = searchParams.then((q) => (typeof q.replay === "string" ? q.replay : null));
  return (
    <Suspense fallback={<div className="mx-auto max-w-[1400px] px-6 py-10 text-ink-3">Opening the case file…</div>}>
      <CaseBoard params={params} replayParam={replay} />
    </Suspense>
  );
}
