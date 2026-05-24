/**
 * components/GroupingSettingsModal.tsx
 * =====================================
 * Модальное окно настройки профиля группировки задач.
 *
 * ПОТОК ВЗАИМОДЕЙСТВИЯ:
 *   1. Пользователь кликает "Настройки группировки"
 *   2. Открывается модалка с текущим активным профилем
 *   3. Выбирает пресет или настраивает кастомный профиль
 *   4. "Применить" → сохранение в localStorage → onApply callback
 */

import { useState } from "react";
import { getSectionPayloadKeys } from "@/shared/api/shopfloor";
import {
  PRESET_PROFILES,
  type GroupingProfile,
  CRITERION_LABELS,
  getProfilePreview,
  saveProfileForSection,
  saveDefaultProfile,
} from "../lib/groupingProfiles";


// ---------------------------------------------------------------------------
// Типы
// ---------------------------------------------------------------------------

interface GroupingSettingsModalProps {
  sectionId: number;
  sectionName: string;
  currentProfile: GroupingProfile;
  onClose: () => void;
  onApply: (profile: GroupingProfile) => void;
}


// ---------------------------------------------------------------------------
// Основной компонент
// ---------------------------------------------------------------------------

export function GroupingSettingsModal({
  sectionId,
  sectionName,
  currentProfile,
  onClose,
  onApply,
}: GroupingSettingsModalProps) {
  const [selected, setSelected] = useState<GroupingProfile>(currentProfile);
  const [saveAsDefault, setSaveAsDefault] = useState(false);
  const [payloadKeys, setPayloadKeys] = useState<string[]>([]);
  const [keysLoading, setKeysLoading] = useState(false);
  const [keysLoaded, setKeysLoaded] = useState(false);

  // Ленивая загрузка ключей при выборе custom профиля
  const customFields = selected.customFields ?? [];

  async function loadPayloadKeys() {
    if (keysLoaded) return;
    setKeysLoading(true);
    try {
      const keys = await getSectionPayloadKeys(sectionId);
      setPayloadKeys(keys);
      setKeysLoaded(true);
    } catch (e) {
      console.warn("Failed to load payload keys:", e);
    } finally {
      setKeysLoading(false);
    }
  }

  function handleSelectPreset(profile: GroupingProfile) {
    if (profile.id === "custom") {
      setSelected({
        ...profile,
        customFields: selected.id === "custom" ? customFields : [],
      });
      loadPayloadKeys();
    } else {
      setSelected(profile);
    }
  }

  function handleToggleCustomField(key: string) {
    const next = customFields.includes(key)
      ? customFields.filter((k) => k !== key)
      : [...customFields, key].sort();

    setSelected((prev) => ({ ...prev, customFields: next }));
  }

  function handleApply() {
    if (selected.id === "custom" && (selected.customFields?.length ?? 0) === 0) {
      alert("Выберите хотя бы одно поле для кастомной группировки");
      return;
    }

    saveProfileForSection(sectionId, selected);
    if (saveAsDefault) {
      saveDefaultProfile(selected);
    }

    onApply(selected);
    onClose();
  }


  // ---------------------------------------------------------------------------
  // Рендер
  // ---------------------------------------------------------------------------

  return (
    <div
      className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center"
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      <div className="bg-white rounded-lg shadow-xl max-w-lg w-full max-h-[90vh] flex flex-col m-4" role="dialog" aria-modal>
        {/* Заголовок */}
        <div className="flex items-center justify-between p-4 border-b">
          <div>
            <h2 className="text-lg font-semibold">Настройки группировки</h2>
            <p className="text-sm text-muted-foreground">Участок: {sectionName}</p>
          </div>
          <button
            className="text-muted-foreground hover:text-foreground text-2xl leading-none"
            onClick={onClose}
            aria-label="Закрыть"
          >
            ×
          </button>
        </div>

        {/* Список пресетов */}
        <div className="flex-1 overflow-auto p-4 space-y-3">
          <h3 className="text-sm font-medium">Профиль группировки</h3>
          <div className="grid gap-2">
            {PRESET_PROFILES.map((profile) => (
              <ProfileOption
                key={profile.id}
                profile={profile}
                isActive={selected.id === profile.id}
                onClick={() => handleSelectPreset(profile)}
              />
            ))}
          </div>

          {/* Кастомные поля */}
          {selected.id === "custom" && (
            <div className="space-y-2">
              <h3 className="text-sm font-medium flex items-center gap-2">
                Поля из source_payload
                {keysLoading && (
                  <span className="text-xs text-muted-foreground">загрузка...</span>
                )}
              </h3>

              {!keysLoading && !keysLoaded && (
                <button
                  className="text-sm text-blue-600 hover:underline"
                  onClick={loadPayloadKeys}
                >
                  Загрузить доступные поля
                </button>
              )}

              {!keysLoading && payloadKeys.length === 0 && keysLoaded && (
                <p className="text-sm text-muted-foreground">
                  Нет дополнительных полей для задач этого участка
                </p>
              )}

              {payloadKeys.length > 0 && (
                <div className="grid grid-cols-2 gap-2">
                  {payloadKeys.map((key) => (
                    <label key={key} className="flex items-center gap-2 text-sm p-2 rounded border hover:bg-gray-50 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={customFields.includes(key)}
                        onChange={() => handleToggleCustomField(key)}
                        className="rounded"
                      />
                      <code className="text-xs">{key}</code>
                    </label>
                  ))}
                </div>
              )}

              {customFields.length > 0 && (
                <div className="text-sm bg-gray-50 rounded p-2">
                  <span className="text-muted-foreground">Пример: </span>
                  <code className="text-xs">
                    {getProfilePreview({ ...selected, customFields })}
                  </code>
                </div>
              )}
            </div>
          )}

          {/* Глобальный дефолт */}
          <div className="pt-2 border-t">
            <label className="flex items-center gap-2 text-sm cursor-pointer">
              <input
                type="checkbox"
                checked={saveAsDefault}
                onChange={(e) => setSaveAsDefault(e.target.checked)}
                className="rounded"
              />
              <span>Применить как профиль по умолчанию для всех участков</span>
            </label>
            <p className="text-xs text-muted-foreground mt-1">
              Переопределение на конкретный участок сохраняется отдельно
              и имеет приоритет над глобальным
            </p>
          </div>
        </div>

        {/* Кнопки */}
        <div className="flex justify-end gap-2 p-4 border-t">
          <button
            className="px-4 py-2 rounded-md border hover:bg-gray-50 text-sm"
            onClick={onClose}
          >
            Отмена
          </button>
          <button
            className="px-4 py-2 rounded-md bg-blue-600 text-white hover:bg-blue-700 text-sm"
            onClick={handleApply}
          >
            Применить
          </button>
        </div>
      </div>
    </div>
  );
}


// ---------------------------------------------------------------------------
// ProfileOption
// ---------------------------------------------------------------------------

interface ProfileOptionProps {
  profile: GroupingProfile;
  isActive: boolean;
  onClick: () => void;
}

function ProfileOption({ profile, isActive, onClick }: ProfileOptionProps) {
  return (
    <button
      className={`w-full text-left p-3 rounded-lg border transition-colors ${
        isActive
          ? "border-blue-500 bg-blue-50 ring-1 ring-blue-500/20"
          : "hover:bg-gray-50"
      }`}
      onClick={onClick}
      type="button"
    >
      <div className="flex items-center justify-between">
        <span className="font-medium text-sm">{profile.name}</span>
        {isActive && (
          <span className="inline-flex items-center rounded-full bg-blue-100 px-2 py-0.5 text-xs font-medium text-blue-700">
            активен
          </span>
        )}
      </div>

      {/* Критерии */}
      <div className="flex gap-1 mt-1 flex-wrap">
        {profile.id !== "custom" &&
          profile.criteria.map((c) => (
            <span key={c} className="inline-flex items-center rounded-md bg-gray-100 px-1.5 py-0.5 text-xs text-gray-600">
              {CRITERION_LABELS[c]}
            </span>
          ))}
        {profile.id === "custom" && (
          <span className="inline-flex items-center rounded-md bg-gray-100 px-1.5 py-0.5 text-xs text-gray-600">
            Выбираете вы
          </span>
        )}
      </div>

      {/* Пример */}
      <div className="text-xs text-muted-foreground mt-1">
        Пример: <code>{getProfilePreview(profile)}</code>
      </div>
    </button>
  );
}
