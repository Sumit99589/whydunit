import { CaseList } from "./CaseList";

export default function Cases() {
  return (
    <div className="mx-auto max-w-[1000px] px-4 py-8 sm:px-6">
      <h1 className="text-[28px] font-bold tracking-tight">Cases</h1>
      <p className="mb-6 mt-1 text-ink-2">Every investigation, newest first. Cases the watcher opened by itself are marked.</p>
      <CaseList />
    </div>
  );
}
