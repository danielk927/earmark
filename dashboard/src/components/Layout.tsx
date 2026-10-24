import { useState, type ReactNode } from "react";
import { Link, useLocation } from "wouter";
import { fn } from "@contracts/convexFunctions";
import { useBackend, type Connection } from "../data/backend";
import { applyTheme, readTheme, type ThemeChoice } from "../lib/theme";
import { useHref } from "./common";
import { Icon } from "./Icon";

export const NAV = [
  { path: "/", label: "Live map" },
  { path: "/items", label: "Items" },
  { path: "/medications", label: "Medications" },
  { path: "/timeline", label: "Timeline" },
  { path: "/trials", label: "Trials" },
] as const;

export function Layout({ children, connected = true }: { children: ReactNode; connected?: boolean }) {
  return (
    <>
      <a className="skip-link" href="#main">
        Skip to main content
      </a>
      <header className="masthead">
        <div className="masthead-row wrap">
          <Wordmark />
          {connected ? <Household /> : null}
          <div className="masthead-tools">
            {connected ? <ConnectionStatus /> : <ConnectionBadge state="offline" text="Not connected" />}
            <ThemeSwitch />
          </div>
        </div>
        {connected && <MainNav />}
        {connected && <DemoBanner />}
      </header>
      <main id="main" tabIndex={-1} className="wrap">
        {children}
      </main>
      <footer className="colophon wrap">
        <p>
          Earmark has no cameras in the home. It keeps item names, spots, and times, and nothing else about the people
          who live there.
        </p>
        <p>Earmark reports what its sensors detected. It does not give medical advice.</p>
      </footer>
    </>
  );
}

function Wordmark() {
  const href = useHref();
  return (
    <Link href={href("/")} className="wordmark">
      <svg className="wordmark-glyph" viewBox="0 0 32 32" aria-hidden="true" focusable="false">
        <circle cx="9" cy="16" r="5" />
        <path d="M17 9.5a9 9 0 0 1 0 13M22 5.5a15 15 0 0 1 0 21" />
      </svg>
      <span>Earmark</span>
    </Link>
  );
}

function Household() {
  const { useQuery } = useBackend();
  const map = useQuery(fn.dashboard.liveMap, {});
  if (!map) return null;
  return <p className="household">{map.household.name}</p>;
}

function MainNav() {
  const [location] = useLocation();
  const href = useHref();
  return (
    <nav aria-label="Main" className="mainnav wrap">
      <ul>
        {NAV.map((item) => {
          const current = item.path === "/" ? location === "/" : location.startsWith(item.path);
          return (
            <li key={item.path}>
              <Link href={href(item.path)} aria-current={current ? "page" : undefined}>
                {item.label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

const connectionText: Record<Connection, string> = {
  live: "Live",
  connecting: "Connecting",
  offline: "Reconnecting",
  demo: "Demo data",
};

function ConnectionStatus() {
  const state = useBackend().useConnection();
  return <ConnectionBadge state={state} text={connectionText[state]} />;
}

function ConnectionBadge({ state, text }: { state: Connection; text: string }) {
  return (
    <p className={`connection connection-${state}`} role="status">
      <Icon name={state === "live" ? "live" : state === "demo" ? "flask" : "offline"} size={18} />
      <span>
        <span className="visually-hidden">Connection: </span>
        {text}
      </span>
    </p>
  );
}

function DemoBanner() {
  const { kind } = useBackend();
  if (kind !== "demo") return null;
  return (
    <div className="demo-banner">
      <p className="wrap">
        <strong>Demo data.</strong> Nothing here comes from a real home, and changes last only until you reload the
        page.
      </p>
    </div>
  );
}

const THEMES: { value: ThemeChoice; label: string }[] = [
  { value: "system", label: "System" },
  { value: "light", label: "Light" },
  { value: "dark", label: "Dark" },
];

function ThemeSwitch() {
  const [choice, setChoice] = useState<ThemeChoice>(readTheme);
  return (
    <fieldset className="theme-switch">
      <legend>Theme</legend>
      <div className="segmented">
        {THEMES.map((t) => (
          <label key={t.value}>
            <input
              type="radio"
              name="theme"
              value={t.value}
              checked={choice === t.value}
              onChange={() => {
                setChoice(t.value);
                applyTheme(t.value);
              }}
            />
            <span>{t.label}</span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}
