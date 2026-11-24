import { useEffect, useState } from "react";

import { AdminSearchStats } from "@/blocks/admin-search-stats";
import { loadStats } from "@/blocks/admin-search-stats/load";
import type { SearchStats } from "@/lib/figures-types";

export default function StatsPage() {
  const [stats, setStats] = useState<SearchStats | null>(null);
  useEffect(() => {
    loadStats().then(setStats, () => setStats({ today: 0, week: 0, zero_words: [], top_clicked: [], recent: [] }));
  }, []);
  return <AdminSearchStats stats={stats} searchHref={(q) => `/search?q=${encodeURIComponent(q)}`} />;
}
