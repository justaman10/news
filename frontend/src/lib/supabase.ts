import { createClient, type SupabaseClient } from "@supabase/supabase-js";

const url = import.meta.env.VITE_SUPABASE_URL as string | undefined;
const anonKey = import.meta.env.VITE_SUPABASE_ANON_KEY as string | undefined;

export const configured = Boolean(url && anonKey);

// The anon key is designed to be public: row level security decides what it can read.
export const supabase: SupabaseClient = createClient(
  url || "http://localhost:54321",
  anonKey || "not-configured",
  { auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: true } },
);
