import { useEffect, useRef } from "react";
import { Route, Switch, useLocation } from "wouter";
import type { AppMode } from "./config";
import { BackendProvider, type Backend } from "./data/backend";
import { ErrorBoundary, markNavigated } from "./components/common";
import { Layout } from "./components/Layout";
import { ItemsPage } from "./pages/ItemsPage";
import { LiveMapPage } from "./pages/LiveMapPage";
import { MedicationsPage } from "./pages/MedicationsPage";
import { NotConnectedPage, NotFoundPage } from "./pages/StatePages";
import { TimelinePage } from "./pages/TimelinePage";
import { TrialsPage } from "./pages/TrialsPage";

function NavigationWatcher() {
  const [location] = useLocation();
  const first = useRef(true);
  useEffect(() => {
    if (first.current) first.current = false;
    else markNavigated();
  }, [location]);
  return null;
}

const routes = [
  { path: "/", what: "the live map", Page: LiveMapPage },
  { path: "/items", what: "items", Page: ItemsPage },
  { path: "/medications", what: "medications", Page: MedicationsPage },
  { path: "/timeline", what: "the timeline", Page: TimelinePage },
  { path: "/trials", what: "trials", Page: TrialsPage },
];

export function App({ backend, mode }: { backend: Backend | null; mode?: AppMode }) {
  if (!backend) {
    const m = mode?.kind === "unconfigured" ? mode : ({ kind: "unconfigured", reason: "missing" } as const);
    return (
      <Layout connected={false}>
        <NotConnectedPage mode={m} />
      </Layout>
    );
  }
  return (
    <BackendProvider backend={backend}>
      <NavigationWatcher />
      <Layout>
        <Switch>
          {routes.map(({ path, what, Page }) => (
            <Route key={path} path={path}>
              <ErrorBoundary what={what}>
                <Page />
              </ErrorBoundary>
            </Route>
          ))}
          <Route>
            <NotFoundPage />
          </Route>
        </Switch>
      </Layout>
    </BackendProvider>
  );
}
