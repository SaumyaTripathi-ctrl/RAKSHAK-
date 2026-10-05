import { useQuery } from "@tanstack/react-query";
import { LogIn } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Navigate, useLocation, useNavigate } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input, Label } from "@/components/ui/input";
import { get } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { LANGUAGES, setLanguage, type LangCode } from "@/lib/i18n";

const DEMO = ["admin", "fpo", "driver", "exporter"] as const;

export default function Login() {
  const { t, i18n } = useTranslation();
  const { user, login } = useAuth();
  const nav = useNavigate();
  const loc = useLocation();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // Demo accounts are only advertised when the backend reports it runs with dev secrets.
  const health = useQuery({ queryKey: ["health"], queryFn: () => get<{ dev_secrets: boolean }>("/health"), retry: false });

  if (user) return <Navigate to={(loc.state as { from?: string } | null)?.from ?? "/"} replace />;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(username.trim(), password);
      nav((loc.state as { from?: string } | null)?.from ?? "/", { replace: true });
    } catch (err) {
      setError(err instanceof Error && err.message !== "Unauthorized" ? err.message : t("login.invalid"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-gradient-to-br from-secondary/15 via-background to-primary/10 p-4">
      <Card className="w-full max-w-md">
        <CardHeader className="items-center text-center">
          <img src="/logo.svg" alt="" className="size-16" />
          <CardTitle className="text-2xl">{t("app.name")}</CardTitle>
          <CardDescription>{t("login.subtitle")}</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={submit} className="grid gap-4" noValidate>
            <div className="grid gap-1.5">
              <Label htmlFor="username">{t("login.username")}</Label>
              <Input id="username" autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} required autoFocus />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="password">{t("login.password")}</Label>
              <Input id="password" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
            </div>
            {error && (
              <p role="alert" className="text-sm text-destructive">
                {error}
              </p>
            )}
            <Button type="submit" disabled={busy || !username || !password}>
              <LogIn /> {t("login.signIn")}
            </Button>
          </form>
          {health.data?.dev_secrets && (
            <div className="mt-5 rounded-md border border-dashed p-3 text-sm">
              <p className="mb-2 font-medium">{t("login.demoAccounts")}</p>
              <div className="flex flex-wrap gap-2">
                {DEMO.map((u) => (
                  <Button
                    key={u}
                    type="button"
                    size="sm"
                    variant="outline"
                    onClick={() => {
                      setUsername(u);
                      setPassword(`${u}123`);
                    }}
                  >
                    {t(`roles.${u}`)}
                  </Button>
                ))}
              </div>
              <ul className="mt-3 space-y-1 text-xs text-muted-foreground">
                {DEMO.map((u) => (
                  <li key={u}>
                    <span className="font-semibold text-foreground">{t(`roles.${u}`)}</span> ({u}): {t(`roleHelp.${u}.short`)} · {t("roleHelp.cannot")}: {t(`roleHelp.${u}.cannot`)}
                  </li>
                ))}
              </ul>
              <p className="mt-2 text-xs text-muted-foreground">{t("login.demoHint")}</p>
            </div>
          )}
          <div className="mt-5 flex justify-center gap-2">
            {LANGUAGES.map((l) => (
              <Button key={l.code} type="button" size="sm" variant={i18n.language === l.code ? "secondary" : "ghost"} onClick={() => setLanguage(l.code as LangCode)}>
                {l.label}
              </Button>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
