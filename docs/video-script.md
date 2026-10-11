# Video script (target 2:45, never over 2:59)

Recorded on the flagship case replay (`/cases/flagship?replay=4`), the live Acme world and the evals page.
No music with copyright; no third-party logos. On screen throughout the investigation section, small and steady:
*"Real: GitHub, Vercel, Stripe test mode, analytics, session recordings, Tavily. Simulated: ad platform and traffic."*

| Time | Picture | Voice-over |
|---|---|---|
| 0:00–0:15 | A founder's tabs: analytics, Stripe, Vercel, ads, support inbox, crossfading fast. Freeze on a chart falling. | "Paid signups fell 40% this week. Eight dashboards. Where do you even start?" |
| 0:15–0:35 | Slack-style message from the watcher; the case board opens; seven detectives light up at once. | "Whydunit's watcher noticed first and opened a case. Seven AI detectives start at once, each with its own tools and data: deploys, the funnel, session recordings, payments, ads, support, and the outside world." |
| 0:35–0:50 | Deploy detective close-up: the run-flows tool call; "Nebius Serverless Job" badge; the WebKit failure screenshot; the diff with `requestIdleCallback`. | "The Deploy detective runs signup on every deployment in five real browsers, as a Nebius Serverless Job. One refactor breaks it only on Safari and every iPhone browser, and the diff shows why." |
| 0:50–1:02 | Session detective: keyframes; Omni's sentence about repeated taps on a dead button. | "Nemotron Nano Omni watches the recordings: people fill the form, tap Create account, nothing happens, and they tap again." |
| 1:02–1:15 | Ads and Payments findings side by side; evidence markers pinning onto the wall. | "Meanwhile a teammate cut the ad budget, so paid traffic runs out at noon. And Brazilian banks started declining cards." |
| 1:15–1:30 | World detective: "No external cause found. Checked: …" with Tavily links; then the interrogation thread. | "The World detective checks the news with Tavily, holidays and status pages, and says plainly: nothing external. Then the lead detective, on Nemotron Ultra, cross-examines the team." |
| 1:30–1:55 | The blame waterfall draws in; whiskers; the grey sliver; the "how we know" panel opens. | "Every claim needs evidence; code throws out the rest. A cause needs both a mechanism and matching timing. Then the drop is split with exact Shapley values and confidence intervals: 71% Safari bug, 24% ad budget, 9% card declines, and an honest bit of noise." |
| 1:55–2:25 | Fix panel: PR opens on GitHub; preview passes in all five browsers; approve and merge; ad budget approved; chart recovers; status track moves to Closed. | "Then it fixes things. A pull request, verified on the preview in every browser before anyone merges it. The ad budget, restored with one approval. The watcher sees the metric come back, and only then closes the case." |
| 2:25–2:45 | Quick cuts: the four Nemotron models and Token Factory; the evals table (10/10, zero false accusations); the ad dashboard with its API off, read from a screenshot. | "Nemotron Nano, Super, Ultra and Nano Omni on Nebius Token Factory, Nebius Serverless Jobs, and Tavily. Ten planted scenarios: the right top cause in all ten, and not one false accusation. And when a tool has no API, it reads the dashboard." |
| 2:45 | Wordmark with the evidence marker. | "Whydunit. Know why, fix it, prove it." |

Recording notes: record at 1440×900, replay at 4×; trim tool-call waits; keep cursor movements slow; check the final
cut is under 2:59 and public on YouTube.
