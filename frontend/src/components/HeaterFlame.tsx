// The heater's mood at a glance: a sleeping flame when off, a small flicker while
// it ignites, a lively flame while heating, a cool blue swirl while cooling down.

export function HeaterFlame({ phase, size = 56 }: { phase: string | null; size?: number }) {
  const state =
    phase === "running" ? "burning" : phase === "ignition" || phase === "self_test" ? "igniting" : phase === "cooldown" || phase === "ventilation" ? "cooling" : phase === "fault" ? "fault" : "sleeping";
  return (
    <svg
      className={`heater-flame ${state}`}
      width={size}
      height={size}
      viewBox="0 0 64 64"
      role="img"
      aria-label={{ burning: "heating", igniting: "igniting", cooling: "cooling down", fault: "fault", sleeping: "off" }[state]}
    >
      <defs>
        <radialGradient id="flame-hot" cx="50%" cy="78%" r="70%">
          <stop offset="0%" stopColor="#ffe08a" />
          <stop offset="45%" stopColor="#ff9a3c" />
          <stop offset="100%" stopColor="#e8452a" />
        </radialGradient>
        <radialGradient id="flame-cool" cx="50%" cy="78%" r="70%">
          <stop offset="0%" stopColor="#d9f2ff" />
          <stop offset="100%" stopColor="#5fb2e6" />
        </radialGradient>
      </defs>
      {/* the burner */}
      <rect x="14" y="52" width="36" height="6" rx="3" className="flame-base" />
      {/* outer flame */}
      <path
        className="flame-outer"
        d="M32 6c2 9 12 14 12 28a12 12 0 0 1-24 0c0-7 4-10 6-15 1 4 3 6 5 7 0-7-1-13 1-20z"
      />
      {/* inner flame */}
      <path className="flame-inner" d="M32 26c1 5 6 8 6 15a6 6 0 0 1-12 0c0-4 3-6 4-9 0 2 1 3 2 4 0-4-1-7 0-10z" />
      {/* face: closed eyes when sleeping, open eyes otherwise */}
      {state === "sleeping" ? (
        <>
          <path d="M26 39q2 2 4 0M34 39q2 2 4 0" className="flame-face" />
          <text x="46" y="16" className="flame-zzz">z</text>
          <text x="52" y="9" className="flame-zzz small">z</text>
        </>
      ) : (
        <>
          <circle cx="28" cy="39" r="1.8" className="flame-eye" />
          <circle cx="36" cy="39" r="1.8" className="flame-eye" />
          {state === "fault" ? <path d="M28 46q4 -3 8 0" className="flame-face" /> : <path d="M28 44q4 3 8 0" className="flame-face" />}
        </>
      )}
    </svg>
  );
}
