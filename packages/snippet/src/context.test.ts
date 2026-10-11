import { describe, expect, it } from "vitest";
import { attributionFrom, channelOf, parseUA } from "./context";

const UA = {
  iphoneSafari:
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1",
  iphoneChrome:
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/129.0.6668.69 Mobile/15E148 Safari/604.1",
  pixel:
    "Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Mobile Safari/537.36",
  macSafari:
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15",
  winEdge:
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36 Edg/129.0.0.0",
  linuxFirefox: "Mozilla/5.0 (X11; Linux x86_64; rv:131.0) Gecko/20100101 Firefox/131.0",
  ipad:
    "Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
};

describe("parseUA", () => {
  it.each([
    ["iphoneSafari", "Safari", "iOS", "mobile"],
    ["iphoneChrome", "Chrome", "iOS", "mobile"],
    ["pixel", "Chrome", "Android", "mobile"],
    ["macSafari", "Safari", "macOS", "desktop"],
    ["winEdge", "Edge", "Windows", "desktop"],
    ["linuxFirefox", "Firefox", "Linux", "desktop"],
    ["ipad", "Safari", "iPadOS", "tablet"],
  ] as const)("%s", (k, browser, os, device) => {
    expect(parseUA(UA[k])).toEqual({ browser, os, device });
  });
});

describe("attribution and channel", () => {
  it("paid via utm_medium", () => {
    const a = attributionFrom("?utm_source=google&utm_medium=cpc&utm_campaign=brand", "", "acme.app");
    expect(a.utm_campaign).toBe("brand");
    expect(channelOf(a)).toBe("paid");
  });
  it("paid via gclid", () => {
    expect(channelOf(attributionFrom("?gclid=abc", "", "acme.app"))).toBe("paid");
  });
  it("referral from another site, organic from search and self", () => {
    expect(channelOf(attributionFrom("", "https://news.ycombinator.com/item?id=1", "acme.app"))).toBe("referral");
    expect(channelOf(attributionFrom("", "https://www.google.com/", "acme.app"))).toBe("organic");
    expect(channelOf(attributionFrom("", "https://acme.app/pricing", "acme.app"))).toBe("organic");
  });
});
