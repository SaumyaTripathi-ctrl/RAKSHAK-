// Public, login-free provenance page behind the crate QR code. Mobile-first; English/Hindi.
import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, Globe2, MapPin, ShieldAlert, ShieldCheck, ShieldQuestion } from "lucide-react";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { useParams } from "react-router-dom";

import { ShipmentMap } from "@/components/ShipmentMap";
import { ErrorState, LoadingBlock } from "@/components/States";
import { TrendChart } from "@/components/TrendChart";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { get } from "@/lib/api";
import { fmt, formatDateTime, humanFood } from "@/lib/format";
import { LANGUAGES, setLanguage, type LangCode } from "@/lib/i18n";
import { usePublicDoc } from "@/lib/queries";
import { STAGES } from "@/lib/types";
import { ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";

function Hero({ verified, status, coverage, note }: { verified: boolean | null; status?: string; coverage?: number; note?: string | null }) {
  const { t } = useTranslation();
  const tampered = status === "TAMPERED";
  const Icon = tampered ? ShieldAlert : verified ? ShieldCheck : ShieldQuestion;
  const tone = tampered
    ? "border-red-600/60 bg-red-50 text-red-900 dark:bg-red-950/40 dark:text-red-100"
    : verified
      ? "border-green-600/60 bg-green-50 text-green-900 dark:bg-green-950/40 dark:text-green-100"
      : "border-border bg-muted text-foreground";
  return (
    <div className={cn("flex items-start gap-4 rounded-xl border-2 p-4 sm:p-6", tone)} data-testid="trust-hero" data-verified={String(!!verified)} data-status={status ?? "NONE"}>
      <Icon className="size-12 shrink-0 sm:size-14" aria-hidden />
      <div className="min-w-0">
        <h2 className="text-xl font-bold sm:text-2xl">
          {tampered ? t("public.tampered") : verified ? t("public.verified") : t("public.notVerified")}
        </h2>
        <p className="mt-1 text-sm">{tampered ? t("public.tamperedHint") : verified ? t("public.verifiedHint") : t("public.notVerifiedHint")}</p>
        {verified && coverage !== undefined && coverage < 1 && <p className="mt-1 text-xs opacity-80">{t("public.coverage", { pct: Math.round(coverage * 100) })}</p>}
        {note && <p className="mt-1 text-xs opacity-80">{note}</p>}
      </div>
    </div>
  );
}

export default function PublicQr() {
  const { id = "" } = useParams();
  const { t, i18n } = useTranslation();
  const q = usePublicDoc(id);
  const health = useQuery({ queryKey: ["health"], queryFn: () => get<{ dev_secrets: boolean }>("/health"), retry: false });

  const route = useMemo(() => (q.data?.route ?? []).map((p, i) => ({ t: i, lat: p.lat, lon: p.lon })), [q.data?.route]);
  const series = useMemo(() => {
    const c = q.data?.chart ?? [];
    return {
      temp: [{ key: "t", label: t("cards.temperature"), color: "#1F4E79", points: c.map((p) => ({ t: p.t, v: p.temp_c })) }],
      eth: [{ key: "e", label: t("cards.ethylene"), color: "#E87A1E", points: c.map((p) => ({ t: p.t, v: p.ethylene_idx })) }],
    };
  }, [q.data?.chart, t]);

  return (
    <div className="min-h-screen bg-background">
      <header className="sticky top-0 z-20 flex items-center justify-between gap-2 border-b bg-background/95 px-4 py-2.5 backdrop-blur">
        <div className="flex items-center gap-2 font-bold">
          <img src="/logo.svg" alt="" className="size-8" />
          <span>{t("app.name")}</span>
        </div>
        <div className="flex items-center gap-1 rounded-md border px-1.5">
          <Globe2 className="size-4 text-muted-foreground" aria-hidden />
          <label className="sr-only" htmlFor="plang">{t("common.language")}</label>
          <select id="plang" value={i18n.language} onChange={(e) => setLanguage(e.target.value as LangCode)} className="h-8 bg-transparent text-sm">
            {LANGUAGES.map((l) => (
              <option key={l.code} value={l.code}>{l.label}</option>
            ))}
          </select>
        </div>
      </header>

      <main className="mx-auto max-w-3xl space-y-4 px-4 py-4 pb-16">
        {q.isPending ? (
          <LoadingBlock rows={4} />
        ) : q.isError ? (
          q.error instanceof ApiError && q.error.status === 404 ? (
            <ErrorState error={new Error(t("public.notFound", { id }))} />
          ) : (
            <ErrorState error={q.error} onRetry={() => void q.refetch()} />
          )
        ) : (
          <>
            <Hero verified={q.data.ledger.verified} status={q.data.ledger.status} coverage={q.data.ledger.coverage} note={q.data.ledger.note} />

            <Card>
              <CardHeader>
                <CardTitle className="flex flex-wrap items-center gap-2 text-xl">
                  {t(`foods.${q.data.food_type}`, { defaultValue: humanFood(q.data.food_type) })}
                  {q.data.variety && <span className="text-base font-normal text-muted-foreground">· {q.data.variety}</span>}
                </CardTitle>
                <p className="text-sm text-muted-foreground">
                  {t("public.shipmentId")}: <span className="font-mono">{q.data.shipment_id}</span>
                </p>
              </CardHeader>
              <CardContent className="grid grid-cols-2 gap-3 text-sm">
                <div>
                  <p className="text-xs text-muted-foreground">{t("shipment.origin")}</p>
                  <p className="font-medium">{q.data.origin.name || "-"}</p>
                </div>
                <div>
                  <p className="text-xs text-muted-foreground">{t("shipment.destination")}</p>
                  <p className="font-medium">{q.data.destination.name || "-"}</p>
                </div>
                <div>
                  <p className="text-xs text-muted-foreground">{t("shipment.weight")}</p>
                  <p className="font-medium">{q.data.weight_kg} kg</p>
                </div>
                <div>
                  <p className="text-xs text-muted-foreground">{t("common.status")}</p>
                  <p className="font-medium">{t(`status.${q.data.status}`, { defaultValue: q.data.status })}</p>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>{t("public.journey")}</CardTitle>
              </CardHeader>
              <CardContent>
                {q.data.journey.length === 0 ? (
                  <p className="text-sm text-muted-foreground">{t("custody.none")}</p>
                ) : (
                  <ol className="relative ml-2 space-y-4 border-l pl-5" aria-label={t("public.journey")}>
                    {q.data.journey.map((j, i) => (
                      <li key={i} className="relative">
                        <span className="absolute -left-[27px] top-0.5 flex size-4 items-center justify-center rounded-full bg-green-600 text-white" aria-hidden>
                          <CheckCircle2 className="size-3" />
                        </span>
                        <p className="font-semibold">{t(`stages.${j.stage}`)}</p>
                        <p className="text-sm">{j.organisation || t(`roles.${j.role}`, { defaultValue: j.role })}</p>
                        <p className="text-xs text-muted-foreground">
                          {j.location && <><MapPin className="mr-0.5 inline size-3" aria-hidden />{j.location} · </>}
                          {formatDateTime(j.at)}
                          {j.anchored && <> · <span className="text-green-700 dark:text-green-400">{t("custody.anchored")}</span></>}
                        </p>
                      </li>
                    ))}
                  </ol>
                )}
                <p className="mt-3 text-xs text-muted-foreground">
                  {t("public.stagesOrder")}: {STAGES.map((s) => t(`stages.${s}`)).join(" → ")}
                </p>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>{t("public.conditions")}</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <dl className="grid grid-cols-3 gap-2 text-center">
                  {[
                    [t("public.min"), fmt(q.data.summary.temp_min_c, 1, " °C")],
                    [t("public.avg"), fmt(q.data.summary.temp_avg_c, 1, " °C")],
                    [t("public.max"), fmt(q.data.summary.temp_max_c, 1, " °C")],
                  ].map(([k, v]) => (
                    <div key={k} className="rounded-lg bg-muted p-2">
                      <dt className="text-xs text-muted-foreground">{k}</dt>
                      <dd className="text-lg font-bold tabular-nums">{v}</dd>
                    </div>
                  ))}
                </dl>
                <div>
                  <p className="mb-1 text-sm font-medium">{t("cards.temperature")}</p>
                  <TrendChart series={series.temp} offline={q.data.offline_segments} unit="°" height={200} />
                </div>
                <div>
                  <p className="mb-1 text-sm font-medium">{t("cards.ethylene")}</p>
                  <TrendChart series={series.eth} offline={q.data.offline_segments} unit="%" height={180} yDomain={[0, 100]} />
                </div>
                {q.data.offline_segments.length > 0 && <p className="text-xs text-muted-foreground">{t("public.offlineNote")}</p>}
                <div className="flex flex-wrap gap-2 text-sm">
                  <Badge variant="muted">{t("public.records", { count: q.data.summary.records })}</Badge>
                  {Object.entries(q.data.summary.alerts).length === 0 ? (
                    <Badge variant="safe">{t("public.noAlerts")}</Badge>
                  ) : (
                    Object.entries(q.data.summary.alerts).map(([k, n]) => (
                      <Badge key={k} variant={k.startsWith("TAMPER") ? "crit" : "warn"}>
                        {t(`events.kind.${k}`, { defaultValue: k })} ×{n}
                      </Badge>
                    ))
                  )}
                </div>
              </CardContent>
            </Card>

            {route.length > 1 && (
              <Card>
                <CardHeader>
                  <CardTitle>{t("public.route")}</CardTitle>
                </CardHeader>
                <CardContent>
                  <ShipmentMap
                    resetKey={q.data.shipment_id}
                    height={260}
                    trucks={[]}
                    trail={route}
                    origin={q.data.origin.lat != null && q.data.origin.lon != null ? [q.data.origin.lat, q.data.origin.lon] : null}
                    dest={q.data.destination.lat != null && q.data.destination.lon != null ? [q.data.destination.lat, q.data.destination.lon] : null}
                  />
                </CardContent>
              </Card>
            )}

            <p className="text-center text-xs text-muted-foreground">
              {t("public.poweredBy")} · SIH26232
              {health.data?.dev_secrets && <><br />{t("public.demoNote")}</>}
            </p>
          </>
        )}
      </main>
    </div>
  );
}
