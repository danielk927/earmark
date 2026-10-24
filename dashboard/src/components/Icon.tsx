/** Simple 24px stroke icons. Always decorative: the text next to them carries the meaning. */
const paths = {
  // Dose and trial status
  taken: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="m7.5 12.5 3 3 6-6.5" />
    </>
  ),
  late: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5.5l3.5 2" />
    </>
  ),
  missed: (
    <>
      <path d="M8.2 3h7.6L21 8.2v7.6L15.8 21H8.2L3 15.8V8.2z" />
      <path d="m9 9 6 6m0-6-6 6" />
    </>
  ),
  pending: <circle cx="12" cy="12" r="9" strokeDasharray="3.2 2.6" />,
  // Object status
  onSpot: (
    <>
      <circle cx="12" cy="12" r="9" />
      <circle cx="12" cy="12" r="4.5" fill="currentColor" />
    </>
  ),
  held: (
    <>
      <path d="M12 20V6m0 0-5 5m5-5 5 5" />
      <path d="M5 3h14" />
    </>
  ),
  missing: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.7.3-1 .9-1 1.6v.6" />
      <circle cx="12" cy="17" r=".6" fill="currentColor" />
    </>
  ),
  roaming: (
    <>
      <circle cx="12" cy="15" r="1.6" fill="currentColor" />
      <path d="M8.5 11.5a5 5 0 0 1 7 0M5.5 8.5a9.2 9.2 0 0 1 13 0" />
    </>
  ),
  newItem: (
    <>
      <rect x="3.5" y="3.5" width="17" height="17" rx="4" strokeDasharray="3 2.4" />
      <path d="M12 8v8m-4-4h8" />
    </>
  ),
  // Events
  placed: (
    <>
      <path d="M12 4v14m0 0-5-5m5 5 5-5" />
      <path d="M5 21h14" />
    </>
  ),
  dot: <circle cx="12" cy="12" r="3.5" fill="currentColor" />,
  // UI
  camera: (
    <>
      <path d="M4 8h3l1.6-2.5h6.8L17 8h3v11H4z" />
      <circle cx="12" cy="13.2" r="3.4" />
    </>
  ),
  image: (
    <>
      <rect x="3.5" y="4.5" width="17" height="15" rx="2" />
      <circle cx="9" cy="10" r="1.8" />
      <path d="m4 18 5-5 4 4 2.5-2.5L20 19" />
    </>
  ),
  shield: (
    <>
      <path d="M12 3 5 6v5.5c0 4.3 3 7.7 7 9.5 4-1.8 7-5.2 7-9.5V6z" />
      <path d="m9 12 2.2 2.2L15.5 10" />
    </>
  ),
  info: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 11v6" />
      <circle cx="12" cy="7.8" r=".6" fill="currentColor" />
    </>
  ),
  alert: (
    <>
      <path d="M12 3.5 21.5 20h-19z" />
      <path d="M12 10v4.5" />
      <circle cx="12" cy="17.2" r=".6" fill="currentColor" />
    </>
  ),
  plus: <path d="M12 5v14M5 12h14" />,
  edit: <path d="m4 20 1-4.5L15.5 5a2.1 2.1 0 0 1 3 3L8 18.5zM13.5 7l3 3" />,
  trash: <path d="M4 7h16M9.5 7V4.5h5V7M6.5 7l1 13h9l1-13M10 11v5.5m4-5.5v5.5" />,
  live: (
    <>
      <circle cx="12" cy="12" r="3.5" fill="currentColor" />
      <circle cx="12" cy="12" r="8" />
    </>
  ),
  offline: (
    <>
      <circle cx="12" cy="12" r="8" />
      <path d="m8 8 8 8" />
    </>
  ),
  flask: (
    <>
      <path d="M9.5 3.5h5M10.5 3.5v6L5 19a1.3 1.3 0 0 0 1.1 2h11.8A1.3 1.3 0 0 0 19 19l-5.5-9.5v-6" />
      <path d="M7.5 15h9" />
    </>
  ),
} as const;

export type IconName = keyof typeof paths;

export function Icon({ name, size = 22, className }: { name: IconName; size?: number; className?: string }) {
  return (
    <svg
      className={className ? `icon ${className}` : "icon"}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {paths[name]}
    </svg>
  );
}
