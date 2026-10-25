import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { ConvexProvider, ConvexReactClient } from "convex/react";
import "@fontsource/atkinson-hyperlegible-next/latin-400.css";
import "@fontsource/atkinson-hyperlegible-next/latin-400-italic.css";
import "@fontsource/atkinson-hyperlegible-next/latin-600.css";
import "@fontsource/atkinson-hyperlegible-next/latin-700.css";
import "@fontsource/atkinson-hyperlegible-next/latin-800.css";
import "@fontsource/atkinson-hyperlegible-mono/latin-400.css";
import "./styles/tokens.css";
import "./styles/app.css";
import { App } from "./App";
import { resolveMode, type AppMode } from "./config";
import { convexBackend } from "./data/convexBackend";
import { createFixtureBackend } from "./data/fixtureBackend";
import { makeFixtures } from "./data/fixtures";

const root = createRoot(document.getElementById("root")!);

// The live room view (/room) talks only to the local Earmark bus, so it needs no Convex.
const isRoom = window.location.pathname.replace(/\/+$/, "") === "/room";
let mode: AppMode = resolveMode(window.location.search, import.meta.env.VITE_CONVEX_URL as string | undefined);

if (isRoom) {
  void import("./room/RoomPage").then(({ RoomPage }) =>
    root.render(
      <StrictMode>
        <RoomPage />
      </StrictMode>,
    ),
  );
} else if (mode.kind === "convex") {
  let client: ConvexReactClient | null = null;
  try {
    client = new ConvexReactClient(mode.url);
  } catch {
    mode = { kind: "unconfigured", reason: "invalid", url: mode.url };
  }
  if (client) {
    root.render(
      <StrictMode>
        <ConvexProvider client={client}>
          <App backend={convexBackend} mode={mode} />
        </ConvexProvider>
      </StrictMode>,
    );
  }
}
if (!isRoom && mode.kind === "demo") {
  root.render(
    <StrictMode>
      <App backend={createFixtureBackend(makeFixtures(Date.now() / 1000))} mode={mode} />
    </StrictMode>,
  );
} else if (!isRoom && mode.kind === "unconfigured") {
  root.render(
    <StrictMode>
      <App backend={null} mode={mode} />
    </StrictMode>,
  );
}
