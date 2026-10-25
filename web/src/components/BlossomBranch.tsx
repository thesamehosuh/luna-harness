/** Quiet botanical detail drawn for Luna; colors follow the selected dashboard palette. */
export function BlossomBranch({ className }: { className?: string }) {
  const flowers = [
    { x: 304, y: 26, size: 1 }, { x: 252, y: 61, size: 0.9 },
    { x: 187, y: 72, size: 0.75 }, { x: 271, y: 119, size: 0.65 },
    { x: 137, y: 116, size: 0.7 },
  ];
  return (
    <svg viewBox="0 0 360 180" fill="none" aria-hidden="true" className={className}>
      <g stroke="var(--color-ring)" strokeWidth="1.3" strokeLinecap="round" opacity="0.55">
        <path d="M370 0C306 12 302 67 225 89C171 104 152 129 119 146" />
        <path d="M289 54C285 34 266 27 250 29M255 78C233 52 211 54 180 46M225 89C250 94 261 116 275 143M166 117C164 89 150 84 136 72" />
      </g>
      {flowers.map(({ x, y, size }, index) => (
        <g key={index} transform={`translate(${x} ${y}) scale(${size})`}>
          {[0, 72, 144, 216, 288].map((angle) => (
            <path key={angle} d="M0 2C-12-3-14-15-7-20C-3-23-1-18 0-16C1-18 4-23 8-19C14-12 10-2 0 2Z" transform={`rotate(${angle})`} fill={index % 2 ? "var(--color-ring)" : "var(--color-primary)"} opacity="0.8" />
          ))}
          <circle r="3" fill="var(--color-warning)" />
        </g>
      ))}
      <g fill="var(--color-primary)" opacity="0.5">
        <path d="M78 49C88 42 91 48 82 61C74 59 70 54 78 49Z" />
        <path d="M213 148C223 141 226 148 219 159C210 158 206 153 213 148Z" />
        <path d="M109 93C116 91 119 98 112 104C105 102 103 97 109 93Z" />
      </g>
    </svg>
  );
}
