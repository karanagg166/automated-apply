"use client";
import { useState } from "react";
import { ArrowUpRight, Fingerprint, LockKeyhole } from "lucide-react";
import { Button, Field, Input } from "@/components/ui";
export default function Login() {
  const [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  return (
    <main className="login">
      <div className="login-story">
        <a className="brand" href="/login">
          <span className="brand-mark">a</span>automated
          <span className="brand-light">apply</span>
        </a>
        <div>
          <div className="eyebrow">A LITTLE MORE INTENTIONAL.</div>
          <h1>
            Your next chapter.
            <br />
            <span>Within reach.</span>
          </h1>
          <p>
            A private space to discover the right teams, tell your story, and
            make your next move.
          </p>
        </div>
        <span className="login-foot">
          <span className="status-dot" /> Built around you. Always in your
          control.
        </span>
      </div>
      <section className="login-form">
        <div className="empty-icon">
          <Fingerprint size={30} />
        </div>
        <div className="eyebrow">YOUR PRIVATE WORKSPACE</div>
        <h2>Welcome back.</h2>
        <p className="muted">Sign in with your owner passphrase to continue.</p>
        <form
          onSubmit={async (e) => {
            e.preventDefault();
            setBusy(true);
            setError("");
            const password = String(
              new FormData(e.currentTarget).get("password"),
            );
            try {
              const response = await fetch("/api/auth", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ password }),
              });
              const data = await response.json();
              if (!response.ok) throw new Error(data.detail);
              window.location.assign("/");
            } catch (err) {
              setError(err instanceof Error ? err.message : "Login failed");
            } finally {
              setBusy(false);
            }
          }}
        >
          <Field label="Owner passphrase">
            <Input
              name="password"
              type="password"
              autoComplete="current-password"
              required
              maxLength={256}
              autoFocus
            />
          </Field>
          {error && (
            <p role="alert" className="form-error">
              {error}
            </p>
          )}
          <Button type="submit" variant="primary" busy={busy}>
            Enter workspace
            <ArrowUpRight size={17} />
          </Button>
        </form>
        <p className="private-note">
          <LockKeyhole size={14} /> Single owner. Private by default.
        </p>
      </section>
    </main>
  );
}
