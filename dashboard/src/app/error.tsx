"use client";

import { useEffect } from "react";

// In this Next.js version the recovery callback is `retry` (older releases called it `reset`).
export default function Error({
  error,
  retry,
}: {
  error: Error & { digest?: string };
  retry: () => void;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <div role="alert" className="mx-auto max-w-xl rounded-xl border border-red-300 bg-red-50 p-6 dark:border-red-900 dark:bg-red-950/40">
      <h2 className="text-lg font-semibold text-danger">Something went wrong</h2>
      <p className="mt-1 text-sm">{error.message || "An unexpected error occurred while rendering this page."}</p>
      <button
        onClick={() => retry()}
        className="mt-4 rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-background"
      >
        Try again
      </button>
    </div>
  );
}
