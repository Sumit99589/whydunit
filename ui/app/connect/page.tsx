import { Ladder } from "./Ladder";

export default function Connect() {
  return (
    <div className="mx-auto max-w-[1100px] px-4 py-8 sm:px-6">
      <h1 className="text-[28px] font-bold tracking-tight">Connect your product</h1>
      <p className="mb-6 mt-1 max-w-3xl text-ink-2">
        Detectives ask for evidence by kind, never by vendor. For each kind Whydunit uses the best source it can reach: an
        official API first, then a warehouse, a CSV export, reading the vendor&rsquo;s dashboard from a screenshot, the public
        web, and finally asking you for an upload. Evidence from lower tiers counts for less.
      </p>
      <Ladder />
    </div>
  );
}
