import { useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowDownToLine,
  ArrowUpRight,
  Bell,
  BriefcaseBusiness,
  ChartNoAxesCombined,
  CircleHelp,
  Command,
  LayoutDashboard,
  LogIn,
  LogOut,
  Menu,
  Plus,
  RefreshCw,
  Search,
  Settings2,
  ShieldCheck,
  Users,
  Workflow,
  X,
} from "lucide-react";
import { useEntrance } from "./motion";
import { csvCell } from "./export";
import { api, tokenStore } from "./api";
import { Context, canManage, screeningScore } from "./context";
import type { ModalState, Page } from "./context";
import type { Application, Config, User, Workspace } from "./types";
import { Avatar, Button, Modal, Spinner, label } from "./ui";
import {
  AnalyticsPage,
  CandidatesPage,
  JobsPage,
  OverviewPage,
  PipelinePage,
  SettingsPage,
} from "./pages";
import { ModalHost } from "./forms";
import { CandidatePanel } from "./CandidatePanel";
import { InvitationPage } from "./InvitationPage";

const EMPTY: Workspace = {
  jobs: [],
  candidates: [],
  applications: [],
  screenings: [],
  assessments: [],
  interviews: [],
  feedback: [],
  activities: [],
  tasks: [],
  metrics: {},
};
const NAV = [
  { id: "overview" as const, title: "Overview", icon: LayoutDashboard },
  { id: "jobs" as const, title: "Job openings", icon: BriefcaseBusiness },
  { id: "candidates" as const, title: "Candidates", icon: Users },
  { id: "pipeline" as const, title: "Hiring pipeline", icon: Workflow },
  { id: "analytics" as const, title: "Analytics", icon: ChartNoAxesCombined },
];
function currentPage(): Page {
  const page = window.location.pathname.split("/")[1];
  return ["jobs", "candidates", "pipeline", "analytics", "settings"].includes(
    page,
  )
    ? (page as Page)
    : "overview";
}
function App() {
  return window.location.pathname.startsWith("/invite/") ? (
    <InvitationPage token={window.location.pathname.slice(8)} />
  ) : (
    <WorkspaceApp />
  );
}

function WorkspaceApp() {
  const [data, setData] = useState<Workspace>(EMPTY);
  const [user, setUser] = useState<User | null>(null);
  const [config, setConfig] = useState<Config>({});
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [page, setPage] = useState<Page>(currentPage);
  const [modal, setModal] = useState<ModalState>(null);
  const [selected, setSelected] = useState<Application | null>(null);
  const [toast, setToast] = useState<{
    message: string;
    error: boolean;
  } | null>(null);
  const [mobile, setMobile] = useState(false);
  const [search, setSearch] = useState("");
  const [notifications, setNotifications] = useState(false);

  const [help, setHelp] = useState(false);
  const [routeQuery, setRouteQuery] = useState(window.location.search);
  const requestVersion = useRef(0);
  const contentRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const activityRef = useRef<HTMLDivElement>(null);
  const sidebarRef = useRef<HTMLElement>(null);
  const menuRef = useRef<HTMLButtonElement>(null);
  useEntrance(contentRef, page + String(loading), ":scope > *");

  const refresh = useCallback(async () => {
    const version = ++requestVersion.current;
    const token = tokenStore.get();
    try {
      const isAuthenticated = !!tokenStore.get();
      const [snapshot, me, settings] = await Promise.all([
        api<Workspace>(isAuthenticated ? "/workspace" : "/demo"),
        isAuthenticated ? api<User>("/auth/me") : Promise.resolve(null),
        api<Config>("/config"),
      ]);
      if (version !== requestVersion.current || token !== tokenStore.get())
        return;
      setData({ ...EMPTY, ...snapshot });
      setUser(me);
      setConfig(settings);
      setError("");
    } catch (e) {
      if (version === requestVersion.current && token === tokenStore.get())
        setError((e as Error).message);
    } finally {
      if (version === requestVersion.current) setLoading(false);
    }
  }, []);
  useEffect(() => {
    void refresh();
    const unauthorized = () => {
      setUser(null);
      setData(EMPTY);
      setSelected(null);
      setModal(null);
      setLoading(true);
      void refresh();
    };
    const pop = () => {
      setPage(currentPage());
      setRouteQuery(window.location.search);
      setSearch("");
      setSelected(null);
    };
    window.addEventListener("hireline:unauthorized", unauthorized);
    window.addEventListener("popstate", pop);
    return () => {
      window.removeEventListener("hireline:unauthorized", unauthorized);
      window.removeEventListener("popstate", pop);
    };
  }, [refresh]);
  useEffect(() => {
    function shortcut(e: KeyboardEvent) {
      if (
        (e.metaKey || e.ctrlKey) &&
        e.key.toLowerCase() === "k" &&
        !document.querySelector('[role="dialog"]')
      ) {
        e.preventDefault();
        searchRef.current?.focus();
      }
      if (e.key === "Escape") {
        setMobile(false);
        setNotifications(false);
      }
    }
    const outside = (e: MouseEvent) => {
      if (!activityRef.current?.contains(e.target as Node))
        setNotifications(false);
    };
    window.addEventListener("keydown", shortcut);
    document.addEventListener("mousedown", outside);
    return () => {
      window.removeEventListener("keydown", shortcut);
      document.removeEventListener("mousedown", outside);
    };
  }, []);
  useEffect(() => {
    document.title = label(page) + " · Hireline";
  }, [page]);
  useEffect(() => {
    if (!mobile) return;
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    sidebarRef.current
      ?.querySelector<HTMLElement>('[aria-current="page"]')
      ?.focus();
    function trap(e: KeyboardEvent) {
      if (e.key !== "Tab") return;
      const controls = [
        ...(sidebarRef.current?.querySelectorAll<HTMLElement>("a, button") ??
          []),
      ];
      const first = controls[0];
      const last = controls.at(-1);
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last?.focus();
      }
      if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first?.focus();
      }
    }
    const viewport = window.matchMedia("(min-width: 721px)");
    const resize = () => {
      if (viewport.matches) setMobile(false);
    };
    window.addEventListener("keydown", trap);
    viewport.addEventListener("change", resize);
    return () => {
      document.body.style.overflow = overflow;
      window.removeEventListener("keydown", trap);
      viewport.removeEventListener("change", resize);
      menuRef.current?.focus();
    };
  }, [mobile]);
  const activeTasks = data.tasks.filter((t) =>
    ["pending", "queued", "running", "retrying"].includes(t.status),
  );
  useEffect(() => {
    if (!user) return;
    const timer = window.setInterval(
      () => {
        if (document.visibilityState === "visible") void refresh();
      },
      activeTasks.length ? 3500 : 30000,
    );
    return () => clearInterval(timer);
  }, [user, activeTasks.length, refresh]);
  useEffect(() => {
    const onFocus = () => {
      if (tokenStore.get() && document.visibilityState === "visible")
        void refresh();
    };
    window.addEventListener("focus", onFocus);
    document.addEventListener("visibilitychange", onFocus);
    return () => {
      window.removeEventListener("focus", onFocus);
      document.removeEventListener("visibilitychange", onFocus);
    };
  }, [refresh]);
  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(null), 6500);
    return () => clearTimeout(timer);
  }, [toast]);
  const notify = useCallback(
    (message: string, isError = false) => setToast({ message, error: isError }),
    [],
  );
  function navigate(next: Page, jobId?: string) {
    const query = jobId ? "?job=" + encodeURIComponent(jobId) : "";
    setPage(next);
    setRouteQuery(query);
    setSelected(null);
    setMobile(false);
    setNotifications(false);
    setSearch("");
    window.history.pushState(
      {},
      "",
      (next === "overview" ? "/" : "/" + next) + query,
    );
    window.scrollTo(0, 0);
  }
  const close = useCallback(() => setModal(null), []);
  async function command(action: () => Promise<unknown>, success: string) {
    setBusy(true);
    try {
      await action();
      notify(success);
      await refresh();
    } catch (e) {
      notify((e as Error).message, true);
    } finally {
      setBusy(false);
    }
  }
  function exportSnapshot() {
    const headers = ["Candidate", "Job", "Stage", "Evidence match"];
    const rows = data.applications.map((app) => {
      const c = data.candidates.find((x) => x.id === app.candidate_id);
      const j = data.jobs.find((x) => x.id === app.job_id);
      const screen = data.screenings
        .filter((x) => x.application_id === app.id)
        .sort((a, b) =>
          (b.created_at ?? "").localeCompare(a.created_at ?? ""),
        )[0];
      return [
        c?.name ?? "",
        j?.title ?? "",
        app.stage,
        screeningScore(screen)?.toString() ?? "",
      ];
    });
    const csv = [headers, ...rows]
      .map((row) => row.map(csvCell).join(","))
      .join("\r\n");
    const url = URL.createObjectURL(
      new Blob([csv], { type: "text/csv;charset=utf-8" }),
    );
    const a = document.createElement("a");
    a.href = url;
    a.download = "hireline-pipeline.csv";
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    notify("Pipeline report exported.");
  }
  const routeTitle = [
    ...NAV,
    { id: "settings", title: "Workspace settings" },
  ].find((n) => n.id === page)?.title;
  const displayName = user?.name?.split(" ")[0] ?? "there";
  return (
    <Context.Provider
      value={{
        data,
        user,
        config,
        busy,
        refresh,
        open: setModal,
        close,
        notify,
        navigate,
        select: setSelected,
        command,
      }}
    >
      <a className="skip-link" href="#main-content">
        Skip to content
      </a>
      {mobile && (
        <button
          className="sidebar-scrim"
          onClick={() => setMobile(false)}
          aria-label="Close navigation"
        />
      )}
      <aside
        ref={sidebarRef}
        id="workspace-navigation"
        className={`sidebar ${mobile ? "sidebar-open" : ""}`}
      >
        <a
          className="brand"
          href="/"
          onClick={(e) => {
            e.preventDefault();
            navigate("overview");
          }}
        >
          <span className="brand-mark">
            h<span />
          </span>
          <span>
            hireline<span className="brand-period">.</span>
          </span>
        </a>
        <div className="workspace-identity">
          <span className="workspace-avatar">H</span>
          <div>
            <strong>Hiring workspace</strong>
            <small>
              {user ? label(user.role) + " access" : "Portfolio demo"}
            </small>
          </div>
        </div>
        <nav aria-label="Main navigation">
          {NAV.map((item) => (
            <button
              key={item.id}
              aria-label={item.title}
              className={`nav-item ${page === item.id ? "nav-active" : ""}`}
              onClick={() => navigate(item.id)}
              aria-current={page === item.id ? "page" : undefined}
            >
              <item.icon size={19} strokeWidth={1.7} />
              <span>{item.title}</span>
              {item.id === "candidates" && (
                <span className="nav-count">{data.candidates.length}</span>
              )}
              {item.id === "overview" && <span className="nav-active-dot" />}
            </button>
          ))}
        </nav>
        <div className="sidebar-context">
          <span className="status-dot" />
          <span>
            {config.ai_mode === "gemini"
              ? "Gemini screening"
              : "Demo screening"}
            <small>
              {config.external_mode === "live"
                ? "Live test integrations"
                : "Email & calendar previews"}
            </small>
          </span>
        </div>
        <div className="sidebar-bottom">
          <button
            className={`nav-item ${page === "settings" ? "nav-active" : ""}`}
            onClick={() => navigate("settings")}
          >
            <Settings2 size={19} strokeWidth={1.7} />
            Settings
          </button>
          <button
            className="nav-item"
            onClick={() => {
              setMobile(false);
              setHelp(true);
            }}
          >
            <CircleHelp size={19} />
            Workspace guide
            <ArrowUpRight size={14} />
          </button>
          <div className="sidebar-profile">
            <Avatar name={user?.name ?? "Demo Visitor"} index={3} />
            <div>
              <strong>{user?.name ?? "Demo workspace"}</strong>
              <small>{user ? label(user.role) : "Read-only visitor"}</small>
            </div>
            <button
              className="sidebar-logout"
              aria-label={user ? "Sign out" : "Sign in"}
              onClick={() => {
                if (user) {
                  tokenStore.clear();
                  setUser(null);
                  setData(EMPTY);
                  setSelected(null);
                  setModal(null);
                  setLoading(true);
                  void refresh();
                  notify("Signed out. You are viewing the public demo.");
                } else setModal({ kind: "login" });
              }}
            >
              {user ? <LogOut size={17} /> : <LogIn size={17} />}
            </button>
          </div>
        </div>
      </aside>
      <div className="workspace-main" inert={mobile}>
        <header className="topbar">
          <div className="topbar-title">
            <button
              className="icon-button menu-toggle"
              ref={menuRef}
              aria-controls="workspace-navigation"
              aria-expanded={mobile}
              aria-label="Open navigation"
              onClick={() => setMobile(true)}
            >
              <Menu size={21} />
            </button>
            <span className="breadcrumb">Workspace</span>
            <span className="breadcrumb-slash">/</span>
            <strong>{routeTitle}</strong>
          </div>
          <div className="topbar-actions" ref={activityRef}>
            <div className="global-search">
              <Search size={16} />
              <input
                ref={searchRef}
                aria-label="Search candidates"
                placeholder="Find a candidate"
                value={search}
                onChange={(e) => {
                  if (page !== "candidates") navigate("candidates");
                  setSearch(e.target.value);
                }}
              />
              <kbd>
                <Command size={10} />K
              </kbd>
            </div>
            <button
              className="icon-button notification-button"
              aria-label="Recent activity"
              aria-expanded={notifications}
              onClick={() => setNotifications(!notifications)}
            >
              <Bell size={19} />
            </button>
            <Avatar name={user?.name ?? "Demo Visitor"} index={3} />
            {notifications && (
              <div className="notification-popover">
                <strong>Recent activity</strong>
                {data.activities.slice(0, 5).map((a, i) => (
                  <p key={a.id ?? i}>
                    {a.message ?? label(a.action ?? "Workspace updated")}
                  </p>
                ))}
                {!data.activities.length && (
                  <p>Your workspace is up to date.</p>
                )}
                <button
                  className="text-link"
                  onClick={() => {
                    setNotifications(false);
                    navigate("overview");
                  }}
                >
                  View workspace
                  <ArrowUpRight size={13} />
                </button>
              </div>
            )}
          </div>
        </header>
        {!user && (
          <div className="demo-banner">
            <span>
              <ShieldCheck size={15} />
              <strong>Demo workspace</strong>
              <span className="demo-banner-extra">
                {" "}
                Browse fictional candidates and sample hiring decisions.
              </span>
            </span>
            <button onClick={() => setModal({ kind: "login" })}>
              Staff sign in
              <ArrowUpRight size={14} />
            </button>
          </div>
        )}
        <main id="main-content" className="main-content" tabIndex={-1}>
          <div className="page-heading">
            <div>
              <div className="eyebrow">
                {page === "overview"
                  ? "TODAY AT HIRELINE"
                  : "HIRING WORKSPACE"}
              </div>
              <h1>
                {page === "overview"
                  ? `Good ${new Date().getHours() < 12 ? "morning" : new Date().getHours() < 17 ? "afternoon" : "evening"}, ${displayName}`
                  : routeTitle}
                <span className="heading-period">.</span>
              </h1>
              <p>
                {page === "overview"
                  ? "Review pending screenings and follow your open roles."
                  : page === "jobs"
                    ? "Roles, requirements, and recruiter-approved rubrics."
                    : page === "candidates"
                      ? "Search candidates, compare evidence, and review applications."
                      : page === "pipeline"
                        ? "Every application, from first review to final decision."
                        : page === "analytics"
                          ? "Recorded outcomes and the time spent reaching them."
                          : "Staff access, provider connections, and processing history."}
              </p>
            </div>
            <div className="page-heading-actions">
              <Button
                variant="secondary"
                disabled={loading || !!error}
                onClick={exportSnapshot}
              >
                <ArrowDownToLine size={15} />
                Export report
              </Button>
              {canManage(user) && (
                <Button
                  onClick={() =>
                    setModal({ kind: page === "candidates" ? "upload" : "job" })
                  }
                >
                  <Plus size={17} />
                  {page === "candidates" ? "Add candidates" : "Create a job"}
                </Button>
              )}
            </div>
          </div>
          {error && (
            <div className="error-banner" role="alert">
              <span>{error}</span>
              <Button
                variant="secondary"
                onClick={() => {
                  setLoading(true);
                  void refresh();
                }}
              >
                <RefreshCw size={14} />
                Retry connection
              </Button>
            </div>
          )}
          {activeTasks.length > 0 && (
            <div className="processing-banner">
              <RefreshCw size={15} className="spin" />
              Processing {activeTasks.length}{" "}
              {activeTasks.length === 1 ? "task" : "tasks"} · Progress updates
              automatically while you’re here.
            </div>
          )}
          <div ref={contentRef} className="page-content">
            {loading ? (
              <Spinner />
            ) : page === "overview" ? (
              <OverviewPage />
            ) : page === "jobs" ? (
              <JobsPage />
            ) : page === "candidates" ? (
              <CandidatesPage
                key={routeQuery}
                search={search}
                setSearch={setSearch}
              />
            ) : page === "pipeline" ? (
              <PipelinePage />
            ) : page === "analytics" ? (
              <AnalyticsPage />
            ) : (
              <SettingsPage />
            )}
          </div>
          <footer className="workspace-footer">
            <span>
              <span className="status-dot" />
              {config.ai_mode === "gemini"
                ? "Gemini screening mode"
                : "Synthetic demo · deterministic screening"}
            </span>
            <span>hireline.</span>
          </footer>
        </main>
      </div>
      {selected && (
        <CandidatePanel
          application={
            data.applications.find((a) => a.id === selected.id) ?? selected
          }
          onClose={() => setSelected(null)}
        />
      )}
      {modal && <ModalHost state={modal} />}
      {help && (
        <Modal title="Workspace guide" onClose={() => setHelp(false)}>
          <div className="guide-content">
            <h3>From a role to a recorded decision</h3>
            <ol>
              <li>Create a job and approve the screening criteria.</li>
              <li>Import up to ten synthetic PDF or DOCX resumes.</li>
              <li>
                Open a candidate, check the source evidence, and review the
                screening.
              </li>
              <li>
                Create an assessment and copy the private invitation link.
              </li>
              <li>
                Review responses, schedule an interview, and record feedback.
              </li>
              <li>Update the application stage with a decision note.</li>
            </ol>
            <div className="form-notice">
              <ShieldCheck size={18} />
              <p>
                Demo screening uses deterministic matching. Preview email and
                calendar actions are simulated. Live providers require
                configuration.
              </p>
            </div>
            <Button
              variant="secondary"
              onClick={() => {
                setHelp(false);
                navigate("settings");
              }}
            >
              Open settings
              <ArrowUpRight size={15} />
            </Button>
          </div>
        </Modal>
      )}
      {toast && (
        <div
          role={toast.error ? "alert" : "status"}
          className={`toast ${toast.error ? "toast-error" : ""}`}
        >
          <span>{toast.message}</span>
          <button
            aria-label="Dismiss notification"
            onClick={() => setToast(null)}
          >
            <X size={16} />
          </button>
        </div>
      )}
    </Context.Provider>
  );
}

export default App;
