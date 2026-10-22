import { useCallback, useEffect, useRef, useState } from "react";
import { request } from "../services/api";
import { events, type JarvisEvent } from "../services/events";

export function useApi<T>(path: string | null, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(!!path);
  const seq = useRef(0);

  const reload = useCallback(async () => {
    if (!path) return;
    const id = ++seq.current;
    setLoading(true);
    try {
      const d = await request<T>(path);
      if (id === seq.current) {
        setData(d);
        setError(null);
      }
    } catch (e) {
      if (id === seq.current) setError((e as Error).message);
    } finally {
      if (id === seq.current) setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, ...deps]);

  useEffect(() => {
    void reload();
  }, [reload]);

  return { data, error, loading, reload, setData };
}

export function useEvents(handler: (ev: JarvisEvent) => void, types?: string[]) {
  const ref = useRef(handler);
  ref.current = handler;
  const key = types?.join(",") ?? "";
  useEffect(() => {
    const filter = key ? new Set(key.split(",")) : null;
    return events.subscribe((ev) => {
      if (!filter || filter.has(ev.type)) ref.current(ev);
    });
  }, [key]);
}

export function useInterval(fn: () => void, ms: number) {
  const ref = useRef(fn);
  ref.current = fn;
  useEffect(() => {
    const id = setInterval(() => ref.current(), ms);
    return () => clearInterval(id);
  }, [ms]);
}
