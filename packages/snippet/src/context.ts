// Pure helpers: user-agent parsing, attribution and channel. No DOM access here, so they are unit-testable.

export interface UAInfo {
  browser: string;
  os: string;
  device: "desktop" | "mobile" | "tablet";
}

export function parseUA(ua: string): UAInfo {
  const s = ua || "";
  let os = "Other";
  if (/iPhone|iPod/.test(s)) os = "iOS";
  else if (/iPad/.test(s) || (/Macintosh/.test(s) && /Mobile\//.test(s))) os = "iPadOS";
  else if (/Android/.test(s)) os = "Android";
  else if (/Windows NT/.test(s)) os = "Windows";
  else if (/Mac OS X|Macintosh/.test(s)) os = "macOS";
  else if (/CrOS/.test(s)) os = "ChromeOS";
  else if (/Linux/.test(s)) os = "Linux";

  // Order matters: Edge and Opera include "Chrome", Chrome includes "Safari", iOS browsers are all WebKit.
  let browser = "Other";
  if (/Edg(e|A|iOS)?\//.test(s)) browser = "Edge";
  else if (/OPR\/|Opera/.test(s)) browser = "Opera";
  else if (/SamsungBrowser\//.test(s)) browser = "Samsung Internet";
  else if (/Firefox\/|FxiOS\//.test(s)) browser = "Firefox";
  else if (/CriOS\//.test(s)) browser = "Chrome";
  else if (/Chrome\/|Chromium\//.test(s)) browser = "Chrome";
  else if (/Safari\//.test(s) && /Version\//.test(s)) browser = "Safari";
  else if (/AppleWebKit\//.test(s) && (os === "iOS" || os === "iPadOS")) browser = "Safari";

  let device: UAInfo["device"] = "desktop";
  if (os === "iPadOS" || /Tablet/.test(s) || (/Android/.test(s) && !/Mobile/.test(s))) device = "tablet";
  else if (/Mobi|iPhone|iPod/.test(s)) device = "mobile";

  return { browser, os, device };
}

export interface Attribution {
  utm_source?: string;
  utm_medium?: string;
  utm_campaign?: string;
  referrer?: string;
}

const PAID = new Set(["cpc", "ppc", "paid", "paid_search", "paidsearch", "display", "paid_social"]);

export function attributionFrom(search: string, referrer: string, ownHost: string): Attribution {
  const q = new URLSearchParams(search);
  const a: Attribution = {};
  for (const k of ["utm_source", "utm_medium", "utm_campaign"] as const) {
    const v = q.get(k);
    if (v) a[k] = v.slice(0, 120);
  }
  if (q.get("gclid") && !a.utm_medium) {
    a.utm_source = a.utm_source || "google";
    a.utm_medium = "cpc";
  }
  if (referrer) {
    try {
      const host = new URL(referrer).host;
      if (host && host !== ownHost) a.referrer = host;
    } catch {
      /* ignore malformed referrer */
    }
  }
  return a;
}

export function channelOf(a: Attribution): "paid" | "referral" | "organic" {
  if (a.utm_medium && PAID.has(a.utm_medium.toLowerCase())) return "paid";
  if (a.utm_source || a.referrer) {
    // Search engines without paid params count as organic search.
    if (!a.utm_source && a.referrer && /(^|\.)(google|bing|duckduckgo|yahoo|ecosia)\./.test(a.referrer)) {
      return "organic";
    }
    return "referral";
  }
  return "organic";
}

export function uid(prefix: string): string {
  const c = (globalThis as { crypto?: Crypto }).crypto;
  const rand = c?.randomUUID ? c.randomUUID().replace(/-/g, "") : Math.random().toString(36).slice(2) + Date.now().toString(36);
  return `${prefix}_${rand.slice(0, 24)}`;
}
