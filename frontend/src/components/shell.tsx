"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useTheme } from "next-themes";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowUpRight,
  Bell,
  BriefcaseBusiness,
  Building2,
  ChevronRight,
  CircleHelp,
  Command,
  Compass,
  LayoutDashboard,
  LogOut,
  Mail,
  Menu,
  Moon,
  Plug,
  Search,
  Settings2,
  ShieldCheck,
  Sun,
  UserRound,
  Users,
  X,
} from "lucide-react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui";
const nav = [
  ["Overview", "/", LayoutDashboard],
  ["Discover", "/discover", Compass],
  ["Startups", "/startups", Building2],
  ["Jobs", "/jobs", BriefcaseBusiness],
  ["People", "/people", Users],
  ["Applications", "/applications", LayoutDashboard],
  ["Outreach", "/outreach", Mail],
  ["Notifications", "/notifications", Bell],
  ["Connections", "/connections", Plug],
  ["My Profile", "/profile", UserRound],
  ["Settings", "/settings", Settings2],
] as const;
export function Shell({ children }: { children: React.ReactNode }) {
  const path = usePathname(),
    router = useRouter(),
    { resolvedTheme, setTheme } = useTheme(),
    [mobile, setMobile] = useState(false),
    [search, setSearch] = useState("");
  const connection = useQuery({
    queryKey: ["connections"],
    queryFn: () =>
      api<{ connectors: Array<{ platform: string; live_verified: boolean }> }>(
        "integrations",
      ),
  });
  const runtime = useQuery({
    queryKey: ["runtime"],
    queryFn: () => api<{ demo_mode: boolean }>("dashboard/runtime"),
  });
  const healthy =
    connection.data?.connectors.filter((x) => x.live_verified).length || 0;
  const label =
    nav.find(([, url]) =>
      url === "/" ? path === "/" : path.startsWith(url),
    )?.[0] || "Workspace";
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      {mobile && (
        <button
          className="sidebar-scrim"
          onClick={() => setMobile(false)}
          aria-label="Close navigation"
        />
      )}
      <aside className={`sidebar ${mobile ? "open" : ""}`}>
        <Link className="brand" href="/" onClick={() => setMobile(false)}>
          <span className="brand-mark">a</span>
          <span>
            automated<span className="brand-light">apply</span>
          </span>
        </Link>
        <div className="workspace-label">
          <span className="workspace-icon">
            <Command size={15} />
          </span>
          <div>
            Personal workspace<small>Owner access</small>
          </div>
          <ShieldCheck size={14} />
        </div>
        <span className="nav-caption">WORKSPACE</span>
        <nav aria-label="Main navigation">
          {nav.map(([name, url, Icon], i) => (
            <Link
              key={url}
              href={url}
              onClick={() => setMobile(false)}
              className={`${(url === "/" ? path === "/" : path.startsWith(url)) ? "active" : ""} ${i === 8 ? "nav-divider" : ""}`}
              aria-current={
                (url === "/" ? path === "/" : path.startsWith(url))
                  ? "page"
                  : undefined
              }
            >
              <Icon size={18} />
              {name}
              {name === "Startups" && <span className="nav-new">EXPLORE</span>}
            </Link>
          ))}
        </nav>
        <div className="sidebar-note">
          <span className="status-dot" />
          <strong>Your search. Your pace.</strong>
          <p>Every application and message stays in your control.</p>
          <Link href="/connections">
            Review connections
            <ArrowUpRight size={14} />
          </Link>
        </div>
        <div className="sidebar-owner">
          <div className="avatar">O</div>
          <div>
            <strong>Owner workspace</strong>
            <small>Private command center</small>
          </div>
          <Button
            variant="ghost"
            aria-label="Sign out"
            onClick={async () => {
              const csrf =
                document.cookie
                  .split("; ")
                  .find((x) => x.startsWith("aa_csrf="))
                  ?.split("=")[1] || "";
              await fetch("/api/auth", {
                method: "DELETE",
                headers: { "X-CSRF-Token": csrf },
              });
              window.location.assign("/login");
            }}
          >
            <LogOut size={16} />
          </Button>
        </div>
      </aside>
      <div className="workspace-main">
        <header className="topbar">
          <button
            className="icon-button mobile-menu"
            aria-label="Open navigation"
            onClick={() => setMobile(!mobile)}
          >
            {mobile ? <X size={20} /> : <Menu size={20} />}
          </button>
          <div className="breadcrumb">
            Workspace
            <ChevronRight size={13} />
            <strong>{label}</strong>
          </div>
          <form
            className="global-search"
            onSubmit={(e) => {
              e.preventDefault();
              router.push(`/startups?q=${encodeURIComponent(search)}`);
            }}
          >
            <Search size={16} />
            <input
              aria-label="Search saved companies"
              placeholder="Search your workspace…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
            <kbd>↵</kbd>
          </form>
          <Link className="connection-health" href="/connections">
            <span className={`status-dot ${healthy ? "" : "amber-dot"}`} />
            {connection.isError
              ? "Connection unavailable"
              : `${healthy} live connections`}
          </Link>
          <button
            className="icon-button"
            aria-label="Toggle color theme"
            onClick={() =>
              setTheme(resolvedTheme === "dark" ? "light" : "dark")
            }
          >
            <Sun className="theme-sun" size={18} />
            <Moon className="theme-moon" size={18} />
          </button>
          <Link
            className="icon-button notification-bell"
            href="/notifications"
            aria-label="Notifications"
          >
            <Bell size={19} />
          </Link>
          <Link
            href="/profile"
            className="avatar small-avatar"
            aria-label="Open my profile"
          >
            O
          </Link>
        </header>
        {runtime.data?.demo_mode && (
          <div className="fixture-banner">
            ISOLATED DEMONSTRATION · Fictional fixtures · Actual FastAPI · No
            live provider calls
          </div>
        )}
        <main id="main" className="page-content">
          {children}
        </main>
        <footer className="workspace-footer">
          <span>
            <ShieldCheck size={13} /> Private workspace · Human decisions,
            thoughtful automation.
          </span>
          <Link href="/settings">
            <CircleHelp size={14} /> Workspace settings
          </Link>
        </footer>
      </div>
    </div>
  );
}
