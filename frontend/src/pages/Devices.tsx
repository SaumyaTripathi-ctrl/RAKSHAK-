import { KeyRound, Link2, Plus, RotateCw } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { SyncBadge } from "@/components/badges";
import { EmptyState, ErrorState, LoadingBlock } from "@/components/States";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Input, Label } from "@/components/ui/input";
import { NativeSelect, TBody, TD, TH, THead, TR, Table } from "@/components/ui/misc";
import { useAuth } from "@/lib/auth";
import { timeAgo } from "@/lib/format";
import { useBind, useCreateDevice, useDevices, useRotateKey, useShipments } from "@/lib/queries";
import type { DeviceRow } from "@/lib/types";

function Battery({ pct }: { pct: number | null }) {
  if (pct === null) return <span className="text-muted-foreground">-</span>;
  const tone = pct < 20 ? "bg-red-600" : pct < 40 ? "bg-orange-500" : "bg-green-600";
  return (
    <div className="flex items-center gap-2" title={`${pct}%`}>
      <div className="h-2 w-16 overflow-hidden rounded-full bg-muted" role="meter" aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct}>
        <div className={`h-full ${tone}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs tabular-nums">{pct}%</span>
    </div>
  );
}

export default function Devices() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const devices = useDevices();
  const hubs = (devices.data ?? []).filter((d) => d.kind === "hub");
  const tags = (devices.data ?? []).filter((d) => d.kind === "tag");

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-2xl font-bold tracking-tight">{t("devices.title")}</h1>
        {can("admin") && <NewDeviceDialog hubs={hubs} />}
      </div>
      {devices.isPending ? (
        <LoadingBlock />
      ) : devices.isError ? (
        <ErrorState error={devices.error} onRetry={() => void devices.refetch()} />
      ) : (
        <>
          <DeviceTable title={t("devices.hubs")} rows={hubs} />
          <DeviceTable title={t("devices.tags")} rows={tags} />
        </>
      )}
    </div>
  );
}

function DeviceTable({ title, rows }: { title: string; rows: DeviceRow[] }) {
  const { t } = useTranslation();
  const { can } = useAuth();
  const rotate = useRotateKey();
  const [shown, setShown] = useState<{ id: string; epoch: number; key: string } | null>(null);
  return (
    <Card>
      <CardHeader>
        <CardTitle>
          {title} <Badge variant="muted">{rows.length}</Badge>
        </CardTitle>
      </CardHeader>
      <CardContent>
        {rows.length === 0 ? (
          <EmptyState title={t("devices.none")} />
        ) : (
          <Table>
            <THead>
              <TR>
                <TH>ID</TH>
                <TH>{t("common.status")}</TH>
                <TH>{t("cards.battery")}</TH>
                <TH>{t("devices.lastSeen")}</TH>
                <TH>{t("devices.firmware")}</TH>
                <TH>{t("devices.shipment")}</TH>
                <TH>{t("devices.keyEpoch")}</TH>
                <TH>
                  <span className="sr-only">{t("common.actions")}</span>
                </TH>
              </TR>
            </THead>
            <TBody>
              {rows.map((d) => (
                <TR key={d.id}>
                  <TD className="font-medium">
                    {d.id}
                    {d.hub_id && <span className="ml-1 text-xs text-muted-foreground">↔ {d.hub_id}</span>}
                  </TD>
                  <TD>
                    {d.kind === "hub" ? (
                      <SyncBadge online={d.last_seen_at ? d.online : null} backlog={d.backlog} offlineSince={d.offline_since} compact />
                    ) : (
                      <Badge variant={d.last_seen_at ? "safe" : "muted"}>{d.last_seen_at ? t("sync.online") : t("devices.neverSeen")}</Badge>
                    )}
                  </TD>
                  <TD>
                    <Battery pct={d.battery_pct} />
                  </TD>
                  <TD className="whitespace-nowrap text-muted-foreground">{timeAgo(d.last_seen_at)}</TD>
                  <TD className="text-muted-foreground">{d.firmware_version || "-"}</TD>
                  <TD>{d.shipment_id ?? "-"}</TD>
                  <TD className="tabular-nums">{d.key_epoch}</TD>
                  <TD className="space-x-1 whitespace-nowrap text-right">
                    {can("admin", "fpo") && d.kind === "tag" && <PairDialog device={d} />}
                    {can("admin") && (
                      <Button
                        size="sm"
                        variant="ghost"
                        title={t("devices.rotate")}
                        disabled={rotate.isPending}
                        onClick={() => rotate.mutate(d.id, { onSuccess: (r) => setShown({ id: d.id, epoch: r.key_epoch, key: r.device_key_hex }) })}
                      >
                        <RotateCw />
                        <span className="sr-only">{t("devices.rotate")}</span>
                      </Button>
                    )}
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>
        )}
        <KeyDialog shown={shown} onClose={() => setShown(null)} />
      </CardContent>
    </Card>
  );
}

function KeyDialog({ shown, onClose }: { shown: { id: string; epoch: number; key: string } | null; onClose: () => void }) {
  const { t } = useTranslation();
  return (
    <Dialog open={!!shown} onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <KeyRound className="size-5" aria-hidden /> {t("devices.provisioning")}
          </DialogTitle>
          <DialogDescription>{t("devices.provisioningHint")}</DialogDescription>
        </DialogHeader>
        {shown && (
          <dl className="grid gap-2 text-sm">
            <div>
              <dt className="text-muted-foreground">{t("devices.device")}</dt>
              <dd className="font-medium">{shown.id}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">key_epoch</dt>
              <dd className="tabular-nums">{shown.epoch}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">{t("devices.key")}</dt>
              <dd className="break-all rounded-md bg-muted p-2 font-mono text-xs" data-testid="device-key">
                {shown.key}
              </dd>
            </div>
          </dl>
        )}
        <DialogFooter>
          <Button onClick={onClose}>{t("common.close")}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function NewDeviceDialog({ hubs }: { hubs: DeviceRow[] }) {
  const { t } = useTranslation();
  const create = useCreateDevice();
  const [open, setOpen] = useState(false);
  const [id, setId] = useState("");
  const [kind, setKind] = useState<"hub" | "tag">("tag");
  const [hub, setHub] = useState("");
  const [shown, setShown] = useState<{ id: string; epoch: number; key: string } | null>(null);
  const valid = /^[A-Za-z0-9_-]{1,16}$/.test(id);
  const submit = (e: FormEvent) => {
    e.preventDefault();
    create.mutate(
      { id, kind, hub_id: kind === "tag" && hub ? hub : null },
      {
        onSuccess: (r) => {
          setOpen(false);
          setShown({ id, epoch: r.key_epoch, key: r.device_key_hex });
          setId("");
        },
      },
    );
  };
  return (
    <>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogTrigger asChild>
          <Button>
            <Plus /> {t("devices.add")}
          </Button>
        </DialogTrigger>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("devices.add")}</DialogTitle>
            <DialogDescription>{t("devices.addHint")}</DialogDescription>
          </DialogHeader>
          <form onSubmit={submit} className="grid gap-3">
            <div className="grid gap-1.5">
              <Label htmlFor="did">ID</Label>
              <Input id="did" value={id} onChange={(e) => setId(e.target.value)} placeholder="TAG-0010" maxLength={16} />
              {id && !valid && <p className="text-xs text-destructive">{t("devices.idInvalid")}</p>}
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="dkind">{t("devices.kind")}</Label>
              <NativeSelect id="dkind" value={kind} onChange={(e) => setKind(e.target.value as "hub" | "tag")}>
                <option value="tag">{t("devices.tag")}</option>
                <option value="hub">{t("devices.hub")}</option>
              </NativeSelect>
            </div>
            {kind === "tag" && (
              <div className="grid gap-1.5">
                <Label htmlFor="dhub">{t("shipment.hub")}</Label>
                <NativeSelect id="dhub" value={hub} onChange={(e) => setHub(e.target.value)}>
                  <option value="">{t("common.none")}</option>
                  {hubs.map((h) => (
                    <option key={h.id} value={h.id}>
                      {h.id}
                    </option>
                  ))}
                </NativeSelect>
              </div>
            )}
            {create.isError && <p role="alert" className="text-sm text-destructive">{create.error.message}</p>}
            <DialogFooter>
              <Button type="submit" disabled={!valid || create.isPending}>
                {t("common.create")}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
      <KeyDialog shown={shown} onClose={() => setShown(null)} />
    </>
  );
}

function PairDialog({ device }: { device: DeviceRow }) {
  const { t } = useTranslation();
  const shipments = useShipments();
  const [open, setOpen] = useState(false);
  const [sid, setSid] = useState("");
  const bind = useBind(sid || "none");
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size="sm" variant="ghost" title={t("devices.pair")}>
          <Link2 />
          <span className="sr-only">{t("devices.pair")}</span>
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("devices.pairTitle", { id: device.id })}</DialogTitle>
          <DialogDescription>{t("devices.pairHint")}</DialogDescription>
        </DialogHeader>
        <NativeSelect aria-label={t("nav.shipments")} value={sid} onChange={(e) => setSid(e.target.value)}>
          <option value="">{t("common.choose")}</option>
          {(shipments.data ?? []).map((s) => (
            <option key={s.id} value={s.id}>
              {s.id}
            </option>
          ))}
        </NativeSelect>
        {bind.isError && <p role="alert" className="text-sm text-destructive">{bind.error.message}</p>}
        <DialogFooter>
          <Button disabled={!sid || bind.isPending} onClick={() => bind.mutate({ tag_ids: [device.id] }, { onSuccess: () => setOpen(false) })}>
            {t("devices.pair")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
