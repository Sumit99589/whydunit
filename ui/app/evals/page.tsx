import { Results } from "./Results";

export default function Evals() {
  return (
    <div className="mx-auto max-w-[1100px] px-4 py-8 sm:px-6">
      <h1 className="text-[28px] font-bold tracking-tight">How often is it right?</h1>
      <p className="mb-6 mt-1 max-w-3xl text-ink-2">
        Ten planted scenarios with known answers, from a single Safari bug to a holiday with a red-herring deploy, a tracking
        bug and plain noise. The detectives never see the answer key. Each row links to its case.
      </p>
      <Results />
    </div>
  );
}
