import { apiClient } from "@/shared/api/client"
import type {
  InternalNotification,
  InternalNotificationList,
  NotificationsApi,
} from "@/modules/notifications"

/**
 * Адаптер модуля notifications к бэкенду KTM.
 *
 * Реализован поверх проектного axios-инстанса (а не createHttpAdapter),
 * чтобы сохранить общие интерсепторы: обработку 401, токен и т.д.
 *
 * Бэк уведомлений KTM пока отсутствует (отдельная задача) — эндпоинты
 * используют тот же каноничный контракт /internal-notifications.
 */
export const ktmNotificationsApi: NotificationsApi = {
  async list(limit = 50): Promise<InternalNotificationList> {
    const { data } = await apiClient.get<InternalNotificationList>(
      "/internal-notifications",
      { params: { limit, only_unclosed: true } },
    )
    return data
  },

  async markRead(id): Promise<InternalNotification> {
    const { data } = await apiClient.post<InternalNotification>(
      `/internal-notifications/${id}/read`,
    )
    return data
  },

  async close(id): Promise<InternalNotification> {
    const { data } = await apiClient.post<InternalNotification>(
      `/internal-notifications/${id}/close`,
    )
    return data
  },
}
