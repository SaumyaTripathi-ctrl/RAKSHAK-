import { Anchor, Check, Link2, PenLine } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useParams } from "react-router-dom";

import { ShipmentPicker } from "@/components/ShipmentPicker";
import { EmptyState, ErrorState, LoadingBlock } from "@/components/States";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input, Label, Textarea } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/misc";
import { useAuth } from "@/lib/auth";
import { formatDateTime, shortHash } from "@/lib/format";
import { useCustody, useHandover, useShipments, useVerify } from "@/lib/queries";
import { STAGES, type Handover, type Role, type Stage } from "@/lib/types";
import { cn } from "@/lib/utils";

// Mirror of backend/rakshak/services/custody.py ROLE_STAGES (the server is the authority).
const ROLE_STAGES: Record<Role, Stage[]> = {
  admin: [...STAGES],
  fpo: ["FARM", "FPO", "PACKHOUSE", "COLD_STORAGE"],
  driver: ["TRANSPORT", "COLD_STORAGE"],
  exporter: ["COLD_STORAGE", "RETAIL"],
};

export default function Custody() {
  const { id } = useParams();
  const nav = useNavigate();
  const { t } = useTranslation();
  const list = useShipments();
  useEffect(() => {
    if (!id && list.data?.[0]) nav(`/custody/${list.data[0].id}`, { replace: true });
  }, [id, list.data, nav]);

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-2xl font-bold tracking-tight">{t("custody.title")}</h1>
        <ShipmentPicker value={id} onChange={(v) => nav(`/custody/${v}`)} />
      </div>
      {id ? <Timeline id={id} /> : <EmptyState title={t("alerts.pick")} />}
    </div>
  );
}

function Timeline({ id }: { id: string }) {
  const { t } = useTranslation();
  const custody = useCustody(id);
  const verify = useVerify(id);
  if (custody.isPending) return <LoadingBlock rows={3} />;
  if (custody.isError) return <ErrorState error={custody.error} onRetry={() => void custody.refetch()} />;

  const checks = new Map((verify.data?.handovers ?? []).map((h) => [h.id, h]));
  // Latest hand-over per stage; the journey shows where the shipment has been, in order.
  const events = custody.data;
  const reached = new Set(events.map((h) => h.stage));

  return (
    <div className="grid gap-5 xl:grid-cols-3">
      <Card className="xl:col-span-2">
        <CardHeader>
          <CardTitle>{t("custody.journey")}</CardTitle>
        </CardHeader>
        <CardContent>
          <ol className="flex items-center gap-1 overflow-x-auto pb-3" aria-label={t("custody.stages")}>
            {STAGES.map((st, i) => (
              <li key={st} className="flex items-center gap-1">
                <span
                  className={cn(
                    "flex items-center gap-1.5 whitespace-nowrap rounded-full border px-3 py-1.5 text-xs font-semibold",
                    reached.has(st) ? "border-green-600/50 bg-green-100 text-green-900 dark:bg-green-950 dark:text-green-200" : "text-muted-foreground",
                  )}
                  aria-current={events.at(-1)?.stage === st ? "step" : undefined}
                >
                  {reached.has(st) ? <Check className="size-3.5" aria-hidden /> : <span className="size-3.5 rounded-full border" aria-hidden />}
                  {t(`stages.${st}`)}
                </span>
                {i < STAGES.length - 1 && <span className="h-px w-4 bg-border" aria-hidden />}
              </li>
            ))}
          </ol>

          {events.length === 0 ? (
            <EmptyState title={t("custody.none")} hint={t("custody.noneHint")} />
          ) : (
            <ol className="relative ml-2 space-y-5 border-l pl-6" data-testid="handover-list">
              {events.map((h) => (
                <HandoverItem key={h.id} h={h} check={checks.get(h.id)} />
              ))}
            </ol>
          )}
        </CardContent>
      </Card>

      <HandoverForm id={id} />
    </div>
  );
}

function HandoverItem({ h, check }: { h: Handover; check?: { ok: boolean; problems: string[]; anchored: boolean } }) {
  const { t } = useTranslation();
  const bad = check && !check.ok;
  return (
    <li className="relative">
      <span className={cn("absolute -left-[31px] top-1 flex size-4 items-center justify-center rounded-full border-2 bg-background", bad ? "border-red-600" : "border-green-600")} aria-hidden />
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="secondary">{t(`stages.${h.stage}`)}</Badge>
        <span className="text-sm font-medium">{h.organisation || h.actor_name}</span>
        <span className="text-xs text-muted-foreground">
          {t(`roles.${h.actor_role}`)} · {formatDateTime(h.created_at)}
        </span>
        {h.ledger_ref && (
          <Badge variant={bad ? "crit" : "safe"}>
            <Anchor className="size-3" aria-hidden /> {bad ? t("custody.chainBroken") : t("custody.anchored")}
          </Badge>
        )}
      </div>
      {h.location && <p className="mt-0.5 text-sm">{h.location}</p>}
      {h.notes && <p className="text-sm text-muted-foreground">{h.notes}</p>}
      <dl className="mt-1.5 grid gap-x-4 gap-y-0.5 font-mono text-xs text-muted-foreground sm:grid-cols-2">
        <div className="flex items-center gap-1">
          <PenLine className="size-3" aria-hidden />
          <dt className="sr-only">{t("custody.signature")}</dt>
          <dd title={h.signature}>{t("custody.signedBy", { key: shortHash(h.public_key, 6) })}</dd>
        </div>
        <div className="flex items-center gap-1">
          <Link2 className="size-3" aria-hidden />
          <dt className="sr-only">{t("custody.chain")}</dt>
          <dd title={`${h.prev_hash} → ${h.payload_hash}`}>
            {shortHash(h.prev_hash, 6)} → {shortHash(h.payload_hash, 6)}
          </dd>
        </div>
        {h.ledger_ref && (
          <div className="sm:col-span-2">
            <dt className="sr-only">ledger</dt>
            <dd>{h.ledger_ref}</dd>
          </div>
        )}
      </dl>
      {bad && check?.problems.map((p, i) => <p key={i} className="mt-1 text-sm text-destructive" role="alert">{p}</p>)}
    </li>
  );
}

function HandoverForm({ id }: { id: string }) {
  const { t } = useTranslation();
  const { user } = useAuth();
  const handover = useHandover(id);
  const allowed = user ? ROLE_STAGES[user.role] : [];
  const [stage, setStage] = useState<Stage | "">("");
  const [location, setLocation] = useState("");
  const [notes, setNotes] = useState("");
  useEffect(() => {
    if (!stage && allowed.length) setStage(allowed[0]);
  }, [allowed, stage]);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!stage) return;
    handover.mutate({ stage, location, notes }, { onSuccess: () => { setLocation(""); setNotes(""); } });
  };

  return (
    <Card className="h-fit">
      <CardHeader>
        <CardTitle>{t("custody.record")}</CardTitle>
        <p className="text-sm text-muted-foreground">{t("custody.recordHint")}</p>
      </CardHeader>
      <CardContent>
        <form onSubmit={submit} className="grid gap-3">
          <div className="grid gap-1.5">
            <Label htmlFor="stage">{t("custody.stage")}</Label>
            <NativeSelect id="stage" value={stage} onChange={(e) => setStage(e.target.value as Stage)}>
              {allowed.map((s) => (
                <option key={s} value={s}>
                  {t(`stages.${s}`)}
                </option>
              ))}
            </NativeSelect>
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="loc">{t("custody.location")}</Label>
            <Input id="loc" value={location} onChange={(e) => setLocation(e.target.value)} />
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="notes">{t("custody.notes")}</Label>
            <Textarea id="notes" value={notes} onChange={(e) => setNotes(e.target.value)} maxLength={1000} />
          </div>
          <Button type="submit" disabled={handover.isPending || !stage}>
            <PenLine /> {t("custody.signAndRecord")}
          </Button>
          {handover.isError && <p role="alert" className="text-sm text-destructive">{handover.error.message}</p>}
          {handover.isSuccess && <p role="status" className="text-sm text-green-700 dark:text-green-400">{t("custody.recorded")}</p>}
        </form>
        <p className="mt-3 text-xs text-muted-foreground">{t("custody.signingNote")}</p>
      </CardContent>
    </Card>
  );
}
