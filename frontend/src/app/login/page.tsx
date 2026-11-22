"use client";
import { useEffect, useState } from "react";
import {
  ArrowUpRight,
  Fingerprint,
  LoaderCircle,
  LockKeyhole,
} from "lucide-react";
export default function Login() {
  const [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  const [ready, setReady] = useState(false);
  useEffect(() => setReady(true), []);
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
          method="post"
          action="/api/auth"
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
          <div className="field">
            <label htmlFor="owner-passphrase">Owner passphrase</label>
            <input
              className="input"
              id="owner-passphrase"
              name="password"
              type="password"
              autoComplete="current-password"
              required
              maxLength={256}
              autoFocus
              disabled={!ready}
            />
          </div>
          {error && (
            <p role="alert" className="form-error">
              {error}
            </p>
          )}
          <button
            type="submit"
            className="button primary"
            disabled={!ready || busy}
          >
            {busy && (
              <LoaderCircle size={15} className="spin" aria-hidden="true" />
            )}
            Enter workspace
            <ArrowUpRight size={17} />
          </button>
        </form>
        <p className="private-note">
          <LockKeyhole size={14} /> Single owner. Private by default.
        </p>
      </section>
    </main>
  );
}
