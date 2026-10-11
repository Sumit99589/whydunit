import type { Metadata } from "next";
import { Schibsted_Grotesk } from "next/font/google";
import Link from "next/link";
import { ThemeToggle } from "@/components/ThemeToggle";
import { Marker } from "@/components/Marker";
import "./globals.css";

const schibsted = Schibsted_Grotesk({ variable: "--font-schibsted", subsets: ["latin"], weight: ["400", "500", "600", "700", "800"] });

export const metadata: Metadata = {
  title: "Whydunit",
  description: "A team of AI detectives that finds out why your numbers dropped, proves it, fixes it, and confirms the fix worked.",
};

const themeInit = `try{var t=localStorage.getItem("wd-theme");if(t)document.documentElement.dataset.theme=t}catch(e){}`;

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${schibsted.variable} h-full antialiased`} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeInit }} />
      </head>
      <body className="flex min-h-full flex-col font-sans">
        <header className="border-b border-line">
          <div className="mx-auto flex max-w-[1400px] items-center gap-6 px-4 py-3 sm:px-6">
            <Link href="/" className="flex items-center gap-2 text-[17px] font-bold tracking-tight">
              <Marker n="?" size={22} />
              Whydunit
            </Link>
            <nav className="flex flex-1 items-center gap-1 overflow-x-auto text-sm text-ink-2">
              <Link className="rounded-md px-2.5 py-1.5 hover:bg-surface-2 hover:text-ink" href="/cases">Cases</Link>
              <Link className="rounded-md px-2.5 py-1.5 hover:bg-surface-2 hover:text-ink" href="/playground">Playground</Link>
              <Link className="rounded-md px-2.5 py-1.5 hover:bg-surface-2 hover:text-ink" href="/connect">Connect</Link>
              <Link className="rounded-md px-2.5 py-1.5 hover:bg-surface-2 hover:text-ink" href="/evals">Evals</Link>
            </nav>
            <ThemeToggle />
          </div>
        </header>
        <main className="flex-1">{children}</main>
      </body>
    </html>
  );
}
