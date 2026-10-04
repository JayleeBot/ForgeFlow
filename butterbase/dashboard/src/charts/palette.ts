import { useEffect, useRef, useState } from "react";
import type { RefObject } from "react";

/**
 * Categorical series colours, in a fixed order that passes the colour-vision
 * deficiency checks on adjacent pairs (validated against the white panel
 * surface). Assign by position, never cycle: a part with more offers than slots
 * is not expected, but the last slot repeats rather than inventing a hue.
 * Magenta, yellow and aqua sit below 3:1 contrast on white, so every chart
 * that uses them also has a legend and the table view.
 */
export const SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"];

export const seriesColor = (i: number) => SERIES[Math.min(i, SERIES.length - 1)];

/**
 * Status colours, reserved for the follow-up clock and never used for a series.
 * They always ship with an icon and a text label, so colour is never the only
 * signal.
 */
export const STATUS = {
  good: "#0ca30c",
  warning: "#fab219",
  critical: "#d03b3b",
} as const;

/** Width of an element, tracked as it resizes, so SVG charts draw at real pixels. */
export function useWidth<T extends HTMLElement>(): [RefObject<T | null>, number] {
  const ref = useRef<T | null>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const observer = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width));
    observer.observe(el);
    setWidth(el.getBoundingClientRect().width);
    return () => observer.disconnect();
  }, []);
  return [ref, width];
}

/** Round tick values: 1, 2 or 5 times a power of ten. */
export function niceTicks(min: number, max: number, count = 4): number[] {
  if (min === max) {
    const pad = Math.abs(min) * 0.1 || 1;
    min -= pad;
    max += pad;
  }
  const raw = (max - min) / count;
  const pow = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 5, 10].map((m) => m * pow).find((s) => s >= raw) ?? raw;
  const start = Math.floor(min / step) * step;
  const ticks: number[] = [];
  for (let v = start; v <= max + step * 0.5; v += step) ticks.push(Number(v.toFixed(10)));
  return ticks;
}
