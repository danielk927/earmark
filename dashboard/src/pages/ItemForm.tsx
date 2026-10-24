import { useEffect, useId, useRef, useState, type FormEvent, type ReactNode } from "react";
import type { ObjectFields, SpotRow } from "@contracts/convexFunctions";
import { errorMessage } from "../lib/errors";
import { splitAliases } from "../lib/words";
import { Notice } from "../components/common";

export interface FormValues {
  name: string;
  aliases: string;
  notes: string;
  description: string;
  homeSpot: string;
  tag: string;
  fobId: string;
  isMedication: boolean;
}

export function toFormValues(f: Partial<ObjectFields>): FormValues {
  return {
    name: f.name ?? "",
    aliases: (f.aliases ?? []).join(", "),
    notes: f.notes ?? "",
    description: f.description ?? "",
    homeSpot: f.homeSpot != null ? String(f.homeSpot) : "",
    tag: f.tag ?? "",
    fobId: f.fobId ?? "",
    isMedication: f.isMedication ?? false,
  };
}

export function toFields(v: FormValues): ObjectFields {
  return {
    name: v.name.trim(),
    aliases: splitAliases(v.aliases),
    notes: v.notes.trim(),
    description: v.description.trim(),
    homeSpot: v.homeSpot ? Number(v.homeSpot) : null,
    tag: v.tag.trim() || null,
    fobId: v.fobId.trim() || null,
    isMedication: v.isMedication,
  };
}

/** Only the fields that differ, for objects.update. */
export function changedFields(before: ObjectFields, after: ObjectFields): Partial<ObjectFields> {
  const out: Partial<ObjectFields> = {};
  for (const k of Object.keys(after) as (keyof ObjectFields)[]) {
    if (JSON.stringify(before[k]) !== JSON.stringify(after[k])) (out as Record<string, unknown>)[k] = after[k];
  }
  return out;
}

interface Props {
  heading: string;
  initial: FormValues;
  spots: SpotRow[];
  submitLabel: string;
  onSubmit: (fields: ObjectFields) => Promise<void>;
  onCancel: () => void;
  cancelLabel?: string;
  before?: ReactNode;
  after?: ReactNode;
  focusOnMount?: boolean;
}

export function ItemForm({
  heading,
  initial,
  spots,
  submitLabel,
  onSubmit,
  onCancel,
  cancelLabel = "Cancel",
  before,
  after,
  focusOnMount = true,
}: Props) {
  const id = useId();
  const [v, setV] = useState<FormValues>(initial);
  const [nameError, setNameError] = useState<string | null>(null);
  const [serverError, setServerError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const nameRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (focusOnMount) headingRef.current?.focus();
  }, [focusOnMount]);

  const set = <K extends keyof FormValues>(k: K, value: FormValues[K]) => setV((old) => ({ ...old, [k]: value }));

  async function submit(e: FormEvent) {
    e.preventDefault();
    setServerError(null);
    if (!v.name.trim()) {
      setNameError("Enter a name, for example \"sugar\".");
      nameRef.current?.focus();
      return;
    }
    setNameError(null);
    setSaving(true);
    try {
      await onSubmit(toFields(v));
    } catch (err) {
      setServerError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  const f = (name: string) => `${id}-${name}`;
  return (
    <form className="item-form" onSubmit={submit} noValidate aria-labelledby={f("heading")}>
      <h3 id={f("heading")} ref={headingRef} tabIndex={-1}>
        {heading}
      </h3>
      {before}
      <div className="field">
        <label htmlFor={f("name")}>Name</label>
        <p className="hint" id={f("name-hint")}>
          What the family calls it. The voice assistant uses this name.
        </p>
        <input
          ref={nameRef}
          id={f("name")}
          value={v.name}
          onChange={(e) => set("name", e.target.value)}
          required
          aria-required="true"
          aria-invalid={nameError ? true : undefined}
          aria-describedby={`${f("name-hint")}${nameError ? ` ${f("name-error")}` : ""}`}
          autoComplete="off"
        />
        {nameError && (
          <p className="field-error" id={f("name-error")}>
            {nameError}
          </p>
        )}
      </div>
      <div className="field">
        <label htmlFor={f("aliases")}>Other names</label>
        <p className="hint" id={f("aliases-hint")}>
          Separate with commas, for example: table salt, sea salt.
        </p>
        <input
          id={f("aliases")}
          value={v.aliases}
          onChange={(e) => set("aliases", e.target.value)}
          aria-describedby={f("aliases-hint")}
          autoComplete="off"
        />
      </div>
      <div className="field">
        <label htmlFor={f("description")}>Description</label>
        <p className="hint" id={f("description-hint")}>
          What it looks or feels like. This helps tell look-alikes apart.
        </p>
        <textarea
          id={f("description")}
          rows={2}
          value={v.description}
          onChange={(e) => set("description", e.target.value)}
          aria-describedby={f("description-hint")}
        />
      </div>
      <div className="field">
        <label htmlFor={f("notes")}>Notes</label>
        <p className="hint" id={f("notes-hint")}>
          Anything else worth knowing, such as what it's used for.
        </p>
        <textarea
          id={f("notes")}
          rows={2}
          value={v.notes}
          onChange={(e) => set("notes", e.target.value)}
          aria-describedby={f("notes-hint")}
        />
      </div>
      <div className="field-row">
        <div className="field">
          <label htmlFor={f("home")}>Home spot</label>
          <select id={f("home")} value={v.homeSpot} onChange={(e) => set("homeSpot", e.target.value)}>
            <option value="">No home spot</option>
            {spots.map((s) => (
              <option key={s.spot} value={String(s.spot)}>
                Spot {s.spot}: {s.label}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor={f("tag")}>Spot tag ID</label>
          <p className="hint" id={f("tag-hint")}>
            Filled in for you when you label a new tag.
          </p>
          <input
            id={f("tag")}
            className="tag-id"
            value={v.tag}
            onChange={(e) => set("tag", e.target.value)}
            aria-describedby={f("tag-hint")}
            autoComplete="off"
            spellCheck={false}
          />
        </div>
        <div className="field">
          <label htmlFor={f("fob")}>Bluetooth fob ID</label>
          <p className="hint" id={f("fob-hint")}>
            Only for items that carry a fob, like keys.
          </p>
          <input
            id={f("fob")}
            className="tag-id"
            value={v.fobId}
            onChange={(e) => set("fobId", e.target.value)}
            aria-describedby={f("fob-hint")}
            autoComplete="off"
            spellCheck={false}
          />
        </div>
      </div>
      <div className="field check">
        <input
          id={f("med")}
          type="checkbox"
          checked={v.isMedication}
          onChange={(e) => set("isMedication", e.target.checked)}
          aria-describedby={f("med-hint")}
        />
        <label htmlFor={f("med")}>This is a medication</label>
        <p className="hint" id={f("med-hint")}>
          Lets you set dose times for it on the Medications page.
        </p>
      </div>
      {serverError && (
        <Notice tone="bad" icon="alert" role="alert" title="Not saved.">
          <p>{serverError}</p>
        </Notice>
      )}
      {after}
      <div className="actions">
        <button type="submit" className="button primary" disabled={saving}>
          {saving ? "Saving..." : submitLabel}
        </button>
        <button type="button" className="button" onClick={onCancel}>
          {cancelLabel}
        </button>
      </div>
    </form>
  );
}
