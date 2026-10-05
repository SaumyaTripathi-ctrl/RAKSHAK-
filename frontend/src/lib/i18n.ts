import i18n from "i18next";
import { initReactI18next } from "react-i18next";

import en from "../locales/en.json";
import hi from "../locales/hi.json";

export const LANGUAGES = [
  { code: "en", label: "English" },
  { code: "hi", label: "हिन्दी" },
] as const;
export type LangCode = (typeof LANGUAGES)[number]["code"];

const KEY = "rakshak.lang";

function initialLanguage(): LangCode {
  try {
    const saved = localStorage.getItem(KEY);
    if (saved === "en" || saved === "hi") return saved;
  } catch {
    /* ignore */
  }
  return "en"; // English by default everywhere; Hindi only when the user picks it
}

void i18n.use(initReactI18next).init({
  resources: { en: { translation: en }, hi: { translation: hi } },
  lng: initialLanguage(),
  fallbackLng: "en",
  interpolation: { escapeValue: false },
  returnNull: false,
});

export function setLanguage(code: LangCode): void {
  void i18n.changeLanguage(code);
  try {
    localStorage.setItem(KEY, code);
  } catch {
    /* ignore */
  }
  document.documentElement.lang = code;
}

export default i18n;
