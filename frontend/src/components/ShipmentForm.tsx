import { Plus } from "lucide-react";
import { useMemo, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Input, Label } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/misc";
import { useAuth } from "@/lib/auth";
import { humanFood } from "@/lib/format";
import { useCreateShipment, useDevices, useFoodTypes } from "@/lib/queries";

function num(v: string): number | null {
  const n = Number(v);
  return v.trim() === "" || Number.isNaN(n) ? null : n;
}

export function CreateShipmentDialog() {
  const { t } = useTranslation();
  const nav = useNavigate();
  const { can } = useAuth();
  const foods = useFoodTypes();
  const devices = useDevices();
  const create = useCreateShipment();
  const [open, setOpen] = useState(false);
  const [f, setF] = useState({
    food_type: "",
    variety: "",
    weight_kg: "1000",
    origin_name: "",
    origin_lat: "",
    origin_lon: "",
    dest_name: "",
    dest_lat: "",
    dest_lon: "",
    hub_id: "",
    model_profile: "real",
  });
  const [tags, setTags] = useState<string[]>([]);
  const [formError, setFormError] = useState<string | null>(null);

  const hubs = useMemo(() => (devices.data ?? []).filter((d) => d.kind === "hub"), [devices.data]);
  const hubTags = useMemo(() => (devices.data ?? []).filter((d) => d.kind === "tag" && (!f.hub_id || d.hub_id === f.hub_id)), [devices.data, f.hub_id]);
  const band = foods.data?.find((x) => x.food_type === f.food_type);

  if (!can("admin", "fpo")) return null;

  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF((s) => ({ ...s, [k]: e.target.value }));

  const submit = (e: FormEvent) => {
    e.preventDefault();
    setFormError(null);
    if (!f.food_type) return setFormError(t("shipment.form.foodRequired"));
    const weight = num(f.weight_kg);
    if (weight === null || weight < 0) return setFormError(t("shipment.form.weightInvalid"));
    create.mutate(
      {
        food_type: f.food_type,
        variety: f.variety,
        weight_kg: weight,
        origin_name: f.origin_name,
        origin_lat: num(f.origin_lat),
        origin_lon: num(f.origin_lon),
        dest_name: f.dest_name,
        dest_lat: num(f.dest_lat),
        dest_lon: num(f.dest_lon),
        hub_id: f.hub_id || null,
        tag_ids: tags,
        model_profile: f.model_profile,
      },
      {
        onSuccess: (s) => {
          setOpen(false);
          nav(`/shipments/${s.id}`);
        },
        onError: (err) => setFormError(err.message),
      },
    );
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button>
          <Plus /> {t("shipment.new")}
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("shipment.new")}</DialogTitle>
          <DialogDescription>{t("shipment.form.hint")}</DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} className="grid gap-3" noValidate>
          <div className="grid gap-1.5">
            <Label htmlFor="food">{t("shipment.foodType")}</Label>
            <NativeSelect id="food" value={f.food_type} onChange={set("food_type")} required>
              <option value="">{t("common.choose")}</option>
              {(foods.data ?? []).map((x) => (
                <option key={x.food_type} value={x.food_type}>
                  {t(`foods.${x.food_type}`, { defaultValue: humanFood(x.food_type) })}
                </option>
              ))}
            </NativeSelect>
            {band && (
              <p className="text-xs text-muted-foreground">
                {t("shipment.form.band", { min: band.min_temp, max: band.max_temp })} · <span title={band.source}>{t("shipment.form.todoVerify")}</span>
              </p>
            )}
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="grid gap-1.5">
              <Label htmlFor="variety">{t("shipment.variety")}</Label>
              <Input id="variety" value={f.variety} onChange={set("variety")} />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="weight">{t("shipment.weight")}</Label>
              <Input id="weight" inputMode="decimal" value={f.weight_kg} onChange={set("weight_kg")} />
            </div>
          </div>
          <div className="grid grid-cols-3 gap-3">
            <div className="col-span-3 grid gap-1.5 sm:col-span-1">
              <Label htmlFor="on">{t("shipment.origin")}</Label>
              <Input id="on" value={f.origin_name} onChange={set("origin_name")} />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="olat">{t("common.lat")}</Label>
              <Input id="olat" inputMode="decimal" value={f.origin_lat} onChange={set("origin_lat")} />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="olon">{t("common.lon")}</Label>
              <Input id="olon" inputMode="decimal" value={f.origin_lon} onChange={set("origin_lon")} />
            </div>
            <div className="col-span-3 grid gap-1.5 sm:col-span-1">
              <Label htmlFor="dn">{t("shipment.destination")}</Label>
              <Input id="dn" value={f.dest_name} onChange={set("dest_name")} />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="dlat">{t("common.lat")}</Label>
              <Input id="dlat" inputMode="decimal" value={f.dest_lat} onChange={set("dest_lat")} />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="dlon">{t("common.lon")}</Label>
              <Input id="dlon" inputMode="decimal" value={f.dest_lon} onChange={set("dest_lon")} />
            </div>
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="hub">{t("shipment.hub")}</Label>
            <NativeSelect id="hub" value={f.hub_id} onChange={(e) => { set("hub_id")(e); setTags([]); }}>
              <option value="">{t("common.none")}</option>
              {hubs.map((h) => (
                <option key={h.id} value={h.id}>
                  {h.id} {h.shipment_id ? `(${t("devices.inUse", { id: h.shipment_id })})` : ""}
                </option>
              ))}
            </NativeSelect>
          </div>
          {hubTags.length > 0 && (
            <fieldset className="grid gap-1.5">
              <legend className="text-sm font-medium">{t("shipment.tags")}</legend>
              <div className="flex flex-wrap gap-2">
                {hubTags.map((tg) => (
                  <label key={tg.id} className="flex items-center gap-1.5 rounded-md border px-2 py-1 text-sm">
                    <input
                      type="checkbox"
                      checked={tags.includes(tg.id)}
                      onChange={(e) => setTags((cur) => (e.target.checked ? [...cur, tg.id] : cur.filter((x) => x !== tg.id)))}
                    />
                    {tg.id}
                  </label>
                ))}
              </div>
            </fieldset>
          )}
          {can("admin") && (
            <div className="grid gap-1.5">
              <Label htmlFor="profile">{t("shipment.profile")}</Label>
              <NativeSelect id="profile" value={f.model_profile} onChange={set("model_profile")}>
                <option value="real">{t("shipment.profileReal")}</option>
                <option value="demo">{t("shipment.profileDemo")}</option>
              </NativeSelect>
            </div>
          )}
          {formError && (
            <p role="alert" className="text-sm text-destructive">
              {formError}
            </p>
          )}
          <DialogFooter>
            <Button type="submit" disabled={create.isPending}>
              {t("common.create")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
