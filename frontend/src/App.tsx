import { useCallback, useEffect, useState } from 'react';
import { ArrowDownToLine, ArrowUpRight, Bell, BriefcaseBusiness, ChartNoAxesCombined, ChevronDown, CircleHelp, Command, LayoutDashboard, LogIn, LogOut, Menu, PanelLeftClose, Plus, RefreshCw, Search, Settings2, ShieldCheck, Sparkles, Users, Workflow, X } from 'lucide-react';
import { api, tokenStore } from './api';
import { Context, canManage } from './context';
import type { ModalState, Page } from './context';
import type { Application, Config, User, Workspace } from './types';
import { Avatar, Button, Spinner, label } from './ui';
import { AnalyticsPage, CandidatesPage, JobsPage, OverviewPage, PipelinePage, SettingsPage } from './pages';
import { ModalHost } from './forms';
import { CandidatePanel } from './CandidatePanel';
import { InvitationPage } from './InvitationPage';

const EMPTY: Workspace = { jobs: [], candidates: [], applications: [], screenings: [], assessments: [], interviews: [], feedback: [], activities: [], tasks: [], metrics: {} };
const NAV = [
  { id: 'overview' as const, title: 'Overview', icon: LayoutDashboard },
  { id: 'jobs' as const, title: 'Job openings', icon: BriefcaseBusiness },
  { id: 'candidates' as const, title: 'Candidates', icon: Users },
  { id: 'pipeline' as const, title: 'Hiring pipeline', icon: Workflow },
  { id: 'analytics' as const, title: 'Analytics', icon: ChartNoAxesCombined },
];
function currentPage(): Page { const page = window.location.pathname.split('/')[1]; return ['jobs', 'candidates', 'pipeline', 'analytics', 'settings'].includes(page) ? page as Page : 'overview'; }
function App() { return window.location.pathname.startsWith('/invite/') ? <InvitationPage token={window.location.pathname.slice(8)} /> : <WorkspaceApp />; }

function WorkspaceApp() {
  const [data, setData] = useState<Workspace>(EMPTY);
  const [user, setUser] = useState<User | null>(null);
  const [config, setConfig] = useState<Config>({});
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [page, setPage] = useState<Page>(currentPage);
  const [modal, setModal] = useState<ModalState>(null);
  const [selected, setSelected] = useState<Application | null>(null);
  const [toast, setToast] = useState<{ message: string; error: boolean } | null>(null);
  const [mobile, setMobile] = useState(false);
  const [search, setSearch] = useState('');
  const [notifications, setNotifications] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const isAuthenticated = !!tokenStore.get();
      const [snapshot, me] = await Promise.all([
        api<Workspace>(isAuthenticated ? '/workspace' : '/demo'),
        isAuthenticated ? api<User>('/auth/me') : Promise.resolve(null),
      ]);
      setData({ ...EMPTY, ...snapshot }); setUser(me); setError('');
    } catch (e) { setError((e as Error).message); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => {
    void refresh();
    api<Config>('/config').then(setConfig).catch(() => {});
    const unauthorized = () => { setUser(null); void refresh(); };
    const pop = () => { setPage(currentPage()); setSelected(null); };
    window.addEventListener('hireline:unauthorized', unauthorized); window.addEventListener('popstate', pop);
    return () => { window.removeEventListener('hireline:unauthorized', unauthorized); window.removeEventListener('popstate', pop); };
  }, [refresh]);
  const activeTasks = data.tasks.filter(t => ['pending', 'queued', 'running', 'retrying'].includes(t.status));
  useEffect(() => {
    if (!user) return;
    const timer = window.setInterval(() => { if (document.visibilityState === 'visible') void refresh(); }, activeTasks.length ? 3500 : 30000);
    return () => clearInterval(timer);
  }, [user, activeTasks.length, refresh]);
  useEffect(() => {
    const onFocus = () => { if (tokenStore.get() && document.visibilityState === 'visible') void refresh(); };
    window.addEventListener('focus', onFocus);
    document.addEventListener('visibilitychange', onFocus);
    return () => { window.removeEventListener('focus', onFocus); document.removeEventListener('visibilitychange', onFocus); };
  }, [refresh]);
  useEffect(() => { if (!toast) return; const timer = setTimeout(() => setToast(null), 6500); return () => clearTimeout(timer); }, [toast]);
  const notify = useCallback((message: string, isError = false) => setToast({ message, error: isError }), []);
  function navigate(next: Page) { setPage(next); setSelected(null); setMobile(false); setSearch(''); window.history.pushState({}, '', next === 'overview' ? '/' : `/${next}`); window.scrollTo(0, 0); }
  const close = useCallback(() => setModal(null), []);
  async function command(action: () => Promise<unknown>, success: string) {
    setBusy(true);
    try { await action(); notify(success); await refresh(); }
    catch (e) { notify((e as Error).message, true); }
    finally { setBusy(false); }
  }
  function exportSnapshot() {
    const headers = ['Candidate', 'Job', 'Stage', 'Evidence match'];
    const rows = data.applications.map(app => { const c = data.candidates.find(x => x.id === app.candidate_id); const j = data.jobs.find(x => x.id === app.job_id); const screen = data.screenings.filter(x => x.application_id === app.id).sort((a, b) => (b.created_at ?? '').localeCompare(a.created_at ?? ''))[0]; return [c?.name ?? '', j?.title ?? '', app.stage, screen?.score?.toString() ?? '']; });
    const csv = [headers, ...rows].map(row => row.map(x => `"${x.replaceAll('"', '""')}"`).join(',')).join('\r\n');
    const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
    const a = document.createElement('a'); a.href = url; a.download = 'hireline-pipeline.csv'; a.click(); URL.revokeObjectURL(url);
    notify('Pipeline report exported.');
  }
  const routeTitle = [...NAV, { id: 'settings', title: 'Workspace settings' }].find(n => n.id === page)?.title;
  const displayName = user?.name?.split(' ')[0] ?? 'there';
  return <Context.Provider value={{ data, user, config, busy, refresh, open: setModal, close, notify, navigate, select: setSelected, command }}>
    <a className="skip-link" href="#main-content">Skip to content</a>
    {mobile && <button className="sidebar-scrim" onClick={() => setMobile(false)} aria-label="Close navigation" />}
    <aside className={`sidebar ${mobile ? 'sidebar-open' : ''}`}>
      <a className="brand" href="/" onClick={e => { e.preventDefault(); navigate('overview'); }}><span className="brand-mark">h<span /></span><span>hireline<span className="brand-period">.</span></span></a>
      <button className="workspace-switch" onClick={() => navigate('settings')}><span className="workspace-avatar">W</span><span><strong>My workspace</strong><small>Recruiting studio</small></span><ChevronDown size={15} /></button>
      <div className="nav-label">WORKSPACE</div>
      <nav aria-label="Main navigation">{NAV.map(item => <button key={item.id} className={`nav-item ${page === item.id ? 'nav-active' : ''}`} onClick={() => navigate(item.id)} aria-current={page === item.id ? 'page' : undefined}><item.icon size={19} strokeWidth={1.7} /><span>{item.title}</span>{item.id === 'candidates' && <span className="nav-count">{data.candidates.length}</span>}{item.id === 'overview' && <span className="nav-active-dot" />}</button>)}</nav>
      <div className="sidebar-insight"><span className="insight-icon"><Sparkles size={18} /></span><h3>A little less busywork.<br />A lot more possibility.</h3><p>Thoughtful hiring, backed by evidence.</p><button onClick={() => navigate('analytics')}>Explore your insights<ArrowUpRight size={15} /></button></div>
      <div className="sidebar-bottom"><button className={`nav-item ${page === 'settings' ? 'nav-active' : ''}`} onClick={() => navigate('settings')}><Settings2 size={19} strokeWidth={1.7} />Settings</button><a className="nav-item" href="https://github.com/topics/recruitment" target="_blank" rel="noreferrer" onClick={e => { e.preventDefault(); notify('Need a hand? Setup, API, and integration guides are included in the project README.'); }}><CircleHelp size={19} strokeWidth={1.7} />Help & resources<ArrowUpRight size={14} /></a><div className="sidebar-profile"><Avatar name={user?.name ?? 'Demo Visitor'} index={3} /><div><strong>{user?.name ?? 'Demo workspace'}</strong><small>{user ? label(user.role) : 'Read-only visitor'}</small></div><button className="sidebar-logout" aria-label={user ? 'Sign out' : 'Sign in'} onClick={() => { if (user) { tokenStore.clear(); void refresh(); notify('Signed out. You are viewing the public demo.'); } else setModal({ kind: 'login' }); }}>{user ? <LogOut size={17} /> : <LogIn size={17} />}</button></div></div>
    </aside>
    <div className="workspace-main">
      <header className="topbar"><div className="topbar-title"><button className="icon-button menu-toggle" aria-label="Open navigation" onClick={() => setMobile(true)}><Menu size={21} /></button><PanelLeftClose size={18} className="desktop-only muted" /><span className="breadcrumb">Workspace</span><span className="breadcrumb-slash">/</span><strong>{routeTitle}</strong></div><div className="topbar-actions"><div className="global-search"><Search size={16} /><input aria-label="Search candidates" placeholder="Search anything…" value={search} onChange={e => { setSearch(e.target.value); if (page !== 'candidates') setPage('candidates'); }} /><kbd><Command size={10} />K</kbd></div><button className="icon-button notification-button" aria-label="Recent activity" aria-expanded={notifications} onClick={() => setNotifications(!notifications)}><Bell size={19} /><span /></button><Avatar name={user?.name ?? 'Demo Visitor'} index={3} />{notifications && <div className="notification-popover"><strong>Recent activity</strong>{data.activities.slice(0, 5).map((a, i) => <p key={a.id ?? i}>{a.message ?? label(a.action ?? 'Workspace updated')}</p>)}{!data.activities.length && <p>Your workspace is up to date.</p>}<button className="text-link" onClick={() => { setNotifications(false); navigate('overview'); }}>View workspace<ArrowUpRight size={13} /></button></div>}</div></header>
      {!user && <div className="demo-banner"><span><ShieldCheck size={15} /><strong>A real workflow. Fictional candidates.</strong><span className="demo-banner-extra"> Explore this read-only portfolio demo.</span></span><button onClick={() => setModal({ kind: 'login' })}>Staff sign in<ArrowUpRight size={14} /></button></div>}
      <main id="main-content" className="main-content">
        <div className="page-heading"><div><div className="eyebrow">YOUR RECRUITING WORKSPACE</div><h1>{page === 'overview' ? `Good ${new Date().getHours() < 12 ? 'morning' : new Date().getHours() < 17 ? 'afternoon' : 'evening'}, ${displayName}` : routeTitle}<span className="heading-period">.</span></h1><p>{page === 'overview' ? 'Great teams start with thoughtful decisions. Here’s where you stand.' : page === 'jobs' ? 'The right opportunities. The right people. All in one place.' : page === 'candidates' ? 'Look beyond the resume. See the evidence behind every match.' : page === 'pipeline' ? 'A clear view of every candidate’s next step.' : page === 'analytics' ? 'Understand your hiring journey, one useful insight at a time.' : 'Keep your people, connections, and preferences in sync.'}</p></div><div className="page-heading-actions"><Button variant="secondary" onClick={exportSnapshot}><ArrowDownToLine size={15} />Export report</Button>{canManage(user) && <Button onClick={() => setModal({ kind: page === 'candidates' ? 'upload' : 'job' })}><Plus size={17} />{page === 'candidates' ? 'Add candidates' : 'Create a job'}</Button>}</div></div>
        {error && <div className="error-banner" role="alert"><span>{error}</span><Button variant="secondary" onClick={() => { setLoading(true); void refresh(); }}><RefreshCw size={14} />Retry connection</Button></div>}
        {activeTasks.length > 0 && <div className="processing-banner"><RefreshCw size={15} className="spin" />Processing {activeTasks.length} {activeTasks.length === 1 ? 'task' : 'tasks'} · Progress updates automatically while you’re here.</div>}
        {loading ? <Spinner /> : page === 'overview' ? <OverviewPage /> : page === 'jobs' ? <JobsPage /> : page === 'candidates' ? <CandidatesPage search={search} setSearch={setSearch} /> : page === 'pipeline' ? <PipelinePage /> : page === 'analytics' ? <AnalyticsPage /> : <SettingsPage />}
        <footer className="workspace-footer"><span><span className="status-dot" />{config.ai_mode === 'gemini' ? 'Gemini screening mode' : 'Synthetic demo · deterministic screening'}</span><span>Built for people. Grounded in evidence.</span></footer>
      </main>
    </div>
    {selected && <CandidatePanel application={data.applications.find(a => a.id === selected.id) ?? selected} onClose={() => setSelected(null)} />}
    {modal && <ModalHost state={modal} />}
    {toast && <div role={toast.error ? 'alert' : 'status'} className={`toast ${toast.error ? 'toast-error' : ''}`}><span>{toast.message}</span><button aria-label="Dismiss notification" onClick={() => setToast(null)}><X size={16} /></button></div>}
  </Context.Provider>;
}

export default App;
