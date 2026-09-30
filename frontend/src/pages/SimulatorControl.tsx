import { Flame, Pause, Play, Power, Radio, Square, Wifi, WifiOff, Wind, Zap } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { EmptyState, ErrorState, LoadingBlock, SimulatedBadge } from "@/components/States";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input, Label } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/misc";
import { formatDuration } from "@/lib/format";
import { useSimControl, useSimInject, useSimScenarios, useSimStart, useSimState } from "@/lib/queries";
import type { SimRun, SimScenario } from "@/lib/types";

const HUBS = ["HUB-0001", "HUB-0002", "HUB-0003"];

export default function SimulatorControl() {
  const { t } = useTranslation();
  const scenarios = useSimScenarios();
  const state = useSimState();

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-2xl font-bold tracking-tight">{t("sim.title")}</h1>
        <SimulatedBadge />
      </div>
      <p className="max-w-3xl text-sm text-muted-foreground">{t("sim.intro")}</p>

      {scenarios.isError ? (
        <ErrorState error={scenarios.error} onRetry={() => void scenarios.refetch()} />
      ) : scenarios.isPending ? (
        <LoadingBlock rows={2} />
      ) : (
        <StartPanel scenarios={scenarios.data.scenarios} />
      )}

      <section aria-label={t("sim.runs")} className="space-y-4">
        <h2 className="text-lg font-semibold">{t("sim.runs")}</h2>
        {state.isPending ? (
          <LoadingBlock rows={2} />
        ) : state.isError ? (
          <ErrorState error={state.error} onRetry={() => void state.refetch()} />
        ) : state.data.runs.length === 0 ? (
          <EmptyState title={t("sim.noRuns")} hint={t("sim.noRunsHint")} />
        ) : (
          state.data.runs
            .slice()
            .sort((a, b) => Number(b.state === "running") - Number(a.state === "running"))
            .map((r) => <RunCard key={r.id} run={r} />)
        )}
      </section>
    </div>
  );
}

function StartPanel({ scenarios }: { scenarios: SimScenario[] }) {
  const { t } = useTranslation();
  const start = useSimStart();
  const [name, setName] = useState(scenarios[0]?.name ?? "");
  const [hub, setHub] = useState(HUBS[0]);
  const [profile, setProfile] = useState("demo");
  const [accel, setAccel] = useState("");
  const [fresh, setFresh] = useState(true);
  const sc = scenarios.find((s) => s.name === name);
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("sim.start")}</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-4 lg:grid-cols-3">
        <div className="space-y-3 lg:col-span-2">
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="grid gap-1.5">
              <Label htmlFor="sc">{t("sim.scenario")}</Label>
              <NativeSelect id="sc" value={name} onChange={(e) => setName(e.target.value)}>
                {scenarios.map((s) => (
                  <option key={s.name} value={s.name}>
                    {s.title}
                  </option>
                ))}
              </NativeSelect>
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="shub">{t("shipment.hub")}</Label>
              <NativeSelect id="shub" value={hub} onChange={(e) => setHub(e.target.value)}>
                {HUBS.map((h) => (
                  <option key={h}>{h}</option>
                ))}
              </NativeSelect>
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="sprof">{t("shipment.profile")}</Label>
              <NativeSelect id="sprof" value={profile} onChange={(e) => setProfile(e.target.value)}>
                <option value="demo">{t("shipment.profileDemo")}</option>
                <option value="real">{t("shipment.profileReal")}</option>
              </NativeSelect>
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="sacc">{t("sim.speed")}</Label>
              <Input id="sacc" inputMode="decimal" placeholder={sc ? String(sc.accel) : "60"} value={accel} onChange={(e) => setAccel(e.target.value)} />
            </div>
          </div>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={fresh} onChange={(e) => setFresh(e.target.checked)} />
            {t("sim.newShipment")}
          </label>
          <Button
            disabled={start.isPending || !name}
            onClick={() =>
              start.mutate({ scenario: name, hub_id: hub, profile, accel: accel ? Number(accel) : undefined, new_shipment: fresh })
            }
          >
            <Play /> {t("sim.startRun")}
          </Button>
          {start.isError && <p role="alert" className="text-sm text-destructive">{start.error.message}</p>}
        </div>
        {sc && (
          <div className="space-y-2 rounded-md bg-muted p-3 text-sm">
            <p>{sc.description}</p>
            <p className="text-xs text-muted-foreground">
              {t("sim.duration", { time: formatDuration(sc.duration_min / 60) })} · {sc.food_type}
            </p>
            <ol className="space-y-0.5 text-xs">
              {sc.steps.map((st, i) => (
                <li key={i}>
                  <span className="tabular-nums text-muted-foreground">T+{st.at}m</span> {st.action}
                </li>
              ))}
            </ol>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

const STATE_VARIANT = { running: "safe", paused: "warn", finished: "muted", stopped: "muted", error: "crit", created: "muted" } as const;

function RunCard({ run }: { run: SimRun }) {
  const { t } = useTranslation();
  const inject = useSimInject();
  const control = useSimControl();
  const [tagId, setTagId] = useState(run.tag_ids[0] ?? "");
  const live = run.state === "running" || run.state === "paused";
  const snap = run.snapshot;
  const pct = Math.min(100, (snap.elapsed_min / run.duration_min) * 100);
  const go = (action: string, params: Record<string, unknown> = {}) => inject.mutate({ run: run.id, action, params });

  return (
    <Card data-testid={`run-${run.id}`}>
      <CardHeader className="gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <CardTitle>{run.title}</CardTitle>
          <Badge variant={STATE_VARIANT[run.state]}>{t(`sim.state.${run.state}`)}</Badge>
          <SimulatedBadge />
          <Link to={`/shipments/${run.shipment_id}`} className="text-sm font-medium text-secondary underline-offset-2 hover:underline">
            {run.shipment_id}
          </Link>
          <span className="text-sm text-muted-foreground">
            {run.hub_id} · {run.food_type} · {t(`shipment.profile_${run.profile}`)} · ×{run.accel}
          </span>
          {live && (
            <span className="ml-auto flex gap-1">
              {run.state === "running" ? (
                <Button size="sm" variant="outline" onClick={() => control.mutate({ run: run.id, op: "pause" })}>
                  <Pause /> {t("sim.pause")}
                </Button>
              ) : (
                <Button size="sm" variant="outline" onClick={() => control.mutate({ run: run.id, op: "resume" })}>
                  <Play /> {t("sim.resume")}
                </Button>
              )}
              <Button size="sm" variant="destructive" onClick={() => control.mutate({ run: run.id, op: "stop" })}>
                <Square /> {t("sim.stop")}
              </Button>
            </span>
          )}
        </div>
        <div className="h-2 overflow-hidden rounded-full bg-muted" role="progressbar" aria-valuenow={Math.round(pct)} aria-valuemin={0} aria-valuemax={100}>
          <div className="h-full bg-secondary transition-all" style={{ width: `${pct}%` }} />
        </div>
        {run.error && <p role="alert" className="text-sm text-destructive">{run.error}</p>}
      </CardHeader>
      <CardContent className="space-y-4">
        <dl className="grid grid-cols-2 gap-2 text-sm sm:grid-cols-4 lg:grid-cols-8">
          {[
            [t("cards.temperature"), `${snap.temperature.toFixed(1)} °C`],
            [t("cards.ethylene"), `${snap.ethylene_index.toFixed(0)} %`],
            [t("cards.flap"), `${snap.flap} %`],
            [t("cards.fan"), snap.fan ? t("common.on") : t("common.off")],
            [t("cards.battery"), `${snap.battery} %`],
            [t("sim.led"), snap.led + (snap.buzzer_latched ? " 🔔" : "")],
            [t("cards.backlog", { count: snap.backlog }), ""],
            [t("sim.elapsed"), formatDuration(snap.elapsed_min / 60)],
          ].map(([k, v]) => (
            <div key={k}>
              <dt className="text-xs text-muted-foreground">{k}</dt>
              <dd className="font-semibold tabular-nums">{v}</dd>
            </div>
          ))}
        </dl>
        <div className="flex items-center gap-2 text-sm">
          {snap.connected ? (
            <Badge variant="safe"><Wifi className="size-3.5" /> {t("sync.online")}</Badge>
          ) : (
            <Badge variant="warn"><WifiOff className="size-3.5" /> {t("sync.offline")}</Badge>
          )}
          {snap.truth_risk !== null && <span className="text-xs text-muted-foreground">{t("sim.truth", { risk: snap.truth_risk })}</span>}
        </div>

        {live && (
          <fieldset className="space-y-3" disabled={inject.isPending}>
            <legend className="mb-1 text-sm font-semibold">{t("sim.inject")}</legend>
            <div className="flex flex-wrap gap-2">
              <Button size="sm" variant="outline" onClick={() => go("heat", { extra_c: 12 })}><Flame /> {t("sim.heat")}</Button>
              <Button size="sm" variant="ghost" onClick={() => go("heat", { extra_c: 0 })}>{t("sim.heatOff")}</Button>
              <Button size="sm" variant="outline" onClick={() => go("ethylene", { units_per_h: 35 })}><Wind /> {t("sim.ethylene")}</Button>
              <Button size="sm" variant="ghost" onClick={() => go("ethylene", { units_per_h: 0 })}>{t("sim.ethyleneOff")}</Button>
              <Button size="sm" variant="outline" onClick={() => go("shock", { g: 2.4 })}><Zap /> {t("sim.shock")}</Button>
              <Button size="sm" variant="outline" onClick={() => go("network_cut")}><WifiOff /> {t("sim.networkCut")}</Button>
              <Button size="sm" variant="outline" onClick={() => go("network_restore")}><Wifi /> {t("sim.networkRestore")}</Button>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <NativeSelect aria-label={t("tags.tag")} className="h-8 w-auto" value={tagId} onChange={(e) => setTagId(e.target.value)}>
                {run.tag_ids.map((x) => <option key={x}>{x}</option>)}
              </NativeSelect>
              <Button size="sm" variant="outline" onClick={() => go("lid_open", { tag_id: tagId })}>{t("sim.lidOpen")}</Button>
              <Button size="sm" variant="outline" onClick={() => go("reboot_tag", { tag_id: tagId })}>{t("sim.rebootTag")}</Button>
              <Button size="sm" variant="outline" onClick={() => go("ble_drop", { tag_id: tagId })}><Radio /> {t("sim.bleDrop")}</Button>
              <Button size="sm" variant="ghost" onClick={() => go("ble_restore", { tag_id: tagId })}>{t("sim.bleRestore")}</Button>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button size="sm" variant="outline" onClick={() => go("tamper_forge", { device_id: tagId })}>{t("sim.tamperForge")}</Button>
              <Button size="sm" variant="outline" onClick={() => go("tamper_delete", { device_id: tagId })}>{t("sim.tamperDelete")}</Button>
              <Button size="sm" variant="outline" onClick={() => go("anchor")}>{t("verify.anchorNow")}</Button>
              <Button size="sm" variant="outline" onClick={() => go("tamper_db", { kind: "edit_value" })}>{t("sim.tamperDb")}</Button>
              <Button size="sm" variant="accent" onClick={() => go("follow_reroute")}><Power /> {t("sim.followReroute")}</Button>
            </div>
            {inject.isError && <p role="alert" className="text-sm text-destructive">{inject.error.message}</p>}
          </fieldset>
        )}

        <details className="text-sm">
          <summary className="cursor-pointer font-medium">{t("sim.deviceLog")}</summary>
          <ul className="mt-2 max-h-56 space-y-0.5 overflow-auto rounded-md bg-muted p-2 font-mono text-xs">
            {run.log.length === 0 ? <li>-</li> : run.log.slice().reverse().map((l, i) => <li key={i}>{l}</li>)}
          </ul>
          {run.pending_steps.length > 0 && (
            <p className="mt-2 text-xs text-muted-foreground">
              {t("sim.pending")}: {run.pending_steps.slice(0, 6).map((s) => `T+${s.at}m ${s.action}`).join(" · ")}
            </p>
          )}
        </details>
      </CardContent>
    </Card>
  );
}
