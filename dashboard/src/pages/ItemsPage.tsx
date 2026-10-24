import { useEffect, useRef, useState } from "react";
import { useSearch } from "wouter";
import { fn, type LiveMap, type ObjectFields, type ObjectRow, type UnknownTagRow } from "@contracts/convexFunctions";
import { useBackend } from "../data/backend";
import { errorMessage } from "../lib/errors";
import { formatWhen } from "../lib/time";
import { capitalize, spotLabel, theSpot } from "../lib/words";
import { Loading, Notice, Page, useNow } from "../components/common";
import { Icon } from "../components/Icon";
import { changedFields, ItemForm, toFormValues } from "./ItemForm";
import { PhotoLabel } from "./PhotoLabel";

type Adding = { how: "photo" | "hand"; preset?: Partial<ObjectFields>; forTag?: string } | null;

export function ItemsPage() {
  const { useQuery } = useBackend();
  const map = useQuery(fn.dashboard.liveMap, {});
  const search = useSearch();
  const labelTag = new URLSearchParams(search).get("label");

  return (
    <Page
      title="Items"
      lead="The names, other names, and notes Earmark's voice assistant uses. Changes reach it within a few seconds."
    >
      {!map ? <Loading what="items" /> : <ItemsBody map={map} labelTag={labelTag} />}
    </Page>
  );
}

function presetFor(u: UnknownTagRow): Partial<ObjectFields> {
  return { tag: u.tag, homeSpot: u.spot };
}

function ItemsBody({ map, labelTag }: { map: LiveMap; labelTag: string | null }) {
  const now = useNow();
  const tz = map.household.timezone;
  const create = useBackend().useMutation(fn.objects.create);
  const [adding, setAdding] = useState<Adding>(() => {
    const u = map.unknownTags.find((x) => x.tag === labelTag);
    return u ? { how: "hand", preset: presetFor(u), forTag: u.tag } : null;
  });
  const [message, setMessage] = useState<string | null>(null);
  const addHeading = useRef<HTMLHeadingElement>(null);
  const messageRef = useRef<HTMLDivElement>(null);
  const objects = [...map.objects].sort((a, b) => a.name.localeCompare(b.name));

  useEffect(() => {
    if (message) messageRef.current?.focus();
  }, [message]);

  const done = (text: string) => {
    setAdding(null);
    setMessage(text);
  };
  const close = () => {
    setAdding(null);
    addHeading.current?.focus();
  };
  const forTagText = (tag: string | undefined) => {
    const u = map.unknownTags.find((x) => x.tag === tag);
    return u?.spot != null ? ` for the new item on ${theSpot(map.spots, u.spot)}` : "";
  };

  return (
    <>
      <div ref={messageRef} tabIndex={-1} className="message-slot">
        <div role="status">
          {message && (
            <Notice tone="ok" icon="taken" title={message}>
              <p>
                <button type="button" className="link-button" onClick={() => setMessage(null)}>
                  Dismiss
                </button>
              </p>
            </Notice>
          )}
        </div>
      </div>

      {map.unknownTags.length > 0 && (
        <section aria-labelledby="new-tags-heading" className="block">
          <h2 id="new-tags-heading">New tags waiting for a name</h2>
          <ul className="new-tags">
            {map.unknownTags.map((u) => (
              <li key={u.tag}>
                <p>
                  <strong>{u.spot != null ? capitalize(theSpot(map.spots, u.spot)) : "Not on a spot"}</strong>: tag{" "}
                  <span className="tag-id">{u.tag}</span>, first seen {formatWhen(u.t, now, tz)}.
                </p>
                <div className="actions">
                  <button
                    type="button"
                    className="button primary"
                    onClick={() => setAdding({ how: "photo", preset: presetFor(u), forTag: u.tag })}
                  >
                    <Icon name="camera" /> Label from a photo
                  </button>
                  <button
                    type="button"
                    className="button"
                    onClick={() => setAdding({ how: "hand", preset: presetFor(u), forTag: u.tag })}
                  >
                    <Icon name="edit" /> Label by hand
                  </button>
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section aria-labelledby="add-heading" className="block add-block">
        <h2 id="add-heading" ref={addHeading} tabIndex={-1}>
          Add an item{adding?.forTag ? forTagText(adding.forTag) : ""}
        </h2>
        {!adding && (
          <div className="actions">
            <button type="button" className="button primary" onClick={() => setAdding({ how: "photo" })}>
              <Icon name="camera" /> Start from a photo
            </button>
            <button type="button" className="button" onClick={() => setAdding({ how: "hand" })}>
              <Icon name="plus" /> Add by hand
            </button>
          </div>
        )}
        {adding?.how === "photo" && (
          <PhotoLabel
            key={adding.forTag ?? "new"}
            objects={adding.forTag ? [] : objects}
            spots={map.spots}
            preset={adding.preset}
            onDone={done}
            onCancel={close}
            onFillByHand={() => setAdding({ ...adding, how: "hand" })}
          />
        )}
        {adding?.how === "hand" && (
          <ItemForm
            key={adding.forTag ?? "new"}
            heading="New item"
            initial={toFormValues(adding.preset ?? {})}
            spots={map.spots}
            submitLabel="Save item"
            onCancel={close}
            onSubmit={async (fields) => {
              await create(fields);
              done(`Saved ${fields.name}. The voice assistant will know it within a few seconds.`);
            }}
          />
        )}
      </section>

      <section aria-labelledby="list-heading" className="block">
        <h2 id="list-heading" tabIndex={-1}>
          Your items ({objects.length})
        </h2>
        {objects.length === 0 ? (
          <p>No items yet. Add one above, or put a tagged item on a spot and label it here.</p>
        ) : (
          <ul className="item-list">
            {objects.map((o) => (
              <ItemEntry key={o.objectId} item={o} map={map} onMessage={setMessage} />
            ))}
          </ul>
        )}
      </section>
    </>
  );
}

function ItemEntry({ item, map, onMessage }: { item: ObjectRow; map: LiveMap; onMessage: (m: string) => void }) {
  const { useMutation } = useBackend();
  const update = useMutation(fn.objects.update);
  const remove = useMutation(fn.objects.remove);
  const [mode, setMode] = useState<"view" | "edit" | "confirm-delete">("view");
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);
  const editButton = useRef<HTMLButtonElement>(null);
  const confirmRef = useRef<HTMLDivElement>(null);
  const name = capitalize(item.name);

  useEffect(() => {
    if (mode === "confirm-delete") confirmRef.current?.focus();
  }, [mode]);

  const backToView = () => {
    setMode("view");
    requestAnimationFrame(() => editButton.current?.focus());
  };

  if (mode === "edit") {
    return (
      <li className="item editing">
        <ItemForm
          heading={`Edit ${name}`}
          initial={toFormValues(item)}
          spots={map.spots}
          submitLabel="Save changes"
          onCancel={backToView}
          onSubmit={async (fields) => {
            const patch = changedFields(item, fields);
            if (Object.keys(patch).length === 0) {
              backToView();
              return;
            }
            await update({ objectId: item.objectId, ...patch });
            onMessage(`Saved changes to ${fields.name}. The voice assistant will use them within a few seconds.`);
            backToView();
          }}
          after={
            <div className="danger-zone">
              <button type="button" className="button danger" onClick={() => setMode("confirm-delete")}>
                <Icon name="trash" /> Delete {name}
              </button>
            </div>
          }
        />
      </li>
    );
  }

  return (
    <li className="item">
      <div className="item-head">
        <h3>{name}</h3>
        {item.isMedication && <span className="pill">Medication</span>}
      </div>
      <dl className="facts">
        <div>
          <dt>Other names</dt>
          <dd>{item.aliases.length ? item.aliases.join(", ") : "None"}</dd>
        </div>
        <div>
          <dt>Home spot</dt>
          <dd>{item.homeSpot != null ? capitalize(spotLabel(map.spots, item.homeSpot) ?? "") : "None"}</dd>
        </div>
        {item.description && (
          <div className="wide">
            <dt>Description</dt>
            <dd>{item.description}</dd>
          </div>
        )}
        {item.notes && (
          <div className="wide">
            <dt>Notes</dt>
            <dd>{item.notes}</dd>
          </div>
        )}
        {item.fobId && (
          <div>
            <dt>Bluetooth fob</dt>
            <dd className="tag-id">{item.fobId}</dd>
          </div>
        )}
        {item.tag && (
          <div>
            <dt>Spot tag</dt>
            <dd className="tag-id">{item.tag}</dd>
          </div>
        )}
      </dl>
      {mode === "confirm-delete" ? (
        <div className="confirm" ref={confirmRef} tabIndex={-1} role="group" aria-labelledby={`del-${item.objectId}`}>
          <p id={`del-${item.objectId}`} className="confirm-title">
            Delete {name}?
          </p>
          <p>Earmark will stop recognizing it, and the voice assistant won't be able to find it.</p>
          {deleteError && (
            <Notice tone="bad" icon="alert" role="alert" title="Not deleted.">
              <p>{deleteError}</p>
            </Notice>
          )}
          <div className="actions">
            <button
              type="button"
              className="button danger"
              disabled={deleting}
              onClick={async () => {
                setDeleting(true);
                setDeleteError(null);
                try {
                  await remove({ objectId: item.objectId });
                  onMessage(`Deleted ${item.name}.`);
                } catch (err) {
                  setDeleteError(errorMessage(err));
                  setDeleting(false);
                }
              }}
            >
              {deleting ? "Deleting..." : `Yes, delete ${name}`}
            </button>
            <button type="button" className="button" onClick={backToView} disabled={deleting}>
              Keep {name}
            </button>
          </div>
        </div>
      ) : (
        <div className="actions">
          <button ref={editButton} type="button" className="button" onClick={() => setMode("edit")}>
            <Icon name="edit" /> Edit {name}
          </button>
        </div>
      )}
    </li>
  );
}
