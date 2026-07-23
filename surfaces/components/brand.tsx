/**
 * The Cowrie mark.
 *
 * A cowrie shell: the money of West African trade for centuries, and the reason
 * the product is called what it is. Drawn rather than imported so it stays
 * crisp at every size and inherits currentColor.
 */

export function CowrieMark({ className = "h-6 w-6" }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      className={className}
      aria-hidden="true"
      focusable="false"
    >
      {/* shell body */}
      <path
        d="M12 1.6c3.1 0 5.4 2.9 5.4 7.2v6.4c0 4.3-2.3 7.2-5.4 7.2s-5.4-2.9-5.4-7.2V8.8C6.6 4.5 8.9 1.6 12 1.6Z"
        fill="currentColor"
      />
      {/* the aperture */}
      <path
        d="M12 5.6c.9 0 1.5 1 1.5 2.6v7.6c0 1.6-.6 2.6-1.5 2.6s-1.5-1-1.5-2.6V8.2c0-1.6.6-2.6 1.5-2.6Z"
        fill="#FFFFFF"
        fillOpacity="0.95"
      />
      {/* teeth */}
      <g stroke="currentColor" strokeWidth="0.9" strokeLinecap="round" opacity="0.55">
        <path d="M10.9 8.4h2.2M10.9 10.2h2.2M10.9 12h2.2M10.9 13.8h2.2M10.9 15.6h2.2" />
      </g>
    </svg>
  );
}

/** Mark in a rounded violet tile, as used on the CowriePay login screen. */
export function CowrieBadge({ className = "" }: { className?: string }) {
  return (
    <span
      className={`inline-flex h-12 w-12 items-center justify-center rounded-2xl bg-violet-600 text-white shadow-fab ${className}`}
    >
      <CowrieMark className="h-7 w-7" />
    </span>
  );
}

/** Mark plus wordmark, for application headers. */
export function CowrieWordmark({
  label,
  className = "",
}: {
  label: string;
  className?: string;
}) {
  return (
    <span className={`inline-flex items-center gap-2.5 ${className}`}>
      <CowrieMark className="h-6 w-6 text-violet-600" />
      <span className="text-[15px] font-semibold tracking-tight text-heading">{label}</span>
    </span>
  );
}

/**
 * Country flags, drawn as simple bands.
 *
 * An emoji flag would be simpler, but they do not render on Windows Chrome at
 * all, and SRS 2.4 lists Chromium as a supported target. These render
 * everywhere.
 */
export function Flag({
  country,
  className = "h-5 w-5",
}: {
  country: "NG" | "KE" | "GH" | "TZ" | "US";
  className?: string;
}) {
  const label = {
    NG: "Nigeria",
    KE: "Kenya",
    GH: "Ghana",
    TZ: "Tanzania",
    US: "United States",
  }[country];

  return (
    <span
      className={`relative inline-block overflow-hidden rounded-full ring-1 ring-black/5 ${className}`}
      role="img"
      aria-label={label}
    >
      <svg viewBox="0 0 24 24" className="h-full w-full">
        {country === "NG" && (
          <g>
            <rect width="24" height="24" fill="#FFFFFF" />
            <rect width="8" height="24" fill="#008751" />
            <rect x="16" width="8" height="24" fill="#008751" />
          </g>
        )}
        {country === "KE" && (
          <g>
            <rect width="24" height="24" fill="#FFFFFF" />
            <rect width="24" height="7" fill="#000000" />
            <rect y="7" width="24" height="2" fill="#FFFFFF" />
            <rect y="9" width="24" height="6" fill="#BB0000" />
            <rect y="15" width="24" height="2" fill="#FFFFFF" />
            <rect y="17" width="24" height="7" fill="#006600" />
            <ellipse cx="12" cy="12" rx="2.6" ry="6" fill="#BB0000" stroke="#FFFFFF" strokeWidth="0.8" />
          </g>
        )}
        {country === "GH" && (
          <g>
            <rect width="24" height="8" fill="#CE1126" />
            <rect y="8" width="24" height="8" fill="#FCD116" />
            <rect y="16" width="24" height="8" fill="#006B3F" />
            <path d="m12 9.5 1.2 3.6h3.8l-3.1 2.2 1.2 3.6-3.1-2.2-3.1 2.2 1.2-3.6-3.1-2.2h3.8Z" fill="#000" />
          </g>
        )}
        {country === "TZ" && (
          <g>
            <rect width="24" height="24" fill="#1EB53A" />
            <path d="M0 24 24 0v24Z" fill="#00A3DD" />
            <path d="M0 19 19 0h5v5L5 24H0Z" fill="#FCD116" />
            <path d="M0 20.5 20.5 0h1.5L1.5 22H0Z" fill="#000" />
          </g>
        )}
        {country === "US" && (
          <g>
            <rect width="24" height="24" fill="#FFFFFF" />
            <g fill="#B22234">
              <rect width="24" height="2" />
              <rect y="4" width="24" height="2" />
              <rect y="8" width="24" height="2" />
              <rect y="12" width="24" height="2" />
              <rect y="16" width="24" height="2" />
              <rect y="20" width="24" height="2" />
            </g>
            <rect width="11" height="12" fill="#3C3B6E" />
          </g>
        )}
      </svg>
    </span>
  );
}
