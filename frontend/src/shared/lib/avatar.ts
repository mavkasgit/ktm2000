/**
 * Multiavatar seed helpers — same contract as HRMS.
 * Seed = 8 hex chars; null → empty placeholder on UI.
 */

export type AvatarUserLike = {
  avatar_seed?: string | null
}

export function getUserSeed(user?: AvatarUserLike | null): string | null {
  if (!user?.avatar_seed) return null
  return user.avatar_seed
}

export function generateRandomSeed(): string {
  const bytes = new Uint8Array(4)
  crypto.getRandomValues(bytes)
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("")
}
