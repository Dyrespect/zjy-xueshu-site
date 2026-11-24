/** 接待机器人知识库（后台「设置 → 接待机器人」；docs/任务单/12_接待机器人_设计.md 第三节）。字段和后端 app/intake/reception/kb.py 一一对应。 */

export interface ReceptionIntent {
  id: string;
  name: string;
  stage: string;
  desc: string;
  examples: string[];
  keywords: string[];
  decisive: boolean;
  reply: string;
  next: string;
  handoff: string;
  samples: string[];
}

export interface ReceptionAsk {
  key: string;
  label: string;
  say: string;
  markers: string[];
  max_times: number;
}

export interface ReceptionKB {
  version: number;
  disclosure: { text: string; window_days: number; web_footer: string };
  persona: { name: string; who: string; never: string };
  owner: { wechat: string; line: string; mute_after_handoff: boolean };
  style: {
    max_chars_per_msg: number;
    max_chars_per_turn: number;
    max_segments: Record<string, number>;
    banned: { text: string; why: string }[];
    banned_patterns: { pattern: string; why: string }[];
    fillers: string[];
  };
  rhythm: Record<string, number | string | string[] | [number, number]>;
  asks: ReceptionAsk[];
  intents: ReceptionIntent[];
  /** 样张（带水印的 PDF，后台上传可换；小鱼在聊天里发） */
  samples: ReceptionSample[];
  /** 想看样张时顺带说的那句（公众号每天的免费 PPT） */
  gzh_line: string;
}

export interface ReceptionSample {
  title: string;
  about: string;
  filename: string;
  size: number;
  ready?: boolean;
}

export interface ReceptionTry {
  intents: { id: string; name: string }[];
  how: string;
  answering: boolean;
  scores: { id: string; name: string; score: number }[];
  reply?: { text: string; after_s: number }[];
  problems?: string[];
}
