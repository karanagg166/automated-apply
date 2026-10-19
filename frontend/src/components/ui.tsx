"use client";
import {
  forwardRef,
  useId,
  Children,
  cloneElement,
  isValidElement,
  type ReactElement,
  type ButtonHTMLAttributes,
  type InputHTMLAttributes,
  type SelectHTMLAttributes,
  type ReactNode,
} from "react";
import * as Dialog from "@radix-ui/react-dialog";
import {
  AlertCircle,
  ArrowUpRight,
  LoaderCircle,
  SearchX,
  X,
} from "lucide-react";
import { clsx } from "clsx";
import { ApiError, externalUrl } from "@/lib/api";
export const Button = forwardRef<
  HTMLButtonElement,
  ButtonHTMLAttributes<HTMLButtonElement> & {
    variant?: "primary" | "secondary" | "ghost" | "danger";
    busy?: boolean;
  }
>(function Button(
  { className, variant = "secondary", busy, children, disabled, ...props },
  ref,
) {
  return (
    <button
      ref={ref}
      className={clsx("button", variant, className)}
      disabled={disabled || busy}
      {...props}
    >
      {busy && <LoaderCircle size={15} className="spin" />}
      {children}
    </button>
  );
});
export const Input = forwardRef<
  HTMLInputElement,
  InputHTMLAttributes<HTMLInputElement>
>(function Input({ className, ...props }, ref) {
  return <input ref={ref} className={clsx("input", className)} {...props} />;
});
export function Select({
  className,
  children,
  ...props
}: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select className={clsx("input", className)} {...props}>
      {children}
    </select>
  );
}
export function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: ReactNode;
}) {
  const id = useId();
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      {Children.map(children, (child) => {
        if (
          isValidElement(child) &&
          (child.type === Input ||
            child.type === Select ||
            ["input", "select", "textarea"].includes(String(child.type)))
        ) {
          return cloneElement(child as ReactElement<Record<string, unknown>>, {
            id,
            "aria-describedby": hint ? `${id}-hint` : undefined,
          });
        }
        return child;
      })}
      {hint && <small id={`${id}-hint`}>{hint}</small>}
    </div>
  );
}
export function Badge({
  children,
  tone = "neutral",
}: {
  children: ReactNode;
  tone?: "neutral" | "green" | "amber" | "red";
}) {
  return <span className={`badge ${tone}`}>{children}</span>;
}
export function External({
  href,
  children,
  className,
}: {
  href?: string | null;
  children: ReactNode;
  className?: string;
}) {
  const url = externalUrl(href);
  return url ? (
    <a
      className={clsx("external", className)}
      href={url}
      target="_blank"
      rel="noopener noreferrer"
    >
      {children}
      <ArrowUpRight size={14} />
    </a>
  ) : (
    <span className="muted">Link unavailable</span>
  );
}
export function Empty({
  title = "Nothing here yet",
  description,
  action,
}: {
  title?: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <div className="empty">
      <div className="empty-icon">
        <SearchX size={25} />
      </div>
      <h3>{title}</h3>
      <p>{description}</p>
      {action}
    </div>
  );
}
export function Skeleton() {
  return (
    <div className="skeleton-grid" aria-label="Loading results" role="status">
      {[1, 2, 3].map((i) => (
        <div className="skeleton" key={i}>
          <i />
          <i />
          <i />
        </div>
      ))}
    </div>
  );
}
export function ErrorState({
  error,
  retry,
}: {
  error: unknown;
  retry?: () => void;
}) {
  const message =
    error instanceof Error ? error.message : "Something could not be loaded";
  return (
    <div className="error-state" role="alert">
      <AlertCircle size={20} />
      <div>
        <strong>
          {error instanceof ApiError && error.status === 401
            ? "Sign in required"
            : error instanceof ApiError && error.status === 429
              ? "Rate limit reached"
              : "Unable to complete this request"}
        </strong>
        <p>{message}</p>
        {retry && <Button onClick={retry}>Try again</Button>}
        {error instanceof ApiError && error.status === 401 && (
          <a href="/login">Sign in</a>
        )}
      </div>
    </div>
  );
}
export function Notice({ children }: { children: ReactNode }) {
  return (
    <div className="notice" role="status">
      {children}
    </div>
  );
}
export function Modal({
  open,
  onOpenChange,
  title,
  description,
  children,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  title: string;
  description: string;
  children: ReactNode;
}) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content className="dialog-content">
          <Dialog.Title className="dialog-title">{title}</Dialog.Title>
          <Dialog.Description className="muted">
            {description}
          </Dialog.Description>
          <Dialog.Close
            className="icon-button dialog-close"
            aria-label="Close dialog"
          >
            <X size={20} />
          </Dialog.Close>
          {children}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
export function PageTitle({
  eyebrow,
  title,
  description,
  actions,
}: {
  eyebrow: string;
  title: string;
  description: string;
  actions?: ReactNode;
}) {
  return (
    <div className="page-heading">
      <div>
        <div className="eyebrow">{eyebrow}</div>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      {actions && <div className="actions">{actions}</div>}
    </div>
  );
}
