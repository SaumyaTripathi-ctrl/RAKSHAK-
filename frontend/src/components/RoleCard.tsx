import { ShieldCheck } from "lucide-react";
import { useTranslation } from "react-i18next";

import { useAuth } from "@/lib/auth";
import { cn } from "@/lib/utils";

const TONE: Record<string, string> = {
  admin: "border-red-500/50 bg-red-500/10",
  fpo: "border-green-600/50 bg-green-600/10",
  driver: "border-orange-500/50 bg-orange-500/10",
  exporter: "border-blue-500/50 bg-blue-500/10",
};

/** Always-visible reminder of who you are signed in as and what that role may do (the roles differ in the details). */
export function RoleCard() {
  const { t } = useTranslation();
  const { user } = useAuth();
  if (!user) return null;
  return (
    <section className={cn("mt-4 rounded-md border p-3 text-xs leading-snug", TONE[user.role] ?? "")} aria-label={t("roleHelp.title")}>
      <div className="flex items-center gap-1.5 font-semibold">
        <ShieldCheck className="size-3.5" aria-hidden />
        {t(`roles.${user.role}`)}
      </div>
      <div className="text-muted-foreground">{t(`roleHelp.${user.role}.short`)}</div>
      <p className="mt-2">
        <span className="font-semibold">{t("roleHelp.can")}: </span>
        {t(`roleHelp.${user.role}.can`)}
      </p>
      <p className="mt-1.5">
        <span className="font-semibold">{t("roleHelp.cannot")}: </span>
        {t(`roleHelp.${user.role}.cannot`)}
      </p>
    </section>
  );
}
