import { apiClient } from "./client";

export type UserListItem = {
  id: number;
  username: string;
  full_name: string;
  is_active: boolean;
};

export async function listUsers(): Promise<UserListItem[]> {
  const { data } = await apiClient.get<{
    users: UserListItem[];
    total: number;
    limit: number;
    offset: number;
  }>("/users", { params: { limit: 500, offset: 0 } });
  return data.users;
}