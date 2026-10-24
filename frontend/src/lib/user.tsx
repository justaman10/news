import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import type { Session } from "@supabase/supabase-js";
import { siteConfig } from "./api";
import { configured, supabase } from "./supabase";
import type { CategoryInfo, Prefs, Story } from "./types";

// Signed out, everything lives in this browser. Signed in, the database is the
// source of truth and every device sees the same preferences, bookmarks and history.

const FALLBACK_PREFS: Prefs = {
  categories: {}, countries: [], industries: [], sports: [], teams: [], leagues: [],
  interview_roles: [], extra_interests: "",
};

type BookmarkRow = { story_id: number; created_at: string; story?: Story };
type HistoryRow = { story_id: number; read_at: string; story?: Story };

interface UserState {
  session: Session | null;
  categories: CategoryInfo[];
  prefs: Prefs;
  savePrefs: (p: Prefs) => Promise<void>;
  bookmarks: BookmarkRow[];
  isBookmarked: (id: number) => boolean;
  toggleBookmark: (id: number) => Promise<void>;
  history: HistoryRow[];
  hasRead: (id: number) => boolean;
  markRead: (id: number) => void;
  known: Set<string>;
  toggleKnown: (key: string) => Promise<void>;
  signIn: (email: string, password: string) => Promise<string | null>;
  signUp: (email: string, password: string) => Promise<string | null>;
  signOut: () => Promise<void>;
  syncError: string | null;
}

const Ctx = createContext<UserState | null>(null);

function local<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(`db:${key}`);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}

function saveLocal(key: string, value: unknown) {
  try {
    localStorage.setItem(`db:${key}`, JSON.stringify(value));
  } catch {
    /* private mode or storage full: the in-memory state still works */
  }
}

export function mergePrefs(defaults: Prefs, saved: Partial<Prefs> | null | undefined): Prefs {
  const out: Prefs = { ...FALLBACK_PREFS, ...defaults, categories: { ...(defaults?.categories ?? {}) } };
  for (const [k, v] of Object.entries(saved ?? {})) {
    if (k === "categories" && v && typeof v === "object") {
      for (const [slug, cfg] of Object.entries(v as Prefs["categories"])) {
        out.categories[slug] = { ...out.categories[slug], ...cfg };
      }
    } else if (v !== null && v !== undefined && v !== "") {
      (out as unknown as Record<string, unknown>)[k] = v;
    }
  }
  return out;
}

const STORY_BRIEF = "id, headline, category, image_url, summary, published_at, edition:editions(edition_date)";

export function UserProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [categories, setCategories] = useState<CategoryInfo[]>(local("categories", []));
  const [defaults, setDefaults] = useState<Prefs>(local("default_prefs", FALLBACK_PREFS));
  const [saved, setSaved] = useState<Partial<Prefs> | null>(local("prefs", null));
  const [bookmarks, setBookmarks] = useState<BookmarkRow[]>(local("bookmarks", []));
  const [history, setHistory] = useState<HistoryRow[]>(local("history", []));
  const [known, setKnown] = useState<Set<string>>(new Set(local<string[]>("known", [])));
  const [syncError, setSyncError] = useState<string | null>(null);

  useEffect(() => {
    if (!configured) return;
    siteConfig().then((cfg) => {
      setCategories(cfg.categories);
      saveLocal("categories", cfg.categories);
      if (cfg.default_prefs) {
        setDefaults(cfg.default_prefs);
        saveLocal("default_prefs", cfg.default_prefs);
      }
    }).catch(() => undefined);
    supabase.auth.getSession().then(({ data }) => setSession(data.session));
    const { data } = supabase.auth.onAuthStateChange((_event, s) => setSession(s));
    return () => data.subscription.unsubscribe();
  }, []);

  const uid = session?.user.id;

  // On sign-in: upload anything collected while signed out, then load the account's data.
  useEffect(() => {
    if (!uid) return;
    (async () => {
      try {
        const localBookmarks = local<BookmarkRow[]>("bookmarks", []);
        const localHistory = local<HistoryRow[]>("history", []);
        const localKnown = local<string[]>("known", []);
        const localPrefs = local<Partial<Prefs> | null>("prefs", null);
        if (localBookmarks.length)
          await supabase.from("bookmarks").upsert(localBookmarks.map((b) => ({ user_id: uid, story_id: b.story_id })), { ignoreDuplicates: true });
        if (localHistory.length)
          await supabase.from("reading_history").upsert(localHistory.map((h) => ({ user_id: uid, story_id: h.story_id, read_at: h.read_at })));
        if (localKnown.length)
          await supabase.from("prep_known").upsert(localKnown.map((k) => ({ user_id: uid, item_key: k })), { ignoreDuplicates: true });

        const [p, b, h, k] = await Promise.all([
          supabase.from("profiles").select("prefs").eq("user_id", uid).maybeSingle(),
          supabase.from("bookmarks").select(`story_id, created_at, story:stories(${STORY_BRIEF})`).order("created_at", { ascending: false }),
          supabase.from("reading_history").select(`story_id, read_at, story:stories(${STORY_BRIEF})`).order("read_at", { ascending: false }).limit(200),
          supabase.from("prep_known").select("item_key"),
        ]);
        for (const r of [p, b, h, k]) if (r.error) throw new Error(r.error.message);
        let accountPrefs = (p.data?.prefs as Partial<Prefs>) ?? null;
        if (!accountPrefs && localPrefs) {
          await supabase.from("profiles").upsert({ user_id: uid, prefs: localPrefs, updated_at: new Date().toISOString() });
          accountPrefs = localPrefs;
        }
        setSaved(accountPrefs);
        setBookmarks((b.data ?? []) as unknown as BookmarkRow[]);
        setHistory((h.data ?? []) as unknown as HistoryRow[]);
        setKnown(new Set((k.data ?? []).map((r: { item_key: string }) => r.item_key)));
        for (const key of ["bookmarks", "history", "known", "prefs"]) localStorage.removeItem(`db:${key}`);
        setSyncError(null);
      } catch (e) {
        setSyncError((e as Error).message);
      }
    })();
  }, [uid]);

  const prefs = useMemo(() => mergePrefs(defaults, saved), [defaults, saved]);

  const savePrefs = useCallback(async (p: Prefs) => {
    setSaved(p);
    if (uid) {
      const { error } = await supabase.from("profiles").upsert({ user_id: uid, prefs: p, updated_at: new Date().toISOString() });
      setSyncError(error?.message ?? null);
      if (error) throw new Error(error.message);
    } else saveLocal("prefs", p);
  }, [uid]);

  const toggleBookmark = useCallback(async (id: number) => {
    const exists = bookmarks.some((b) => b.story_id === id);
    const next = exists ? bookmarks.filter((b) => b.story_id !== id)
      : [{ story_id: id, created_at: new Date().toISOString() }, ...bookmarks];
    setBookmarks(next);
    if (uid) {
      const { error } = exists
        ? await supabase.from("bookmarks").delete().eq("user_id", uid).eq("story_id", id)
        : await supabase.from("bookmarks").insert({ user_id: uid, story_id: id });
      setSyncError(error?.message ?? null);
      if (!exists && !error) {
        const { data } = await supabase.from("stories").select(STORY_BRIEF).eq("id", id).maybeSingle();
        if (data) setBookmarks((cur) => cur.map((b) => (b.story_id === id ? { ...b, story: data as unknown as Story } : b)));
      }
    } else saveLocal("bookmarks", next);
  }, [bookmarks, uid]);

  const markRead = useCallback((id: number) => {
    const row = { story_id: id, read_at: new Date().toISOString() };
    setHistory((cur) => {
      const next = [row, ...cur.filter((h) => h.story_id !== id)].slice(0, 300);
      if (!uid) saveLocal("history", next);
      return next;
    });
    if (uid) {
      supabase.from("reading_history").upsert({ user_id: uid, ...row }).then(({ error }) => {
        if (error) setSyncError(error.message);
        else supabase.from("stories").select(STORY_BRIEF).eq("id", id).maybeSingle().then(({ data }) => {
          if (data) setHistory((cur) => cur.map((h) => (h.story_id === id ? { ...h, story: data as unknown as Story } : h)));
        });
      });
    }
  }, [uid]);

  const toggleKnown = useCallback(async (key: string) => {
    const next = new Set(known);
    const had = next.has(key);
    had ? next.delete(key) : next.add(key);
    setKnown(next);
    if (uid) {
      const { error } = had
        ? await supabase.from("prep_known").delete().eq("user_id", uid).eq("item_key", key)
        : await supabase.from("prep_known").insert({ user_id: uid, item_key: key });
      setSyncError(error?.message ?? null);
    } else saveLocal("known", [...next]);
  }, [known, uid]);

  const value: UserState = {
    session, categories, prefs, savePrefs, bookmarks, history, known, syncError,
    isBookmarked: (id) => bookmarks.some((b) => b.story_id === id),
    toggleBookmark,
    hasRead: (id) => history.some((h) => h.story_id === id),
    markRead,
    toggleKnown,
    signIn: async (email, password) => (await supabase.auth.signInWithPassword({ email, password })).error?.message ?? null,
    signUp: async (email, password) => {
      const { data, error } = await supabase.auth.signUp({ email, password });
      if (error) return error.message;
      return data.session ? null : "Check your inbox to confirm your email, then sign in here.";
    },
    signOut: async () => {
      await supabase.auth.signOut();
      setBookmarks([]); setHistory([]); setKnown(new Set()); setSaved(null);
    },
  };
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useUser(): UserState {
  const v = useContext(Ctx);
  if (!v) throw new Error("useUser outside UserProvider");
  return v;
}

/** Categories ordered by the reader's weights (hidden ones last). */
export function orderedCategories(categories: CategoryInfo[], prefs: Prefs): CategoryInfo[] {
  const w = (slug: string) => prefs.categories[slug]?.weight ?? 2;
  return [...categories].sort((a, b) => w(b.slug) - w(a.slug));
}

export function followTerms(prefs: Prefs): string[] {
  return [...prefs.countries, ...prefs.teams, ...prefs.industries, ...prefs.leagues]
    .map((t) => t.replace(/\(.*?\)/g, "").trim().toLowerCase())
    .filter((t) => t.length > 2);
}
