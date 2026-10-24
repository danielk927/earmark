/**
 * Photo-assisted labeling: one photo from the family member's own device, shrunk to a JPEG here,
 * uploaded to Convex storage, described by Claude, then deleted by the server.
 * The suggestion is only a starting point: nothing is saved until the person confirms the form.
 */
import { useEffect, useId, useRef, useState } from "react";
import { fn, type ObjectFields, type ObjectRow, type PhotoSuggestion, type SpotRow } from "@contracts/convexFunctions";
import { useBackend } from "../data/backend";
import { photoErrorMessage } from "../lib/errors";
import { downscalePhoto, PhotoError } from "../lib/photo";
import { capitalize } from "../lib/words";
import { Notice } from "../components/common";
import { Icon } from "../components/Icon";
import { changedFields, ItemForm, toFormValues } from "./ItemForm";

type Step = "shrinking" | "uploading" | "suggesting";
type State =
  | { kind: "idle" }
  | { kind: "working"; step: Step }
  | { kind: "suggested"; suggestion: PhotoSuggestion }
  | { kind: "error"; message: string };

const stepText: Record<Step, string> = {
  shrinking: "Shrinking the photo on this device...",
  uploading: "Uploading the photo...",
  suggesting: "Asking the model for a name and description...",
};

interface Props {
  objects: ObjectRow[];
  spots: SpotRow[];
  /** Fields for a new item, for example the tag and spot of an unlabeled tag. */
  preset?: Partial<ObjectFields>;
  onDone: (message: string) => void;
  onCancel: () => void;
  onFillByHand: () => void;
}

export function PhotoLabel({ objects, spots, preset, onDone, onCancel, onFillByHand }: Props) {
  const id = useId();
  const { useMutation, useAction, uploadPhoto } = useBackend();
  const generateUploadUrl = useMutation(fn.labeling.generateUploadUrl);
  const suggestFromPhoto = useAction(fn.labeling.suggestFromPhoto);
  const create = useMutation(fn.objects.create);
  const update = useMutation(fn.objects.update);

  const [state, setState] = useState<State>({ kind: "idle" });
  const [target, setTarget] = useState<string>(""); // "" = new item, else objectId
  const [preview, setPreview] = useState<string | null>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const errorRef = useRef<HTMLDivElement>(null);

  useEffect(() => headingRef.current?.focus(), []);
  useEffect(() => () => void (preview && URL.revokeObjectURL(preview)), [preview]);
  useEffect(() => {
    if (state.kind === "error") errorRef.current?.focus();
  }, [state.kind]);

  async function handleFile(file: File | undefined) {
    if (!file) return;
    try {
      setState({ kind: "working", step: "shrinking" });
      const jpeg = await downscalePhoto(file);
      setPreview(URL.createObjectURL(jpeg));
      setState({ kind: "working", step: "uploading" });
      const url = await generateUploadUrl({});
      const storageId = await uploadPhoto(url, jpeg);
      setState({ kind: "working", step: "suggesting" });
      const suggestion = await suggestFromPhoto({ storageId });
      setState({ kind: "suggested", suggestion });
    } catch (err) {
      setState({ kind: "error", message: err instanceof PhotoError ? err.message : photoErrorMessage(err) });
    }
  }

  const existing = objects.find((o) => o.objectId === target);
  const working = state.kind === "working";

  if (state.kind === "suggested") {
    const sg = state.suggestion;
    const base: Partial<ObjectFields> = existing ?? preset ?? {};
    const initial = toFormValues({ ...base, name: sg.name, aliases: sg.aliases, description: sg.description });
    return (
      <ItemForm
        heading={existing ? `Check the suggestion for ${capitalize(existing.name)}` : "Check the suggestion"}
        initial={initial}
        spots={spots}
        submitLabel={existing ? `Update ${capitalize(existing.name)}` : "Save as a new item"}
        cancelLabel="Discard suggestion"
        onCancel={onCancel}
        onSubmit={async (fields) => {
          if (existing) {
            await update({ objectId: existing.objectId, ...changedFields(existing, fields) });
            onDone(`Updated ${fields.name}. The voice assistant will use the new details within a few seconds.`);
          } else {
            await create(fields);
            onDone(`Saved ${fields.name}. The voice assistant will know it within a few seconds.`);
          }
        }}
        before={
          <div className="suggestion-meta">
            {preview && <img src={preview} alt="The item you uploaded" className="photo-preview" />}
            <div>
              {sg.photoDeleted ? (
                <Notice tone="ok" icon="shield" title="Photo deleted.">
                  <p>
                    Earmark deleted the photo as soon as the suggestion came back. Only the text below is kept, and only
                    if you save it.
                  </p>
                </Notice>
              ) : (
                <Notice tone="warn" icon="alert" title="The server did not confirm the photo was deleted.">
                  <p>Tell whoever runs this Earmark server. The text below is not saved unless you save it.</p>
                </Notice>
              )}
              <p className="quiet">
                Suggested by {sg.model} in {(sg.latencyMs / 1000).toFixed(1)} s. Check every field: the model can be
                wrong, and it cannot tell identical containers apart.
              </p>
            </div>
          </div>
        }
      />
    );
  }

  return (
    <section className="photo-label" aria-labelledby={`${id}-heading`}>
      <h3 id={`${id}-heading`} ref={headingRef} tabIndex={-1}>
        Start from a photo
      </h3>
      <p>
        Take or choose one photo of the item. Earmark sends it to an AI model, which suggests a name, other names, and
        a description. The photo is deleted as soon as the suggestion comes back, and nothing is saved until you
        confirm.
      </p>
      <p className="quiet">
        Earmark has no cameras in the home. This one photo comes from your own phone or computer.
      </p>

      <div className="field">
        <label htmlFor={`${id}-target`}>Use the suggestion for</label>
        <select id={`${id}-target`} value={target} onChange={(e) => setTarget(e.target.value)} disabled={working}>
          <option value="">A new item</option>
          {objects.map((o) => (
            <option key={o.objectId} value={o.objectId}>
              {capitalize(o.name)} (update)
            </option>
          ))}
        </select>
      </div>

      <div className="file-buttons">
        <label className={`button primary file-button${working ? " is-disabled" : ""}`}>
          <Icon name="camera" />
          <span>Take a photo</span>
          <input
            type="file"
            accept="image/*"
            capture="environment"
            className="visually-hidden"
            disabled={working}
            onChange={(e) => {
              void handleFile(e.target.files?.[0]);
              e.target.value = "";
            }}
          />
        </label>
        <label className={`button file-button${working ? " is-disabled" : ""}`}>
          <Icon name="image" />
          <span>Choose a photo</span>
          <input
            type="file"
            accept="image/*"
            className="visually-hidden"
            disabled={working}
            onChange={(e) => {
              void handleFile(e.target.files?.[0]);
              e.target.value = "";
            }}
          />
        </label>
      </div>

      <div role="status" className="photo-progress">
        {state.kind === "working" && <p>{stepText[state.step]}</p>}
      </div>

      {state.kind === "error" && (
        <div ref={errorRef} tabIndex={-1}>
          <Notice tone="bad" icon="alert" role="alert" title="No suggestion.">
            <p>{state.message}</p>
            <p>Nothing was saved.</p>
          </Notice>
        </div>
      )}

      <div className="actions">
        <button type="button" className="button" onClick={onFillByHand} disabled={working}>
          Fill in by hand instead
        </button>
        <button type="button" className="button" onClick={onCancel} disabled={working}>
          Cancel
        </button>
      </div>
    </section>
  );
}
