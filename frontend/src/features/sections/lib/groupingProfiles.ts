/**
 * lib/groupingProfiles.ts
 * =======================
 * Система профилей группировки задач на доске участка.
 *
 * КОНЦЕПЦИЯ:
 *   Вместо жёсткой группировки SKU+route_step пользователь выбирает,
 *   по каким полям сигнатуры группировать задачи.
 *
 *   Каждый профиль — набор критериев в порядке приоритета.
 *   Ключ группы строится конкатенацией значений всех критериев:
 *   ["productSku", "operationCode"] → "ЮП-460__press_window"
 *
 * ХРАНЕНИЕ:
 *   localStorage — намеренный выбор вместо sessionStorage.
 *   Причина: настройки должны сохраняться между сессиями.
 */


// ---------------------------------------------------------------------------
// Типы
// ---------------------------------------------------------------------------

/**
 * Критерий группировки — одно поле сигнатуры задачи.
 *
 * МАППИНГ на поля SectionBoardTask:
 *   productSku    → task.signature.output_sku
 *   routeStepId   → task.route_step_id
 *   operationCode → task.signature.operation_code
 *   outputKind    → task.signature.output_kind
 *   sourceRef     → task.signature.source_ref
 *   fingerprint   → task.signature.source_fingerprint
 *   customField   → task.signature.source_payload[key]
 */
export type GroupingCriterion =
  | "productSku"     // Артикул (output_sku)
  | "routeStepId"    // Шаг маршрута (route_step_id)
  | "operationCode"  // Код операции (press_window, press_comb...)
  | "outputKind"     // Цвет/тип выхода (silver, black...)
  | "sourceRef"      // Ссылка на заказ (ЗКЗ-2024-1241/5)
  | "fingerprint"    // Полная сигнатура (SHA1-хеш)
  | "customField";   // Произвольное поле из source_payload


export interface GroupingProfile {
  id: string;
  name: string;

  /**
   * Критерии группировки в порядке приоритета.
   * Порядок важен: ["productSku", "operationCode"] даёт
   * "ЮП-460__press_window", а не "press_window__ЮП-460".
   */
  criteria: GroupingCriterion[];

  /**
   * Ключи из source_payload для кастомного профиля.
   * Заполняется пользователем через GroupingSettingsModal.
   * Игнорируется для всех профилей кроме id="custom".
   */
  customFields?: string[];

  /**
   * Профиль создан пользователем (не встроенный пресет).
   */
  isUserDefined?: boolean;
}


// ---------------------------------------------------------------------------
// Пресеты
// ---------------------------------------------------------------------------

export const PRESET_PROFILES: GroupingProfile[] = [
  {
    id: "sku",
    name: "Только артикул",
    criteria: ["productSku"],
  },
  {
    id: "sku+stage",
    name: "Артикул + этап",
    criteria: ["productSku", "routeStepId"],
  },
  {
    id: "sku+operation",
    name: "Артикул + операция",
    criteria: ["productSku", "operationCode"],
  },
  {
    id: "sku+output",
    name: "Артикул + цвет",
    criteria: ["productSku", "outputKind"],
  },
  {
    id: "sku+ref",
    name: "Артикул + заказ",
    criteria: ["productSku", "sourceRef"],
  },
  {
    id: "fingerprint",
    name: "Полная сигнатура",
    criteria: ["fingerprint"],
  },
  {
    id: "custom",
    name: "Свой набор полей",
    criteria: ["customField"],
    customFields: [],
  },
];

// Быстрый доступ по id
export const PROFILE_BY_ID = Object.fromEntries(
  PRESET_PROFILES.map((p) => [p.id, p]),
) as Record<string, GroupingProfile>;


// ---------------------------------------------------------------------------
// localStorage — хранение и загрузка профилей
// ---------------------------------------------------------------------------

const STORAGE_KEYS = {
  defaultProfile: "shopfloor.grouping.defaultProfile",
  sectionProfile: (sectionId: number) =>
    `shopfloor.grouping.sectionProfile.${sectionId}`,
} as const;


export function loadProfileForSection(sectionId: number): GroupingProfile {
  // 1. Переопределение на участок
  try {
    const raw = localStorage.getItem(STORAGE_KEYS.sectionProfile(sectionId));
    if (raw) {
      const parsed = JSON.parse(raw) as GroupingProfile;
      if (parsed.id && Array.isArray(parsed.criteria)) {
        return parsed;
      }
    }
  } catch { /* ignore */ }

  // 2. Глобальный профиль по умолчанию
  try {
    const raw = localStorage.getItem(STORAGE_KEYS.defaultProfile);
    if (raw) {
      const parsed = JSON.parse(raw) as GroupingProfile;
      if (parsed.id && Array.isArray(parsed.criteria)) {
        return parsed;
      }
    }
  } catch { /* ignore */ }

  // 3. Встроенный дефолт — "Артикул + этап"
  return PRESET_PROFILES[1];
}


export function saveProfileForSection(
  sectionId: number,
  profile: GroupingProfile,
): void {
  try {
    localStorage.setItem(
      STORAGE_KEYS.sectionProfile(sectionId),
      JSON.stringify(profile),
    );
  } catch (e) {
    console.warn("Failed to save grouping profile:", e);
  }
}


export function saveDefaultProfile(profile: GroupingProfile): void {
  try {
    localStorage.setItem(
      STORAGE_KEYS.defaultProfile,
      JSON.stringify(profile),
    );
  } catch (e) {
    console.warn("Failed to save default grouping profile:", e);
  }
}


export function resetSectionProfile(sectionId: number): void {
  localStorage.removeItem(STORAGE_KEYS.sectionProfile(sectionId));
}


// ---------------------------------------------------------------------------
// Утилиты для UI
// ---------------------------------------------------------------------------

export const CRITERION_LABELS: Record<GroupingCriterion, string> = {
  productSku:    "Артикул (output)",
  routeStepId:   "Шаг маршрута",
  operationCode: "Код операции",
  outputKind:    "Цвет / тип выхода",
  sourceRef:     "Ссылка на заказ",
  fingerprint:   "Полная сигнатура",
  customField:   "Поля из source_payload",
};


export function getProfilePreview(profile: GroupingProfile): string {
  const examples: Record<string, string> = {
    "sku":           "ЮП-460",
    "sku+stage":     "ЮП-460 · Этап 2",
    "sku+operation": "ЮП-460 · press_window",
    "sku+output":    "ЮП-460 · silver",
    "sku+ref":       "ЮП-460 · ЗКЗ-2024-1241",
    "fingerprint":   "a3f9c2d41b88",
    "custom":        `ЮП-460 · ${(profile.customFields ?? []).join(" · ") || "..."}`,
  };
  return examples[profile.id] ?? "—";
}
