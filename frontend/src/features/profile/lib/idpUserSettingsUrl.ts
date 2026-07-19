export function idpUserSettingsUrlFromIssuer(issuer: string | null | undefined): string | null {
  if (!issuer?.trim()) return null
  try {
    const u = new URL(issuer)
    return `${u.origin}/if/user/`
  } catch {
    return null
  }
}
