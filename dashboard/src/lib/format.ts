const DASH = "–";

export function pct(value: number | null | undefined, digits = 0): string {
  return value === null || value === undefined ? DASH : `${(value * 100).toFixed(digits)}%`;
}

export function pctRange(ci: [number, number] | null | undefined): string {
  return ci ? `${pct(ci[0])}–${pct(ci[1])}` : DASH;
}

export function money(value: number | null | undefined): string {
  if (value === null || value === undefined) return DASH;
  if (value === 0) return "$0";
  return value < 0.01 ? `$${value.toFixed(4)}` : `$${value.toFixed(3)}`;
}

export function ms(value: number | null | undefined): string {
  if (value === null || value === undefined) return DASH;
  return value >= 1000 ? `${(value / 1000).toFixed(1)} s` : `${Math.round(value)} ms`;
}

export function num(value: number | null | undefined, digits = 1): string {
  return value === null || value === undefined ? DASH : value.toFixed(digits);
}

/** "single_fact" -> "Single fact"; "retrieval_miss" -> "Retrieval miss". */
export function humanize(snake: string): string {
  const s = snake.replace(/_/g, " ").trim();
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : s;
}

export function signed(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined) return DASH;
  return `${value >= 0 ? "+" : ""}${value.toFixed(digits)}`;
}

export function shortId(id: string, n = 12): string {
  return id.length > n ? `${id.slice(0, n)}…` : id;
}
