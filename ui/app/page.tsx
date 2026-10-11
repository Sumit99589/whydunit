import Link from "next/link";
import { HeroPreview } from "@/components/HeroPreview";

const STEPS = [
  ["Open a case", "On a metric that moved, or let the watcher open one when it spots a drop."],
  ["Seven detectives investigate at once", "Deploys, the funnel, session recordings, payments, ads, support and the news, each through its own tools."],
  ["The lead cross-examines them", "Claims without evidence are thrown out by code. A cause needs both a mechanism and matching timing."],
  ["The drop is split between causes", "Exact Shapley shares with confidence intervals, plus an honest unexplained share."],
  ["Fixes are opened and verified", "A pull request for a code bug, an approval for a config change, then it watches the metric recover."],
];

export default function Home() {
  return (
    <div className="mx-auto max-w-[1200px] px-4 sm:px-6">
      <section className="grid items-center gap-10 py-12 md:grid-cols-[minmax(0,1.05fr)_minmax(0,0.95fr)] md:py-20">
        <div>
          <h1 className="text-[44px] font-extrabold leading-[1.02] tracking-[-0.035em] sm:text-[64px]">Know why your numbers dropped.</h1>
          <p className="mt-5 max-w-xl text-[18px] leading-relaxed text-ink-2">
            Signups fell 23% since Tuesday? Whydunit sends a team of AI detectives through your deploys, analytics, session
            recordings, ads, payments, support tickets and the news, and comes back with the answer, the proof, the fix, and
            confirmation that the fix worked.
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            <Link href="/cases/flagship?replay=4" className="rounded-lg bg-ink px-4 py-2.5 font-semibold text-bg hover:opacity-90">Watch a solved case</Link>
            <Link href="/playground" className="rounded-lg border border-line bg-surface px-4 py-2.5 font-semibold hover:border-ink-3">Investigate a fixture world</Link>
            <Link href="/connect" className="rounded-lg px-4 py-2.5 font-semibold text-ink-2 hover:text-ink">Connect your product</Link>
          </div>
        </div>
        <HeroPreview />
      </section>
      <section className="border-t border-line py-12" aria-labelledby="how-h">
        <h2 id="how-h" className="text-[22px] font-bold tracking-tight">How a case runs</h2>
        <ol className="mt-6 grid gap-6 md:grid-cols-5">
          {STEPS.map(([t, b], i) => (
            <li key={t}>
              <span className="text-[13px] font-semibold text-ink-3 tabular-nums">{i + 1}</span>
              <h3 className="mt-1 font-semibold leading-snug">{t}</h3>
              <p className="mt-1 text-[14px] leading-relaxed text-ink-2">{b}</p>
            </li>
          ))}
        </ol>
      </section>
      <section className="border-t border-line py-10 text-[14px] text-ink-2" aria-labelledby="real-h">
        <h2 id="real-h" className="font-semibold text-ink">What is real in the demo</h2>
        <p className="mt-2 max-w-3xl leading-relaxed">
          The sandbox startup, Acme Notes, is fictional, but its systems are real: GitHub, Vercel deployments, Stripe in test
          mode, Whydunit&rsquo;s own analytics and session recordings, and live news through Tavily. The ad platform and the
          visitor traffic are simulated, and are labelled that way everywhere. Models: NVIDIA Nemotron Nano, Super, Ultra and
          Nano Omni on Nebius Token Factory.
        </p>
      </section>
    </div>
  );
}
