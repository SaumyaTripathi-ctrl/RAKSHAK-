import { useTranslation } from "react-i18next";

import { NativeSelect } from "@/components/ui/misc";
import { humanFood } from "@/lib/format";
import { useShipments } from "@/lib/queries";

/** Dropdown of shipments; used by the Custody, Verify and Alerts pages. */
export function ShipmentPicker({ value, onChange }: { value?: string; onChange: (id: string) => void }) {
  const { t } = useTranslation();
  const { data } = useShipments();
  return (
    <div className="flex items-center gap-2">
      <label htmlFor="shipment-picker" className="text-sm font-medium">
        {t("nav.shipments")}
      </label>
      <NativeSelect id="shipment-picker" className="w-auto min-w-56" value={value ?? ""} onChange={(e) => onChange(e.target.value)}>
        {!value && <option value="">{t("common.choose")}</option>}
        {(data ?? []).map((s) => (
          <option key={s.id} value={s.id}>
            {s.id} · {t(`foods.${s.food_type}`, { defaultValue: humanFood(s.food_type) })}
          </option>
        ))}
      </NativeSelect>
    </div>
  );
}
