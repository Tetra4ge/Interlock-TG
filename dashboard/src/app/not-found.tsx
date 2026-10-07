import Link from "next/link";

export default function NotFound() {
  return (
    <div className="mx-auto max-w-md py-16 text-center">
      <h1 className="text-2xl font-semibold">Page not found</h1>
      <p className="mt-2 text-sm text-muted">That page does not exist.</p>
      <Link href="/" className="mt-4 inline-block rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-background">
        Back to the overview
      </Link>
    </div>
  );
}
