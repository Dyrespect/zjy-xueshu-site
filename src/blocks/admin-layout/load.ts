import { adminLogout, adminMe, listConversations } from "@/lib/admin";

export async function isLoggedIn(): Promise<boolean> {
  try {
    return (await adminMe()).admin;
  } catch {
    return false;
  }
}

/** 侧栏「会话」上的数：有几个客户有回复等你批 */
export async function loadNavBadges(): Promise<Record<string, number>> {
  const rows = await listConversations();
  return { "/admin/conversations": rows.filter((r) => r.pending > 0 || r.failed > 0).length };
}

export const logout = adminLogout;
