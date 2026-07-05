import { apiClient } from "./client";

export type UserListItem = {
  id: number;
  username: string;
  full_name: string;
  is_active: boolean;
};

export type UsersListResponse = {
  users: UserListItem[];
  total: number;
  limit: number;
  offset: number;
};

export async function listUsersPaginated(params: {
  limit?: number;
  offset?: number;
} = {}): Promise<UsersListResponse> {
  const { data } = await apiClient.get<UsersListResponse>("/users", { params });
  return data;
}

/** Все пользователи для селектов/диалогов (пагинация, max 500 на запрос). */
export async function listUsers(): Promise<UserListItem[]> {
  const pageSize = 500;
  const all: UserListItem[] = [];
  let offset = 0;
  let total = Infinity;

  while (offset < total) {
    const response = await listUsersPaginated({ limit: pageSize, offset });
    all.push(...response.users);
    total = response.total;
    offset += response.users.length;
    if (response.users.length === 0) break;
  }

  return all;
}