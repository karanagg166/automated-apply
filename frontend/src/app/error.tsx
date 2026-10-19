"use client";
import { Button } from "@/components/ui";
export default function Error({ reset }: { reset: () => void }) {
  return (
    <main className="page-content">
      <h1>This view could not be loaded.</h1>
      <p className="section-intro spaced">
        Your saved work is preserved. Check the server configuration and try
        again.
      </p>
      <Button onClick={reset}>Try again</Button>
    </main>
  );
}
