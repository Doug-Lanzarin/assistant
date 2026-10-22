export interface Source {
  owner_type?: string;
  owner_id?: number;
  title?: string;
  citation?: string;
  snippet?: string;
  status?: string;
  stale?: boolean;
}

export interface Action {
  status: string;
  tool: string;
  message: string;
  pending_id?: string | null;
  risk: number;
  data?: unknown;
  sources?: Source[];
}

export interface Pending {
  id: string;
  conversation_id: number | null;
  tool: string;
  summary: string;
  risk: number;
  created_at: string;
  expires_at: string;
}

export interface ChatReply {
  conversation_id: number;
  message_id?: number;
  text: string;
  actions: Action[];
  pending: Pending[];
  sources?: Source[];
  provider?: string;
  cancelled?: boolean;
}

export interface Message {
  id: number;
  conversation_id: number;
  role: "user" | "assistant" | "system" | "tool";
  content: string;
  meta: { provider?: string; actions?: Action[]; sources?: Source[]; origin?: string };
  created_at: string;
}

export interface Conversation {
  id: number;
  title: string;
  updated_at: string;
  messages: number;
}

export interface Memory {
  id: number;
  kind: string;
  kind_label: string;
  title: string;
  content: string;
  source: string;
  status: string;
  confidence: number;
  project_name: string | null;
  tags: string[];
  stale: boolean;
  sensitive: number;
  created_at: string;
  updated_at: string;
}

export interface SearchHit extends Source {
  kind: string;
  score: number;
  project?: string | null;
  created_at: string;
  category?: string;
}

export interface ClipItem {
  id: number;
  title: string;
  category: string;
  project_name: string | null;
  tags: string[];
  pinned: boolean;
  sensitive: boolean;
  char_count: number;
  copy_count: number;
  preview: string;
  content?: string;
  created_at: string;
  updated_at: string;
  last_copied_at: string | null;
  score?: number;
}

export interface Device {
  entity_id: string;
  name: string;
  aliases: string[];
  room: string | null;
  domain: string;
  last_state: string | null;
  attributes: Record<string, unknown>;
}

export interface Status {
  version: string;
  system: Record<string, number | boolean>;
  ai: { mode: string; providers: { name: string; model: string; remote: boolean; available: boolean; detail: string }[]; usage: Record<string, number> };
  agent: { connected: boolean; info: Record<string, unknown> };
  voice: { enabled: boolean; wake_word_enabled: boolean; wake_word: string; agent_voice: boolean };
  home: { configured: boolean; devices: number };
  whatsapp: { mode: string; can_read: boolean; can_send: boolean; detail: string; unread: number };
  kill_switch: boolean;
  pending_actions: number;
  tasks_pending: number;
  reminders: { id: number; text: string; due_at: string }[];
  recent_activity: { ts: string; tool: string; status: string; result_summary: string }[];
  running_tasks: number;
}

export type Settings = Record<string, Record<string, unknown>>;
