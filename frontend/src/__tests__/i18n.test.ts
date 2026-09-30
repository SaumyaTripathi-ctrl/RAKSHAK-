import { readFileSync, readdirSync, statSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

import en from "../locales/en.json";
import hi from "../locales/hi.json";
import i18n from "../lib/i18n";

type Tree = { [k: string]: string | Tree };
function flatten(o: Tree, prefix = ""): string[] {
  return Object.entries(o).flatMap(([k, v]) => (typeof v === "string" ? [prefix + k] : flatten(v, `${prefix}${k}.`)));
}
const enKeys = new Set(flatten(en as Tree));
const hiKeys = new Set(flatten(hi as Tree));

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((f) => {
    const p = path.join(dir, f);
    if (statSync(p).isDirectory()) return f === "__tests__" || f === "test" ? [] : sources(p);
    return /\.tsx?$/.test(f) ? [p] : [];
  });
}

describe("translations", () => {
  it("English and Hindi define exactly the same keys", () => {
    expect([...enKeys].filter((k) => !hiKeys.has(k))).toEqual([]);
    expect([...hiKeys].filter((k) => !enKeys.has(k))).toEqual([]);
  });

  it("every statically used t('key') exists in both languages", () => {
    const used = new Set<string>();
    for (const file of sources(path.resolve(__dirname, ".."))) {
      const s = readFileSync(file, "utf8");
      for (const m of s.matchAll(/\bt\(\s*(["'`])([^"'`]+)\1/g)) if (!m[2].includes("${")) used.add(m[2]);
    }
    expect(used.size).toBeGreaterThan(100);
    expect([...used].filter((k) => !enKeys.has(k))).toEqual([]);
    expect([...used].filter((k) => !hiKeys.has(k))).toEqual([]);
  });

  it("covers every dynamic key family", () => {
    const fam: Record<string, string[]> = {
      levels: ["SAFE", "WARNING", "CRITICAL"],
      stages: ["FARM", "FPO", "PACKHOUSE", "COLD_STORAGE", "TRANSPORT", "RETAIL"],
      status: ["CREATED", "IN_TRANSIT", "DELIVERED"],
      roles: ["admin", "fpo", "driver", "exporter"],
      foods: ["mango", "banana", "tomato", "leafy_vegetables", "milk"],
      facility: ["cold_storage", "fpo_packhouse", "ripening_chamber"],
      "sim.state": ["created", "running", "paused", "finished", "stopped", "error"],
      "verify.batchStatus": ["verified", "tampered", "pending", "ledger_unreachable"],
      "verify.explain": ["VERIFIED", "PARTIAL", "PENDING", "TAMPERED", "LEDGER_UNREACHABLE"],
      "verify.status": ["VERIFIED", "PARTIAL", "PENDING", "TAMPERED", "LEDGER_UNREACHABLE"],
      "verify.tamper": ["edit_value", "edit_body", "rewrite_hash", "delete_record"],
      "common.socket": ["connecting", "open", "closed"],
      nav: ["fleet", "shipments", "alerts", "custody", "verify", "devices", "simulator"],
      "events.kind": [
        "TAMPER_BAD_HASH", "TAMPER_CHAIN_BREAK", "TAMPER_CONFLICT", "AUTH_FAILED", "MISSING_RECORDS", "GAP_FILLED",
        "UNKNOWN_DEVICE", "LID_OPEN", "SHOCK", "LOW_BATTERY", "ALERT_WARNING", "ALERT_CRITICAL", "RECOVERED",
        "REROUTE", "HUB_OFFLINE", "HUB_ONLINE", "COMMAND", "HANDOVER", "LEDGER_ANCHORED",
      ],
    };
    const missing = Object.entries(fam).flatMap(([p, ks]) => ks.map((k) => `${p}.${k}`)).filter((k) => !enKeys.has(k) || !hiKeys.has(k));
    expect(missing).toEqual([]);
    expect(enKeys.has("shipment.profile_real") && enKeys.has("shipment.profile_demo")).toBe(true);
  });

  it("keeps interpolation variables identical in both languages", () => {
    const vars = (s: string) => [...s.matchAll(/\{\{(\w+)\}\}/g)].map((m) => m[1]).sort().join(",");
    const get = (o: Tree, k: string) => k.split(".").reduce<string | Tree>((a, p) => (a as Tree)[p], o) as string;
    const bad = [...enKeys].filter((k) => vars(get(en as Tree, k)) !== vars(get(hi as Tree, k)));
    expect(bad).toEqual([]);
  });

  it("switches language at runtime and interpolates", async () => {
    await i18n.changeLanguage("hi");
    expect(i18n.t("levels.CRITICAL")).toBe("गंभीर");
    expect(i18n.t("alerts.acknowledgedBy", { name: "Sunil" })).toContain("Sunil");
    await i18n.changeLanguage("en");
    expect(i18n.t("levels.CRITICAL")).toBe("CRITICAL");
    expect(i18n.t("does.not.exist")).toBe("does.not.exist");
  });
});
