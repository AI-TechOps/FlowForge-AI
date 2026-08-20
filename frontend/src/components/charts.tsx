/**
 * Charts, hand-rolled in SVG (D21 decision 6, widened).
 *
 * The decision said "no charting dependency" and justified it on one bar chart.
 * The dashboard now carries an area chart, a donut and sparklines, and the
 * reasoning survives the extra scope: these are ~250 lines of SVG against a
 * ~90 kB dependency, they inherit the theme through CSS custom properties for
 * free (every charting library needs a theme adapter), and nothing here is
 * doing statistics — it is drawing shapes from numbers the API already
 * computed.
 *
 * **Every series is real.** These take data derived from `/api/runs`,
 * `/api/audit` and `/api/tickets`. Nothing is padded, interpolated or invented
 * to make a curve look better; an empty range renders as an empty state,
 * because a chart that draws something when it has nothing is the most
 * expensive kind of lie in a product that exists to be trusted.
 */

import { useId, useMemo, useState } from "react";

/* ====================================================================== */
/* Sparkline — a metric card's own history, no axes                        */
/* ====================================================================== */

export function Sparkline({
  values,
  tone = "accent",
  height = 30,
  className,
}: {
  values: number[];
  tone?: "accent" | "ok" | "warn" | "err";
  height?: number;
  className?: string;
}) {
  const id = useId();
  // A series that is almost entirely zeros draws a flat line with one spike,
  // which looks like a rendering fault rather than a fact. Below three
  // non-zero buckets there is nothing a shape can say that the number above
  // it has not already said.
  if (values.length < 2 || values.filter((v) => v > 0).length < 3) return null;

  const width = 100;
  const max = Math.max(...values);
  const min = Math.min(...values);
  // A flat series must not divide by zero, and should sit mid-height rather
  // than pinned to the floor — "steady" is different from "nothing".
  const span = max - min || 1;
  const step = width / (values.length - 1);

  const points = values.map((v, i) => [i * step, height - ((v - min) / span) * (height - 4) - 2]);
  const line = points.map(([x, y], i) => `${i === 0 ? "M" : "L"}${x.toFixed(2)},${y!.toFixed(2)}`).join(" ");
  const area = `${line} L${width},${height} L0,${height} Z`;
  const stroke = `var(--${tone === "accent" ? "accent" : tone})`;

  return (
    <svg
      className={className}
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      width="100%"
      height={height}
      aria-hidden="true"
      style={{ display: "block", overflow: "visible" }}
    >
      <defs>
        <linearGradient id={`spark-${id}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={stroke} stopOpacity="0.28" />
          <stop offset="100%" stopColor={stroke} stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={area} fill={`url(#spark-${id})`} />
      <path
        d={line}
        fill="none"
        stroke={stroke}
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
}

/* ====================================================================== */
/* Area chart — stacked-free, multi-series, with a hover readout           */
/* ====================================================================== */

export interface Series {
  key: string;
  label: string;
  color: string;
  values: number[];
}

export function AreaChart({
  series,
  labels,
  height = 220,
  yTicks = 4,
}: {
  series: Series[];
  labels: string[];
  height?: number;
  yTicks?: number;
}) {
  const id = useId();
  const [hover, setHover] = useState<number | null>(null);

  const W = 800;
  const H = height;
  const padL = 38;
  const padB = 26;
  const padT = 12;
  const padR = 8;
  const plotW = W - padL - padR;
  const plotH = H - padT - padB;

  const peak = Math.max(1, ...series.flatMap((s) => s.values));
  // Round the axis up to something a human would choose, so gridlines read as
  // 0/10/20/30 rather than 0/7/14/21.
  const niceMax = useMemo(() => {
    const raw = peak * 1.1;
    const mag = 10 ** Math.floor(Math.log10(raw));
    return Math.ceil(raw / mag) * mag || 1;
  }, [peak]);

  const n = labels.length;
  const x = (i: number) => padL + (n === 1 ? plotW / 2 : (i / (n - 1)) * plotW);
  const y = (v: number) => padT + plotH - (v / niceMax) * plotH;

  // Integer ticks, deduplicated. With a max of 3 and 4 divisions the raw
  // values are 0/0.75/1.5/2.25/3, which round to 0/1/2/2/3 — a duplicated
  // gridline label that makes the axis look broken.
  const ticks = Array.from(
    new Set(
      Array.from({ length: yTicks + 1 }, (_, i) => Math.round((niceMax / yTicks) * i)),
    ),
  );
  // At most ~8 x labels, or they collide.
  const labelEvery = Math.max(1, Math.ceil(n / 8));

  return (
    <div style={{ position: "relative" }}>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        width="100%"
        height={H}
        role="img"
        aria-label={`${series.map((s) => s.label).join(", ")} over time`}
        onMouseLeave={() => setHover(null)}
        style={{ display: "block", overflow: "visible" }}
      >
        <defs>
          {series.map((s) => (
            <linearGradient key={s.key} id={`area-${id}-${s.key}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={s.color} stopOpacity="0.30" />
              <stop offset="70%" stopColor={s.color} stopOpacity="0.04" />
              <stop offset="100%" stopColor={s.color} stopOpacity="0" />
            </linearGradient>
          ))}
        </defs>

        {ticks.map((t, i) => (
          <g key={i}>
            <line x1={padL} y1={y(t)} x2={W - padR} y2={y(t)} stroke="var(--grid)" strokeWidth="1" />
            <text
              x={padL - 8}
              y={y(t) + 3.5}
              textAnchor="end"
              fontSize="10"
              fill="var(--text-faint)"
              fontFamily="var(--font-mono)"
            >
              {Math.round(t)}
            </text>
          </g>
        ))}

        {labels.map((label, i) =>
          i % labelEvery === 0 ? (
            <text
              key={i}
              x={x(i)}
              y={H - 8}
              textAnchor="middle"
              fontSize="10"
              fill="var(--text-faint)"
            >
              {label}
            </text>
          ) : null,
        )}

        {series.map((s) => {
          const line = s.values
            .map((v, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(2)},${y(v).toFixed(2)}`)
            .join(" ");
          const area = `${line} L${x(n - 1).toFixed(2)},${padT + plotH} L${x(0).toFixed(2)},${padT + plotH} Z`;
          return (
            <g key={s.key}>
              <path d={area} fill={`url(#area-${id}-${s.key})`} />
              <path
                d={line}
                fill="none"
                stroke={s.color}
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </g>
          );
        })}

        {hover !== null && (
          <g>
            <line
              x1={x(hover)}
              y1={padT}
              x2={x(hover)}
              y2={padT + plotH}
              stroke="var(--border-strong)"
              strokeWidth="1"
              strokeDasharray="3 3"
            />
            {series.map((s) => (
              <circle
                key={s.key}
                cx={x(hover)}
                cy={y(s.values[hover] ?? 0)}
                r="3.5"
                fill="var(--panel)"
                stroke={s.color}
                strokeWidth="2"
              />
            ))}
          </g>
        )}

        {/* Invisible hit strips: one per bucket, so the readout tracks the
            nearest point rather than the pixel under the cursor. */}
        {labels.map((_, i) => (
          <rect
            key={i}
            x={x(i) - plotW / Math.max(1, n - 1) / 2}
            y={padT}
            width={plotW / Math.max(1, n - 1)}
            height={plotH}
            fill="transparent"
            onMouseEnter={() => setHover(i)}
          />
        ))}
      </svg>

      {hover !== null && (
        <div
          className="chart-tip"
          style={{
            left: `${(x(hover) / W) * 100}%`,
            transform: `translateX(${hover > n / 2 ? "-105%" : "5%"})`,
          }}
        >
          <div className="chart-tip__date">{labels[hover]}</div>
          {series.map((s) => (
            <div key={s.key} className="chart-tip__row">
              <span className="chart-tip__swatch" style={{ background: s.color }} />
              <span className="chart-tip__label">{s.label}</span>
              <span className="chart-tip__value">{s.values[hover]}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* ====================================================================== */
/* Donut — distribution, with the total in the middle                      */
/* ====================================================================== */

export interface Slice {
  label: string;
  value: number;
  color: string;
}

export function Donut({
  slices,
  size = 168,
  thickness = 22,
  centerLabel,
}: {
  slices: Slice[];
  size?: number;
  thickness?: number;
  centerLabel?: string;
}) {
  const [active, setActive] = useState<number | null>(null);
  const total = slices.reduce((sum, s) => sum + s.value, 0);
  const r = (size - thickness) / 2;
  const c = size / 2;
  const circumference = 2 * Math.PI * r;

  if (total === 0) {
    return (
      <div className="donut donut--empty" style={{ width: size, height: size }}>
        <span className="faint" style={{ fontSize: "var(--fs-xs)" }}>
          No data
        </span>
      </div>
    );
  }

  let offset = 0;
  const arcs = slices
    .filter((s) => s.value > 0)
    .map((s, i) => {
      const fraction = s.value / total;
      // 1px gap between arcs so adjacent slices of similar colour stay legible.
      const dash = Math.max(0, fraction * circumference - 2);
      const arc = { ...s, dash, offset, index: i, fraction };
      offset += fraction * circumference;
      return arc;
    });

  const shown = active !== null ? arcs.find((a) => a.index === active) : null;

  return (
    <div className="donut" style={{ width: size, height: size }}>
      <svg width={size} height={size} style={{ transform: "rotate(-90deg)" }}>
        <circle cx={c} cy={c} r={r} fill="none" stroke="var(--panel-2)" strokeWidth={thickness} />
        {arcs.map((a) => (
          <circle
            key={a.label}
            cx={c}
            cy={c}
            r={r}
            fill="none"
            stroke={a.color}
            strokeWidth={active === a.index ? thickness + 4 : thickness}
            strokeDasharray={`${a.dash} ${circumference - a.dash}`}
            strokeDashoffset={-a.offset}
            strokeLinecap="butt"
            style={{ transition: "stroke-width var(--t-fast) var(--ease)", cursor: "pointer" }}
            onMouseEnter={() => setActive(a.index)}
            onMouseLeave={() => setActive(null)}
          />
        ))}
      </svg>
      <div className="donut__center">
        <div className="donut__value">
          {shown ? shown.value : total}
        </div>
        <div className="donut__label">
          {shown ? shown.label : (centerLabel ?? "total")}
        </div>
      </div>
    </div>
  );
}

export function Legend({ slices, total }: { slices: Slice[]; total?: number }) {
  const sum = total ?? slices.reduce((s, x) => s + x.value, 0);
  return (
    <ul className="legend">
      {slices.map((s) => (
        <li key={s.label} className="legend__item">
          <span className="legend__swatch" style={{ background: s.color }} />
          <span className="legend__label truncate">{s.label}</span>
          <span className="legend__value">
            {s.value}
            {sum > 0 && <span className="faint"> · {Math.round((s.value / sum) * 100)}%</span>}
          </span>
        </li>
      ))}
    </ul>
  );
}

/* ====================================================================== */
/* Ring gauge — one rate, as a fraction of its own ceiling                 */
/* ====================================================================== */

export function Ring({
  value,
  size = 56,
  thickness = 5,
  tone = "accent",
}: {
  /** 0..1, or null when the denominator was empty. */
  value: number | null;
  size?: number;
  thickness?: number;
  tone?: "accent" | "ok" | "warn" | "err";
}) {
  const r = (size - thickness) / 2;
  const c = size / 2;
  const circ = 2 * Math.PI * r;
  const pct = value ?? 0;
  const stroke = `var(--${tone === "accent" ? "accent" : tone})`;

  return (
    <svg width={size} height={size} aria-hidden="true" style={{ transform: "rotate(-90deg)" }}>
      <circle cx={c} cy={c} r={r} fill="none" stroke="var(--panel-2)" strokeWidth={thickness} />
      {/* Zero draws nothing. A round line cap on a zero-length dash still
          paints a dot, which reads as "a very small amount" rather than
          "none" — and on an accuracy gauge that difference matters. */}
      {value !== null && pct > 0 && (
        <circle
          cx={c}
          cy={c}
          r={r}
          fill="none"
          stroke={stroke}
          strokeWidth={thickness}
          strokeDasharray={`${pct * circ} ${circ}`}
          strokeLinecap="round"
          style={{ transition: "stroke-dasharray var(--t-slow) var(--ease)" }}
        />
      )}
    </svg>
  );
}

/* ====================================================================== */
/* Bucketing helpers — turn API rows into a series, honestly               */
/* ====================================================================== */

/**
 * Buckets timestamped rows into a series, choosing the grain from the data.
 *
 * A fresh install has every run inside one afternoon. Bucketed by day over 30
 * days that is 29 empty columns and one spike — technically true and visually
 * useless. So the grain follows the span: hours when everything is recent,
 * days otherwise.
 *
 * Empty buckets are zeros rather than gaps either way, which is the honest
 * shape: in an hour when nothing ran, nothing ran. Dropping empty buckets
 * would compress the axis and make a quiet week look busy.
 */
export function bucketSeries<T>(
  rows: T[],
  getDate: (row: T) => string | null | undefined,
  maxDays: number,
): { labels: string[]; keys: string[]; counts: number[]; grain: "hour" | "day" } {
  const stamps = rows
    .map((r) => getDate(r))
    .filter((d): d is string => Boolean(d))
    .map((d) => new Date(d).getTime())
    .filter((t) => !Number.isNaN(t));

  const spanMs = stamps.length ? Date.now() - Math.min(...stamps) : 0;
  const grain: "hour" | "day" = stamps.length > 0 && spanMs < 36 * 3600_000 ? "hour" : "day";

  const keys: string[] = [];
  const labels: string[] = [];

  if (grain === "hour") {
    const now = new Date();
    now.setMinutes(0, 0, 0);
    for (let i = 23; i >= 0; i--) {
      const d = new Date(now.getTime() - i * 3600_000);
      keys.push(hourKey(d));
      labels.push(d.toLocaleTimeString(undefined, { hour: "numeric" }));
    }
  } else {
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    for (let i = maxDays - 1; i >= 0; i--) {
      const d = new Date(today);
      d.setDate(d.getDate() - i);
      keys.push(dayKey(d));
      labels.push(d.toLocaleDateString(undefined, { month: "short", day: "numeric" }));
    }
  }

  const counts = tally(rows, keys, getDate, grain, () => true);
  return { labels, keys, counts, grain };
}

const dayKey = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

const hourKey = (d: Date) => `${dayKey(d)}T${String(d.getHours()).padStart(2, "0")}`;

function tally<T>(
  rows: T[],
  keys: string[],
  getDate: (row: T) => string | null | undefined,
  grain: "hour" | "day",
  predicate: (row: T) => boolean,
): number[] {
  const index = new Map(keys.map((k, i) => [k, i]));
  const counts = new Array(keys.length).fill(0);
  for (const row of rows) {
    if (!predicate(row)) continue;
    const raw = getDate(row);
    if (!raw) continue;
    const d = new Date(raw);
    if (Number.isNaN(d.getTime())) continue;
    const i = index.get(grain === "hour" ? hourKey(d) : dayKey(d));
    if (i !== undefined) counts[i] += 1;
  }
  return counts;
}

/** The same buckets, filtered — so series line up column for column. */
export function bucketCountsBy<T>(
  rows: T[],
  keys: string[],
  getDate: (row: T) => string | null | undefined,
  predicate: (row: T) => boolean,
  grain: "hour" | "day" = "day",
): number[] {
  return tally(rows, keys, getDate, grain, predicate);
}
