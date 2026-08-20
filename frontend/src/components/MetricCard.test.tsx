/**
 * The metric card's structural contract.
 *
 * jsdom computes no layout, so these cannot assert "the gauge does not overlap
 * the value" in pixels — that check lives in the browser gates. What they can
 * assert is the *structure* that made the overlap impossible: value and gauge
 * are siblings in their own row, and the label is a single element that never
 * shares a line with either. If someone flattens that back into one flex row
 * to save an element, these fail.
 */

import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { MetricCard } from "./MetricCard";

const base = { testId: "metric-x", valueTestId: "metric-value-x", label: "TOOL SUCCESS" };

describe("MetricCard", () => {
  it("keeps the value and the gauge as siblings, not nested or stacked", () => {
    const { container } = render(<MetricCard {...base} value="100.0%" ring={1} />);

    const body = container.querySelector(".metric__body")!;
    const value = body.querySelector(".metric__value");
    const ring = body.querySelector(".metric__ring");

    expect(value).toBeInTheDocument();
    expect(ring).toBeInTheDocument();
    // Siblings under one row is the property; nesting the gauge inside the
    // value is exactly how they came to overlap.
    expect(value!.parentElement).toBe(body);
    expect(ring!.parentElement).toBe(body);
  });

  it("keeps the label out of the value's row", () => {
    const { container } = render(<MetricCard {...base} value="100.0%" ring={1} />);
    const label = container.querySelector(".metric__label")!;
    expect(label.closest(".metric__body")).toBeNull();
    expect(label.closest(".metric__head")).not.toBeNull();
  });

  it("omits the gauge entirely when no ring is given", () => {
    const { container } = render(<MetricCard {...base} value="1329" />);
    expect(container.querySelector(".metric__ring")).toBeNull();
  });

  it("omits the gauge for an absent value rather than drawing an empty one", () => {
    // "—" is the agreed signal for "the API sent null". A 0% gauge beside it
    // would claim a measurement that was never taken.
    const { container } = render(<MetricCard {...base} value="—" ring={null} />);
    expect(container.querySelector(".metric__ring")).toBeNull();
    expect(screen.getByTestId("metric-value-x")).toHaveTextContent("No data yet");
  });

  it("renders the unit inside the value so it reads as one figure", () => {
    render(<MetricCard {...base} label="AVG LATENCY" value="0.13" unit="s" />);
    expect(screen.getByTestId("metric-value-x")).toHaveTextContent("0.13s");
  });

  it("carries both testids so a gate can address the card and its number", () => {
    render(<MetricCard {...base} value="92.9%" ring={0.929} />);
    expect(screen.getByTestId("metric-x")).toBeInTheDocument();
    expect(screen.getByTestId("metric-value-x")).toHaveTextContent("92.9%");
  });
});
