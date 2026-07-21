export type HrmsConnectionPreset = {
  id: string
  label: string
  value: string
  hint: string
}

/** IP сервера по умолчанию, если hostname в браузере недоступен. */
export const HRMS_DEFAULT_SERVER_HOST = "localhost"

export const HRMS_API_PORT = 8011

export const HRMS_LOCAL_PRESET: HrmsConnectionPreset = {
  id: "local",
  label: "Локально",
  value: "localhost:8011",
  hint: "HRMS на этой машине (dev, порт 8011)",
}

export function resolveHrmsServerHost(): string {
  if (typeof window !== "undefined" && window.location.hostname) {
    return window.location.hostname
  }
  return HRMS_DEFAULT_SERVER_HOST
}

export function buildHrmsServerAddress(host = resolveHrmsServerHost()): string {
  return `${host}:${HRMS_API_PORT}`
}

/** Основные варианты подключения к HRMS API. */
export function getHrmsConnectionPresets(): HrmsConnectionPreset[] {
  const serverHost = resolveHrmsServerHost()
  return [
    HRMS_LOCAL_PRESET,
    {
      id: "server",
      label: "Сервер",
      value: buildHrmsServerAddress(serverHost),
      hint: `HRMS на том же IP, что и KTM (${serverHost}:${HRMS_API_PORT})`,
    },
  ]
}

export function findHrmsConnectionPreset(
  value: string,
  presets: HrmsConnectionPreset[] = getHrmsConnectionPresets(),
): HrmsConnectionPreset | undefined {
  const normalized = value.trim().toLowerCase()
  return presets.find((preset) => preset.value.toLowerCase() === normalized)
}
