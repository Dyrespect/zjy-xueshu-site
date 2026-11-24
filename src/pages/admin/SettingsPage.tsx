import { useEffect, useState } from "react";

import { BriefSettingsForm } from "@/blocks/brief-settings";
import { ReceptionSettingsForm } from "@/blocks/reception-settings";
import { SettingsForm } from "@/blocks/settings-form";
import { createContactWay, getAdminSettings, saveAdminSettings, type AdminSettings } from "@/lib/admin";
import { getBriefSettings, saveBriefSettings, type BriefSettings } from "@/lib/brief";
import { getReceptionKB, saveReceptionKB, tryReception, uploadReceptionSample, type ReceptionKB } from "@/lib/reception";

export function SettingsPage() {
  const [settings, setSettings] = useState<AdminSettings | null>(null);
  const [brief, setBrief] = useState<BriefSettings | null>(null);
  const [reception, setReception] = useState<ReceptionKB | null>(null);
  useEffect(() => {
    getAdminSettings().then(setSettings).catch(() => undefined);
    getBriefSettings().then((r) => setBrief(r.settings)).catch(() => undefined);
    getReceptionKB().then((r) => setReception(r.kb)).catch(() => undefined);
  }, []);
  return (
    <div className="max-w-5xl px-5 py-5">
      <h1 className="mb-6 text-[15px] font-semibold text-foreground">设置</h1>
      {settings ? (
        <SettingsForm
          settings={settings}
          imageUrl={(name) => `/api/admin/intake/assets/${name}`}
          onSave={async (config) => {
            const r = await saveAdminSettings(config);
            setSettings({ ...settings, config: r.config });
          }}
          onContactWay={async (scene) => (await createContactWay(scene)).url}
        />
      ) : null}
      {brief ? (
        <section className="border-t pt-6" aria-labelledby="brief-settings-title">
          <h2 id="brief-settings-title" className="mb-3 text-base font-semibold text-foreground">
            需求卡（客人认领后点选、确认才开工）
          </h2>
          <BriefSettingsForm settings={brief} onSave={async (s) => setBrief((await saveBriefSettings(s)).settings)} />
        </section>
      ) : null}
      {reception ? (
        <section className="mt-8 border-t pt-6" aria-labelledby="reception-settings-title">
          <h2 id="reception-settings-title" className="mb-3 text-base font-semibold text-foreground">
            接待机器人（小鱼怎么认、怎么回、什么节奏）
          </h2>
          <ReceptionSettingsForm
            kb={reception}
            onSave={async (kb) => setReception((await saveReceptionKB(kb)).kb)}
            onTry={tryReception}
            onUploadSample={async (slot, file, title) => setReception((await uploadReceptionSample(slot, file, title)).kb)}
          />
        </section>
      ) : null}
    </div>
  );
}
