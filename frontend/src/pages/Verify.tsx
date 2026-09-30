import { useQuery } from "@tanstack/react-query";
import { Anchor, FlaskConical, RefreshCw, RotateCcw, Search, ShieldAlert } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useParams } from "react-router-dom";

import { TrustBadge } from "@/components/badges";
import { ShipmentPicker } from "@/components/ShipmentPicker";
import { EmptyState, ErrorState, LoadingBlock } from "@/components/States";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input, Label } from "@/components/ui/input";
import { TBody, TD, TH, THead, TR, Table } from "@/components/ui/misc";
import { get } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatDateTime, shortHash } from "@/lib/format";
import { useAnchorNow, useDemoRestore, useDemoTamper, useLedgerEntries, useLedgerStatus, useShipments, useVerify } from "@/lib/queries";
import type { BatchCheck } from "@/lib/types";

export default function Verify() {
  const { id } = useParams();
  const nav = useNavigate();
  const { t } = useTranslation();
  const list = useShipments();
  useEffect(() => {
    if (!id && list.data?.[0]) nav(`/verify/${list.data[0].id}`, { replace: true });
  }, [id, list.data, nav]);

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-2xl font-bold tracking-tight">{t("verify.title")}</h1>
        <ShipmentPicker value={id} onChange={(v) => nav(`/verify/${v}`)} />
      </div>
      {id ? <Panel id={id} /> : <EmptyState title={t("alerts.pick")} />}
    </div>
  );
}

const STATUS_VARIANT = { verified: "safe", tampered: "crit", pending: "muted", ledger_unreachable: "warn" } as const;

function Panel({ id }: { id: string }) {
  const { t } = useTranslation();
  const { can } = useAuth();
  const v = useVerify(id);
  const ledger = useLedgerStatus();
  const entries = useLedgerEntries(id);
  const anchor = useAnchorNow(id);
  const demoStatus = useQuery({
    queryKey: ["demo-status"],
    queryFn: () => get<{ enabled: boolean }>("/api/demo/status"),
    enabled: can("admin"),
    retry: false,
  });
  const tamper = useDemoTamper();
  const restore = useDemoRestore();

  if (v.isPending) return <LoadingBlock rows={3} />;
  if (v.isError) return <ErrorState error={v.error} onRetry={() => void v.refetch()} />;
  const d = v.data;
  const problems = [
    ...d.batches.flatMap((b) => b.problems.map((p) => ({ where: `${t("verify.batch")} #${b.batch_id}`, text: p }))),
    ...d.handovers.flatMap((h) => h.problems.map((p) => ({ where: t(`stages.${h.stage}`), text: p }))),
    ...d.unanchored_problems.map((p) => ({ where: t("verify.unanchored"), text: p })),
    ...(d.ledger.integrity_ok ? [] : [{ where: t("verify.ledger"), text: d.ledger.problem }]),
  ];

  return (
    <div className="space-y-5">
      <Card className={d.tampered ? "border-red-600/60 bg-red-50 dark:bg-red-950/30" : d.verified ? "border-green-600/50" : ""}>
        <CardContent className="flex flex-wrap items-center gap-4 p-4 sm:p-5">
          <TrustBadge status={d.status} className="px-4 py-2 text-base" />
          <div className="min-w-0 flex-1 text-sm">
            <p>
              {t("verify.coverage", { anchored: d.anchored_records, total: d.total_records, pct: Math.round(d.coverage * 100) })}
            </p>
            <p className="text-muted-foreground">
              {d.unanchored_records > 0 ? t("verify.unanchoredHint", { count: d.unanchored_records }) : t("verify.allAnchored")} ·{" "}
              {t("verify.checkedAt", { time: formatDateTime(d.checked_at) })}
            </p>
            <p className="mt-1 text-xs text-muted-foreground">{t(`verify.explain.${d.status}`)}</p>
          </div>
          <div className="flex gap-2">
            <Button variant="outline" onClick={() => void v.refetch()} disabled={v.isFetching}>
              <RefreshCw className={v.isFetching ? "animate-spin" : ""} /> {t("verify.verifyNow")}
            </Button>
            {can("admin", "fpo") && (
              <Button variant="secondary" onClick={() => anchor.mutate()} disabled={anchor.isPending}>
                <Anchor /> {t("verify.anchorNow")}
              </Button>
            )}
          </div>
        </CardContent>
      </Card>

      {problems.length > 0 && (
        <Card className="border-red-600/50">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-red-700 dark:text-red-300">
              <ShieldAlert className="size-5" aria-hidden /> {t("verify.problems", { count: problems.length })}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="space-y-1.5 text-sm" role="alert">
              {problems.slice(0, 12).map((p, i) => (
                <li key={i} className="flex gap-2">
                  <Badge variant="crit">{p.where}</Badge>
                  <span>{p.text}</span>
                </li>
              ))}
            </ul>
            {problems.length > 12 && <p className="mt-2 text-xs text-muted-foreground">+{problems.length - 12}…</p>}
          </CardContent>
        </Card>
      )}

      <div className="grid gap-5 xl:grid-cols-3">
        <Card className="xl:col-span-2">
          <CardHeader>
            <CardTitle>{t("verify.batches")}</CardTitle>
            <p className="text-sm text-muted-foreground">{t("verify.batchesHint")}</p>
          </CardHeader>
          <CardContent>
            {d.batches.length === 0 ? (
              <EmptyState title={t("verify.noBatches")} hint={t("verify.noBatchesHint")} />
            ) : (
              <Table>
                <THead>
                  <TR>
                    <TH>#</TH>
                    <TH>{t("verify.device")}</TH>
                    <TH>{t("verify.seqRange")}</TH>
                    <TH>{t("verify.records")}</TH>
                    <TH>{t("verify.root")}</TH>
                    <TH>{t("common.status")}</TH>
                  </TR>
                </THead>
                <TBody>
                  {d.batches.map((b: BatchCheck) => (
                    <TR key={b.batch_id} data-status={b.status}>
                      <TD>{b.batch_id}</TD>
                      <TD>{b.device_id}</TD>
                      <TD className="tabular-nums">
                        {b.first_seq}–{b.last_seq}
                      </TD>
                      <TD className="tabular-nums">{b.leaf_count}</TD>
                      <TD className="font-mono text-xs" title={b.merkle_root}>
                        {shortHash(b.merkle_root, 10)}
                      </TD>
                      <TD>
                        <Badge variant={STATUS_VARIANT[b.status]}>{t(`verify.batchStatus.${b.status}`)}</Badge>
                      </TD>
                    </TR>
                  ))}
                </TBody>
              </Table>
            )}
          </CardContent>
        </Card>

        <div className="space-y-5">
          <Card>
            <CardHeader>
              <CardTitle>{t("verify.ledger")}</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 text-sm">
              <div className="flex flex-wrap gap-2">
                <Badge variant="secondary">{ledger.data?.backend ?? d.ledger.backend}</Badge>
                <Badge variant={d.ledger.decentralised ? "safe" : "warn"}>
                  {d.ledger.decentralised ? t("verify.multiParty") : t("verify.singleParty")}
                </Badge>
                <Badge variant={(ledger.data?.integrity_ok ?? d.ledger.integrity_ok) ? "safe" : "crit"}>
                  {(ledger.data?.integrity_ok ?? d.ledger.integrity_ok) ? t("verify.ledgerOk") : t("verify.ledgerBroken")}
                </Badge>
              </div>
              <p className="text-muted-foreground">{t("verify.entries", { count: ledger.data?.entries ?? d.ledger.entries })}</p>
              {!d.ledger.decentralised && <p className="text-xs text-muted-foreground">{t("verify.singlePartyNote")}</p>}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>{t("verify.handovers")}</CardTitle>
            </CardHeader>
            <CardContent>
              {d.handovers.length === 0 ? (
                <p className="text-sm text-muted-foreground">{t("custody.none")}</p>
              ) : (
                <ul className="space-y-1.5 text-sm">
                  {d.handovers.map((h) => (
                    <li key={h.id} className="flex items-center justify-between gap-2">
                      <span>
                        {t(`stages.${h.stage}`)} <span className="text-muted-foreground">· {h.organisation}</span>
                      </span>
                      <Badge variant={h.ok ? (h.anchored ? "safe" : "muted") : "crit"}>{h.ok ? (h.anchored ? t("custody.anchored") : t("verify.batchStatus.pending")) : t("verify.status.TAMPERED")}</Badge>
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>
        </div>
      </div>

      <div className="grid gap-5 xl:grid-cols-3">
        <Card className="xl:col-span-2">
          <CardHeader>
            <CardTitle>{t("verify.ledgerEntries")}</CardTitle>
          </CardHeader>
          <CardContent>
            {entries.isPending ? (
              <LoadingBlock rows={2} />
            ) : entries.isError ? (
              <ErrorState error={entries.error} />
            ) : entries.data.length === 0 ? (
              <EmptyState title={t("verify.noEntries")} />
            ) : (
              <ul className="divide-y text-sm">
                {entries.data.map((e) => (
                  <li key={e.ref} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2">
                    <Badge variant="outline">{e.kind}</Badge>
                    <span className="font-mono text-xs">{e.ref}</span>
                    <span className="font-mono text-xs text-muted-foreground" title={String(e.payload.merkle_root ?? e.payload.batches_root ?? "")}>
                      {shortHash(String(e.payload.merkle_root ?? e.payload.batches_root ?? e.hash), 10)}
                    </span>
                    <span className="ml-auto text-xs text-muted-foreground">{formatDateTime(e.ts)}</span>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
        <ProofLookup />
      </div>

      {can("admin") && demoStatus.data?.enabled && (
        <Card className="border-dashed border-orange-500/60">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <FlaskConical className="size-4" aria-hidden /> {t("verify.demoTools")}
            </CardTitle>
            <p className="text-sm text-muted-foreground">{t("verify.demoToolsHint")}</p>
          </CardHeader>
          <CardContent className="flex flex-wrap gap-2">
            {(["edit_value", "edit_body", "rewrite_hash", "delete_record"] as const).map((k) => (
              <Button key={k} variant="outline" size="sm" disabled={tamper.isPending} onClick={() => tamper.mutate({ shipment_id: id, kind: k })}>
                {t(`verify.tamper.${k}`)}
              </Button>
            ))}
            <Button size="sm" variant="secondary" disabled={restore.isPending} onClick={() => restore.mutate(id)}>
              <RotateCcw /> {t("verify.restore")}
            </Button>
            {tamper.isError && <p role="alert" className="w-full text-sm text-destructive">{tamper.error.message}</p>}
            {tamper.isSuccess && <p role="status" className="w-full text-sm">{JSON.stringify(tamper.data.tampered)}</p>}
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function ProofLookup() {
  const { t } = useTranslation();
  const [device, setDevice] = useState("");
  const [seq, setSeq] = useState("");
  const [query, setQuery] = useState<{ d: string; s: string } | null>(null);
  const proof = useQuery({
    queryKey: ["proof", query],
    enabled: !!query,
    retry: false,
    queryFn: () =>
      get<{ record_hash: string; merkle_root: string; ledger_ref: string; proof: { hash: string; side: string }[]; method: string }>(
        `/api/ledger/proof/${query!.d}/${query!.s}`,
      ),
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (device && seq) setQuery({ d: device.trim(), s: seq.trim() });
  };
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("verify.proof")}</CardTitle>
        <p className="text-sm text-muted-foreground">{t("verify.proofHint")}</p>
      </CardHeader>
      <CardContent className="space-y-3">
        <form onSubmit={submit} className="flex flex-wrap items-end gap-2">
          <div className="grid gap-1">
            <Label htmlFor="pdev">{t("verify.device")}</Label>
            <Input id="pdev" className="w-32" placeholder="TAG-0001" value={device} onChange={(e) => setDevice(e.target.value)} />
          </div>
          <div className="grid gap-1">
            <Label htmlFor="pseq">seq</Label>
            <Input id="pseq" className="w-24" inputMode="numeric" value={seq} onChange={(e) => setSeq(e.target.value)} />
          </div>
          <Button type="submit" size="sm" variant="outline">
            <Search /> {t("verify.prove")}
          </Button>
        </form>
        {proof.isError && <p role="alert" className="text-sm text-destructive">{proof.error.message}</p>}
        {proof.data && (
          <div className="space-y-1 text-xs">
            <p>
              <span className="text-muted-foreground">record </span>
              <span className="font-mono">{shortHash(proof.data.record_hash, 10)}</span>
            </p>
            <ol className="ml-4 list-decimal font-mono">
              {proof.data.proof.map((p, i) => (
                <li key={i}>
                  {p.side} {shortHash(p.hash, 10)}
                </li>
              ))}
            </ol>
            <p>
              <span className="text-muted-foreground">root </span>
              <span className="font-mono">{shortHash(proof.data.merkle_root, 10)}</span> · {proof.data.ledger_ref}
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
