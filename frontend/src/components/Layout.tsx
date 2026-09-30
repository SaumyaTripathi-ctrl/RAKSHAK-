import {
  Activity,
  AlertOctagon,
  Boxes,
  Cpu,
  FlaskConical,
  Globe2,
  LayoutDashboard,
  LogOut,
  Menu,
  Moon,
  Route,
  ShieldCheck,
  Sun,
  Truck,
} from "lucide-react";
import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Link, NavLink, Outlet, useNavigate } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { useAuth } from "@/lib/auth";
import { LANGUAGES, setLanguage, type LangCode } from "@/lib/i18n";
import { useLiveSocket } from "@/lib/live";
import { useTheme } from "@/lib/theme";
import type { Role } from "@/lib/types";
import { cn } from "@/lib/utils";

interface NavItem {
  to: string;
  key: string;
  icon: typeof Truck;
  roles?: Role[];
  end?: boolean;
}
const NAV: NavItem[] = [
  { to: "/", key: "nav.fleet", icon: LayoutDashboard, end: true },
  { to: "/shipments", key: "nav.shipments", icon: Boxes },
  { to: "/alerts", key: "nav.alerts", icon: AlertOctagon },
  { to: "/custody", key: "nav.custody", icon: Route },
  { to: "/verify", key: "nav.verify", icon: ShieldCheck },
  { to: "/devices", key: "nav.devices", icon: Cpu, roles: ["admin", "fpo"] },
  { to: "/simulator", key: "nav.simulator", icon: FlaskConical, roles: ["admin"] },
];

function Logo() {
  const { t } = useTranslation();
  return (
    <Link to="/" className="flex items-center gap-2 font-bold tracking-tight" aria-label={t("app.name")}>
      <img src="/logo.svg" alt="" className="size-8" />
      <span className="text-lg">{t("app.name")}</span>
    </Link>
  );
}

function NavLinks({ onNavigate }: { onNavigate?: () => void }) {
  const { t } = useTranslation();
  const { user } = useAuth();
  return (
    <nav className="flex flex-col gap-1" aria-label="Main">
      {NAV.filter((n) => !n.roles || (user && n.roles.includes(user.role))).map((n) => (
        <NavLink
          key={n.to}
          to={n.to}
          end={n.end}
          onClick={onNavigate}
          className={({ isActive }) =>
            cn(
              "flex items-center gap-3 rounded-md px-3 py-2.5 text-sm font-medium transition-colors hover:bg-muted",
              isActive && "bg-secondary text-secondary-foreground hover:bg-secondary",
            )
          }
        >
          <n.icon className="size-4" aria-hidden />
          {t(n.key)}
        </NavLink>
      ))}
    </nav>
  );
}

function Controls() {
  const { i18n, t } = useTranslation();
  const { theme, resolved, setTheme } = useTheme();
  return (
    <div className="flex items-center gap-1">
      <label className="sr-only" htmlFor="lang">
        {t("common.language")}
      </label>
      <div className="flex items-center gap-1 rounded-md border px-1.5">
        <Globe2 className="size-4 text-muted-foreground" aria-hidden />
        <select
          id="lang"
          value={i18n.language}
          onChange={(e) => setLanguage(e.target.value as LangCode)}
          className="h-8 bg-transparent text-sm"
        >
          {LANGUAGES.map((l) => (
            <option key={l.code} value={l.code}>
              {l.label}
            </option>
          ))}
        </select>
      </div>
      <Button
        variant="ghost"
        size="icon"
        aria-label={t("common.theme")}
        title={t("common.theme")}
        onClick={() => setTheme(theme === "system" ? (resolved === "dark" ? "light" : "dark") : theme === "dark" ? "light" : "dark")}
      >
        {resolved === "dark" ? <Sun /> : <Moon />}
      </Button>
    </div>
  );
}

export function Layout({ children }: { children?: ReactNode }) {
  const { t } = useTranslation();
  const { user, logout } = useAuth();
  const nav = useNavigate();
  const [open, setOpen] = useState(false);
  const socket = useLiveSocket(); // one socket for everything; the cache layer fans updates out to every view

  return (
    <div className="flex min-h-screen flex-col md:flex-row">
      <aside className="hidden w-60 shrink-0 flex-col gap-6 border-r bg-card p-4 md:flex">
        <Logo />
        <NavLinks />
        <p className="mt-auto text-xs text-muted-foreground">{t("app.tagline")}</p>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex items-center gap-2 border-b bg-background/95 px-3 py-2 backdrop-blur sm:px-5">
          <Button variant="ghost" size="icon" className="md:hidden" aria-label="Menu" onClick={() => setOpen(true)}>
            <Menu />
          </Button>
          <div className="md:hidden">
            <Logo />
          </div>
          <div className="ml-auto flex items-center gap-2">
            <span
              className="flex items-center gap-1.5 text-xs text-muted-foreground"
              title={t(`common.socket.${socket}`)}
              data-socket={socket}
            >
              <Activity className={cn("size-4", socket === "open" ? "text-green-600" : "text-orange-500")} aria-hidden />
              <span className="hidden sm:inline">{t(`common.socket.${socket}`)}</span>
            </span>
            <Controls />
            {user && (
              <div className="flex items-center gap-2">
                <div className="hidden text-right text-xs leading-tight lg:block">
                  <div className="font-medium">{user.full_name || user.username}</div>
                  <div className="text-muted-foreground">{t(`roles.${user.role}`)}</div>
                </div>
                <Button
                  variant="outline"
                  size="icon"
                  aria-label={t("common.logout")}
                  title={t("common.logout")}
                  onClick={() => {
                    logout();
                    nav("/login");
                  }}
                >
                  <LogOut />
                </Button>
              </div>
            )}
          </div>
        </header>

        <main className="container flex-1 space-y-5 py-5 pb-24" id="main">
          {children ?? <Outlet />}
        </main>
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="left-0 top-0 h-full max-w-xs translate-x-0 translate-y-0 rounded-none">
          <DialogTitle className="sr-only">Menu</DialogTitle>
          <Logo />
          <NavLinks onNavigate={() => setOpen(false)} />
        </DialogContent>
      </Dialog>
    </div>
  );
}
