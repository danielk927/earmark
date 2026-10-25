import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link } from "wouter";
import { fn, type LiveMap, type ObjectStateRow } from "@contracts/convexFunctions";
import { useBackend } from "../data/backend";
import { describeChanges } from "../lib/changes";
import { formatAgo, formatWhen } from "../lib/time";
import { anchorWords, capitalize, poseSourceWords, poseWords, statusText, theSpot, whereText, type StatusKey } from "../lib/words";
import { Loading, Notice, Page, StatusText, TableScroll, useHref, useNow, type Tone } from "../components/common";
import type { IconName } from "../components/Icon";
import { MapField } from "./MapField";

export const statusLook: Record<StatusKey, { icon: IconName; tone: Tone }> = {
  on_spot: { icon: "onSpot", tone: "ok" },
  held: { icon: "held", tone: "warn" },
  missing: { icon: "missing", tone: "bad" },
  roaming: { icon: "roaming", tone: "idle" },
  no_reading: { icon: "pending", tone: "idle" },
  unlabeled: { icon: "newItem", tone: "accent" },
};

export function ObjectStatus({ status }: { status: StatusKey }) {
  const look = statusLook[status];
  return (
    <StatusText icon={look.icon} tone={look.tone}>
      {statusText[status]}
    </StatusText>
  );
}

interface Change {
  id: number;
  text: string;
  t: number;
}

/** Remembers the previous snapshot and turns differences into sentences. */
function useChanges(map: LiveMap | undefined) {
  const prev = useRef<LiveMap | undefined>(undefined);
  const counter = useRef(0);
  const [changes, setChanges] = useState<Change[]>([]);
  const [announcement, setAnnouncement] = useState("");
  useEffect(() => {
    if (!map) return;
    if (prev.current) {
      const sentences = describeChanges(prev.current, map);
      if (sentences.length) {
        const t = Date.now() / 1000;
        setChanges((old) => [...sentences.map((text) => ({ id: ++counter.current, text, t })).reverse(), ...old].slice(0, 6));
        setAnnouncement(sentences.join(" "));
      }
    }
    prev.current = map;
  }, [map]);
  return { changes, announcement };
}

export function LiveMapPage() {
  const { useQuery } = useBackend();
  const map = useQuery(fn.dashboard.liveMap, {});
  const { changes, announcement } = useChanges(map);
  const now = useNow();
  const href = useHref();

  return (
    <Page title="Live map" lead="Where everything is right now, as Earmark's sensors report it. This page updates by itself.">
      <div className="visually-hidden" role="status" aria-live="polite">
        {announcement}
      </div>
      {!map ? (
        <Loading what="the live map" />
      ) : (
        <>
          {map.unknownTags.map((u) => (
            <Notice key={u.tag} tone="accent" icon="newItem" title={u.spot != null ? `New item on ${theSpot(map.spots, u.spot)}` : "New unlabeled tag"}>
              <p>
                Earmark sees a tag it doesn't know yet (tag <span className="tag-id">{u.tag}</span>), first seen{" "}
                {formatWhen(u.t, now, map.household.timezone)}. Give it a name so the voice assistant can find it.
              </p>
              <p>
                <Link className="button primary" href={href("/items", { label: u.tag })}>
                  Label this item
                </Link>
              </p>
            </Notice>
          ))}

          <div className="map-layout">
            <section aria-labelledby="map-heading" className="map-panel">
              <h2 id="map-heading" className="visually-hidden">
                Map
              </h2>
              <MapField map={map} />
              <p className="map-caption">
                {map.anchors.length > 0
                  ? "Seen from above. The dot is the person; the triangles are the UWB anchors."
                  : "Seen from above. The listener sits at the bottom, facing the spots. Rings mark distance from their head."}
              </p>
            </section>
            <aside className="map-aside" aria-label="Off the spots and recent changes">
              <WalkingGuidance map={map} now={now} />
              <OffSpot map={map} now={now} />
              <section aria-labelledby="changes-heading">
                <h2 id="changes-heading">Recent changes</h2>
                {changes.length === 0 ? (
                  <p className="quiet">Nothing has changed since you opened this page.</p>
                ) : (
                  <ul className="changes">
                    {changes.map((c) => (
                      <li key={c.id}>
                        <span className="when">{formatAgo(c.t, now)}</span> {c.text}
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            </aside>
          </div>

          <ItemsTable map={map} now={now} />
        </>
      )}
    </Page>
  );
}

function sentence(text: string): string {
  return /[.!?]$/.test(text) ? text : `${text}.`;
}

function stateOf(map: LiveMap, objectId: string): ObjectStateRow | undefined {
  return map.states.find((s) => s.objectId === objectId);
}

/** Text equivalent of the anchors and the person on the map. Only shown when walking guidance is set up. */
function WalkingGuidance({ map, now }: { map: LiveMap; now: number }) {
  const { anchors, wearer } = map;
  if (anchors.length === 0 && !wearer) return null;
  const lost = wearer?.mode === "lost";
  return (
    <section aria-labelledby="uwb-heading">
      <h2 id="uwb-heading">The person and UWB anchors</h2>
      <ul className="uwb-list">
        <li>
          {wearer ? (
            <>
              <StatusText icon={lost ? "alert" : wearer.mode === "tracked" ? "roaming" : "onSpot"} tone={lost ? "bad" : "idle"}>
                The person: {poseWords[wearer.mode].toLowerCase()}
              </StatusText>
              <p className="quiet">
                {lost ? "Showing the last known position. " : ""}
                {poseSourceWords[wearer.source]}, updated {formatAgo(wearer.t, now)}.
              </p>
            </>
          ) : (
            <StatusText icon="pending" tone="idle">
              The person: not being tracked right now
            </StatusText>
          )}
        </li>
        {anchors.map((a) => (
          <li key={a.anchorId}>
            <StatusText icon={a.online ? "live" : "offline"} tone={a.online ? "ok" : "bad"}>
              {anchorWords(a)}
            </StatusText>
            {!a.online && a.lastSeenT != null && <p className="quiet">Last heard {formatAgo(a.lastSeenT, now)}.</p>}
          </li>
        ))}
      </ul>
    </section>
  );
}

function OffSpot({ map, now }: { map: LiveMap; now: number }) {
  const tz = map.household.timezone;
  const off = map.objects.filter((o) => {
    const s = stateOf(map, o.objectId);
    return !s || s.status === "held" || s.status === "missing";
  });
  return (
    <section aria-labelledby="offspot-heading">
      <h2 id="offspot-heading">Not on a spot</h2>
      {off.length === 0 ? (
        <p className="quiet">Every item is on a spot or nearby.</p>
      ) : (
        <ul className="offspot">
          {off.map((o) => {
            const s = stateOf(map, o.objectId);
            return (
              <li key={o.objectId}>
                <p className="offspot-name">{capitalize(o.name)}</p>
                <ObjectStatus status={s ? s.status : "no_reading"} />
                <p className="quiet">
                  {sentence(whereText(map, o, s))}
                  {s?.lastSeenT != null && ` Last seen ${formatWhen(s.lastSeenT, now, tz)} (${formatAgo(s.lastSeenT, now)}).`}
                </p>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

interface RowModel {
  key: string;
  name: ReactNode;
  label?: string;
  status: StatusKey;
  where: string;
  seen: ReactNode;
}

function ItemsTable({ map, now }: { map: LiveMap; now: number }) {
  const tz = map.household.timezone;
  const href = useHref();
  const order: Record<StatusKey, number> = { unlabeled: 0, missing: 1, held: 2, roaming: 3, on_spot: 4, no_reading: 5 };
  const seen = (t: number | null) =>
    t != null ? (
      <>
        {formatWhen(t, now, tz)} <span className="quiet">({formatAgo(t, now)})</span>
      </>
    ) : (
      "Never"
    );
  const rows: RowModel[] = [
    ...map.unknownTags.map((u) => ({
      key: u.tag,
      name: (
        <>
          New item{" "}
          <span className="quiet">
            (tag <span className="tag-id">{u.tag}</span>)
          </span>
        </>
      ),
      label: u.tag,
      status: "unlabeled" as const,
      where: u.spot != null ? capitalize(theSpot(map.spots, u.spot)) : "Not on a spot",
      seen: seen(u.t),
    })),
    ...map.objects
      .map((o) => ({ o, s: stateOf(map, o.objectId) }))
      .sort((a, b) => order[a.s?.status ?? "no_reading"] - order[b.s?.status ?? "no_reading"] || a.o.name.localeCompare(b.o.name))
      .map(({ o, s }) => ({
        key: o.objectId,
        name: capitalize(o.name),
        status: s ? s.status : ("no_reading" as const),
        where: whereText(map, o, s),
        seen: seen(s?.lastSeenT ?? null),
      })),
  ];
  const labelLink = (r: RowModel) => r.label && <Link href={href("/items", { label: r.label })}>Label this item</Link>;

  return (
    <section aria-labelledby="list-heading" className="block">
      <h2 id="list-heading">Every item, as a list</h2>
      <p className="quiet">The same information as the map. Times are in the household's time zone ({tz}).</p>
      <div className="wide-only">
        <TableScroll label="Table of every item">
          <table>
            <thead>
              <tr>
                <th scope="col">Item</th>
                <th scope="col">Status</th>
                <th scope="col">Where</th>
                <th scope="col">Last seen</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.key}>
                  <th scope="row">
                    {r.name}
                    {r.label && <br />}
                    {labelLink(r)}
                  </th>
                  <td>
                    <ObjectStatus status={r.status} />
                  </td>
                  <td>{r.where}</td>
                  <td>{r.seen}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableScroll>
      </div>
      <ul className="narrow-only item-rows">
        {rows.map((r) => (
          <li key={r.key}>
            <p className="item-rows-name">{r.name}</p>
            <ObjectStatus status={r.status} />
            <dl>
              <div>
                <dt>Where</dt>
                <dd>{r.where}</dd>
              </div>
              <div>
                <dt>Last seen</dt>
                <dd>{r.seen}</dd>
              </div>
            </dl>
            {r.label && <p>{labelLink(r)}</p>}
          </li>
        ))}
      </ul>
    </section>
  );
}
