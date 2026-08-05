import { NotificationsBell } from "@/modules/notifications"
import { ktmNotificationsApi } from "./ktmNotificationsApi"

/**
 * KTM-обвязка переносимого модуля notifications:
 * axios-адаптер поверх проектного клиента.
 */
export function KtmNotificationBell() {
  return <NotificationsBell api={ktmNotificationsApi} />
}
