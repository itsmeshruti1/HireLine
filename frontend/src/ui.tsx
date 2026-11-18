import { useEffect, useId, useRef } from "react";
import type { ButtonHTMLAttributes, ReactNode } from "react";
import { ArrowUpRight, Check, ChevronRight, Loader2, X } from "lucide-react";
import { useEntrance } from "./motion";

export function Button({
  children,
  variant = "primary",
  className = "",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost" | "danger";
}) {
  return (
    <button className={`button button-${variant} ${className}`} {...props}>
      {children}
    </button>
  );
}
export function Badge({
  children,
  tone = "neutral",
}: {
  children: ReactNode;
  tone?: string;
}) {
  return <span className={`badge badge-${tone}`}>{children}</span>;
}
export function StageBadge({ stage }: { stage: string }) {
  const tones: Record<string, string> = {
    new: "neutral",
    screening: "purple",
    shortlisted: "blue",
    assessment: "amber",
    interview: "purple",
    hired: "green",
    rejected: "red",
    withdrawn: "neutral",
  };
  return (
    <Badge tone={tones[stage] ?? "neutral"}>
      <span className="badge-dot" />
      {label(stage)}
    </Badge>
  );
}
export function label(value: string) {
  return value.replace(/[_.]/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}
export function initials(name: string) {
  return (name || "Candidate")
    .split(" ")
    .filter(Boolean)
    .slice(0, 2)
    .map((n) => n[0])
    .join("");
}
export function Avatar({
  name,
  size = "",
  index = 0,
}: {
  name: string;
  size?: string;
  index?: number;
}) {
  return (
    <span className={`avatar avatar-${index % 5} ${size}`} aria-hidden="true">
      {initials(name)}
    </span>
  );
}
export function Score({
  score,
  compact = false,
  emptyLabel = "Not screened",
}: {
  score?: number;
  compact?: boolean;
  emptyLabel?: string;
}) {
  if (score === undefined || score === null)
    return <span className="muted small">{emptyLabel}</span>;
  const n = Math.round(score);
  return (
    <span
      className={`score ${compact ? "score-compact" : ""} ${n >= 75 ? "score-good" : n >= 50 ? "score-medium" : "score-low"}`}
    >
      <span className="score-dot" />
      {n}
      <span className="score-percent">%</span>
    </span>
  );
}
export function Spinner({ text = "Loading workspace…" }: { text?: string }) {
  return (
    <div className="loading-state">
      <Loader2 size={23} className="spin" />
      <span>{text}</span>
    </div>
  );
}
export function Empty({
  title,
  text,
  action,
}: {
  title: string;
  text: string;
  action?: ReactNode;
}) {
  return (
    <div className="empty-state">
      <span className="empty-mark">
        <Check size={24} />
      </span>
      <h3>{title}</h3>
      <p>{text}</p>
      {action}
    </div>
  );
}
export function SectionHeader({
  title,
  subtitle,
  action,
}: {
  title: string;
  subtitle?: string;
  action?: ReactNode;
}) {
  return (
    <div className="section-header">
      <div>
        <h2>{title}</h2>
        {subtitle && <p>{subtitle}</p>}
      </div>
      {action}
    </div>
  );
}
export function TextLink({
  children,
  onClick,
}: {
  children: ReactNode;
  onClick: () => void;
}) {
  return (
    <button className="text-link" onClick={onClick}>
      {children}
      <ChevronRight size={15} />
    </button>
  );
}
export function ExternalLink({
  href,
  children,
}: {
  href: string;
  children: ReactNode;
}) {
  return (
    <a href={href} target="_blank" rel="noreferrer" className="text-link">
      {children}
      <ArrowUpRight size={14} />
    </a>
  );
}
export function date(value: string | undefined, withTime = false) {
  if (!value || !Number.isFinite(new Date(value).getTime())) return "—";
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    ...(withTime ? { hour: "numeric", minute: "2-digit" } : {}),
  }).format(new Date(value));
}
export function relativeDate(value?: string) {
  if (!value) return "Recently";
  const minutes = Math.max(
    0,
    Math.round((Date.now() - new Date(value).getTime()) / 60_000),
  );
  if (minutes < 1) return "Just now";
  if (minutes < 60) return `${minutes}m ago`;
  if (minutes < 1440) return `${Math.floor(minutes / 60)}h ago`;
  return date(value);
}
export function Modal({
  title,
  eyebrow,
  children,
  onClose,
  wide = false,
}: {
  title: string;
  eyebrow?: string;
  children: ReactNode;
  onClose: () => void;
  wide?: boolean;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEntrance(ref, "dialog");
  const titleId = useId();
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  useEffect(() => {
    const prior = document.activeElement as HTMLElement;
    const overflow = document.body.style.overflow;
    const backdrop = ref.current?.closest<HTMLElement>(".modal-backdrop");
    const siblings = [...(backdrop?.parentElement?.children ?? [])].filter(
      (element): element is HTMLElement =>
        element instanceof HTMLElement && element !== backdrop,
    );
    const inertStates = siblings.map((element) => ({
      element,
      inert: element.inert,
    }));
    siblings.forEach((element) => {
      element.inert = true;
    });
    const priorDialog = [
      ...document.querySelectorAll<HTMLElement>('[role="dialog"]'),
    ]
      .filter((dialog) => dialog !== ref.current)
      .at(-1);
    const priorBackdrop = priorDialog?.closest<HTMLElement>(".modal-backdrop");
    if (priorBackdrop) {
      priorBackdrop.inert = true;
      priorBackdrop.setAttribute("aria-hidden", "true");
    }
    document.body.style.overflow = "hidden";
    const timer = window.setTimeout(
      () =>
        ref.current
          ?.querySelector<HTMLElement>("input, select, textarea, button")
          ?.focus(),
      30,
    );
    function key(e: KeyboardEvent) {
      if (
        [...document.querySelectorAll('[role="dialog"]')].at(-1) !== ref.current
      )
        return;
      if (e.key === "Escape") closeRef.current();
      if (e.key === "Tab") {
        const all = Array.from(
          ref.current?.querySelectorAll<HTMLElement>(
            'button:not(:disabled), a[href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex="0"]',
          ) ?? [],
        );
        const first = all[0];
        const last = all[all.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last?.focus();
        }
        if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first?.focus();
        }
      }
    }
    window.addEventListener("keydown", key);
    return () => {
      clearTimeout(timer);
      document.body.style.overflow = overflow;
      window.removeEventListener("keydown", key);
      if (priorBackdrop) priorBackdrop.removeAttribute("aria-hidden");
      inertStates.forEach(({ element, inert }) => {
        element.inert = inert;
      });
      prior?.focus();
    };
  }, []);
  return (
    <div
      className="modal-backdrop"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className={`modal ${wide ? "modal-wide" : ""}`}
      >
        <header className="modal-heading">
          <div>
            {eyebrow && <span className="eyebrow">{eyebrow}</span>}
            <h2 id={titleId}>{title}</h2>
          </div>
          <button
            className="icon-button"
            onClick={onClose}
            aria-label="Close dialog"
          >
            <X size={20} />
          </button>
        </header>
        {children}
      </div>
    </div>
  );
}
