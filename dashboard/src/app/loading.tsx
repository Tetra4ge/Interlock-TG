export default function Loading() {
  return (
    <div aria-busy="true" aria-live="polite" className="animate-pulse space-y-4">
      <div className="h-8 w-64 rounded bg-surface-muted" />
      <div className="grid gap-4 md:grid-cols-3">
        <div className="h-28 rounded-xl bg-surface-muted" />
        <div className="h-28 rounded-xl bg-surface-muted" />
        <div className="h-28 rounded-xl bg-surface-muted" />
      </div>
      <div className="h-72 rounded-xl bg-surface-muted" />
    </div>
  );
}
