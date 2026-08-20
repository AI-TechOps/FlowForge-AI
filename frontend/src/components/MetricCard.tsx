/**
 * The metric card. **One implementation, used everywhere** — the dashboard and
 * the evaluation screen previously had their own, which is how two cards that
 * look like siblings drift apart.
 *
 * The layout is three stacked rows rather than one flex row, and that is the
 * fix for a real collision: with badge, label, value and ring all in a single
 * row, a label long enough to wrap ("TOOL SUCCESS", "APPROVAL RATE") grew the
 * text column and pushed the value straight under the ring gauge.
 *
 *   ┌──────────────────────────────┐
 *   │ [badge]  LABEL               │   head — never wraps
 *   │ 100.0%              (ring)   │   body — value and ring are siblings
 *   │ the five MVP tools           │   sub
 *   └──────────────────────────────┘
 *
 * Value and ring being siblings in their own row is what makes overlap
 * impossible: the ring is `flex: none` so it cannot be squeezed, and the value
 * has `min-width: 0` so it shrinks rather than running underneath.
 */

import type { ReactNode } from "react";

import { Ring } from "./charts";
import { Sparkline } from "./charts";
import { testid } from "../testids";

export type MetricTone = "accent" | "ok" | "warn" | "err" | "neutral";

export function MetricCard({
  testId,
  valueTestId,
  label,
  value,
  unit,
  sub,
  icon,
  tone = "accent",
  spark,
  ring,
}: {
  testId: string;
  valueTestId: string;
  label: string;
  /** Already formatted. "—" is the agreed signal for "the API sent null". */
  value: string;
  unit?: string;
  sub?: ReactNode;
  icon?: ReactNode;
  tone?: MetricTone;
  spark?: number[];
  /** 0..1, or null when the denominator was empty. Omit for no gauge. */
  ring?: number | null;
}) {
  const empty = value === "—";
  const ringTone = tone === "neutral" ? "accent" : tone;

  return (
    <div className="metric" {...testid(testId)}>
      <div className="metric__head">
        {icon && <span className={`metric__badge metric__badge--${tone}`}>{icon}</span>}
        {/* Single line, always. A label that wraps on one card and not the
            next makes a row of cards look misaligned even when it is not. */}
        <span className="metric__label truncate" title={label}>
          {label}
        </span>
      </div>

      <div className="metric__body">
        {empty ? (
          <span className="metric__value--empty" {...testid(valueTestId)}>
            No data yet
          </span>
        ) : (
          <span className="metric__value" {...testid(valueTestId)}>
            {value}
            {unit && <span className="metric__unit">{unit}</span>}
          </span>
        )}
        {ring !== undefined && !empty && (
          <span className="metric__ring">
            <Ring value={ring} tone={ringTone} size={44} thickness={4} />
          </span>
        )}
      </div>

      {sub && <div className="metric__sub">{sub}</div>}

      {spark && spark.length > 1 && (
        <div className="metric__spark">
          <Sparkline values={spark} tone={ringTone} />
        </div>
      )}
    </div>
  );
}
