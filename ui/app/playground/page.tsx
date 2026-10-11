import { Playground } from "./Playground";

export default function PlaygroundPage() {
  return (
    <div className="mx-auto max-w-[1000px] px-4 py-8 sm:px-6">
      <h1 className="text-[28px] font-bold tracking-tight">Playground</h1>
      <p className="mb-6 mt-1 max-w-2xl text-ink-2">
        Each world is two weeks of a sandbox startup&rsquo;s data with problems planted at known times. Pick one and watch the
        detectives work. The answer key is hidden from them; the evals page shows how often they get it right.
      </p>
      <Playground />
    </div>
  );
}
