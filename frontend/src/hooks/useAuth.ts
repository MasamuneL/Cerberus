import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, clearAuthContext, getAuthConfig, getAuthSession, logoutSession, setAuthContext } from "../api/client";
import type { AuthSession } from "../api/types";

export type AuthStatus = "loading" | "off" | "authenticated" | "anonymous" | "expired" | "forbidden" | "unavailable" | "signing_out";
interface AuthState { status: AuthStatus; session: AuthSession | null; message?: string }

/** Sesión opaca en cookie; React conserva únicamente roles, vencimiento y CSRF en memoria. */
export function useAuth() {
  const [state, setState] = useState<AuthState>({ status: "loading", session: null });
  const [returnedError] = useState(() => new URL(location.href).searchParams.get("auth_error"));
  const mounted = useRef(false);
  const checking = useRef<AbortController | null>(null);
  const current = useRef<AuthSession | null>(null);
  const logoutToken = useRef<string | null>(null);
  const lastChecked = useRef(0);

  const expire = useCallback(() => {
    clearAuthContext();
    current.current = null;
    logoutToken.current = null;
    if (mounted.current) setState({ status: "expired", session: null });
  }, []);

  const readSession = useCallback(async (signal: AbortSignal, wasAuthenticated: boolean) => {
    try {
      const session = await getAuthSession(signal);
      if (signal.aborted || !mounted.current) return;
      if (!session.roles.length || !session.roles.every(role => role === "reader" || role === "analyst") || !session.csrf_token || !Number.isFinite(Date.parse(session.expires_at))) {
        throw new Error("Respuesta de sesión inválida");
      }
      lastChecked.current = Date.now();
      current.current = session;
      setAuthContext(session.csrf_token, expire);
      setState({ status: "authenticated", session });
    } catch (error) {
      if (signal.aborted || !mounted.current) return;
      clearAuthContext();
      current.current = null;
      const status: AuthStatus = error instanceof ApiError && error.status === 401
        ? (wasAuthenticated ? "expired" : "anonymous")
        : error instanceof ApiError && error.status === 403 ? "forbidden" : "unavailable";
      setState({ status, session: null });
    }
  }, [expire]);

  const initialize = useCallback(async (showReturnedError = false) => {
    checking.current?.abort();
    const controller = new AbortController();
    checking.current = controller;
    clearAuthContext();
    current.current = null;
    logoutToken.current = null;
    setState({ status: "loading", session: null });
    try {
      const config = await getAuthConfig(controller.signal);
      if (controller.signal.aborted || !mounted.current) return;
      if (config.mode === "off") {
        setState({ status: "off", session: null });
        return;
      }
      if (config.mode !== "oidc") throw new Error("Modo de autenticación inválido");
      if (showReturnedError && ["forbidden", "failed", "unavailable"].includes(returnedError ?? "")) {
        setState({ status: returnedError === "forbidden" ? "forbidden" : returnedError === "unavailable" ? "unavailable" : "anonymous", session: null,
          message: returnedError === "failed" ? "No se pudo completar el inicio de sesión. Inténtalo de nuevo." : undefined });
        return;
      }
      await readSession(controller.signal, false);
    } catch {
      if (!controller.signal.aborted && mounted.current) setState({ status: "unavailable", session: null });
    }
  }, [readSession, returnedError]);

  const checkSession = useCallback(() => {
    checking.current?.abort();
    const controller = new AbortController();
    checking.current = controller;
    void readSession(controller.signal, true);
  }, [readSession]);

  const logout = useCallback(async () => {
    const token = logoutToken.current ?? current.current?.csrf_token;
    if (!token) return;
    logoutToken.current = token;
    current.current = null;
    checking.current?.abort();
    clearAuthContext();
    setState({ status: "signing_out", session: null });
    try {
      await logoutSession(token);
    } catch (error) {
      if (!(error instanceof ApiError && error.status === 401)) {
        if (mounted.current) setState({ status: "unavailable", session: null, message: "No se pudo confirmar el cierre de sesión. Reintenta para completarlo." });
        return;
      }
    }
    logoutToken.current = null;
    if (mounted.current) setState({ status: "anonymous", session: null, message: "Sesión cerrada." });
  }, []);

  useEffect(() => {
    mounted.current = true;
    const url = new URL(location.href);
    if (url.searchParams.has("auth_error")) {
      url.searchParams.delete("auth_error");
      history.replaceState(null, "", url.pathname + url.search + url.hash);
    }
    void initialize(true);
    return () => {
      mounted.current = false;
      checking.current?.abort();
      clearAuthContext();
    };
  }, [initialize]);

  useEffect(() => {
    if (state.status !== "authenticated" || !state.session) return;
    // Comprobar después del vencimiento evita que un sondeo temprano mantenga viva una sesión inactiva.
    const delay = Math.max(0, Date.parse(state.session.expires_at) - Date.now()) + 250;
    const timer = window.setTimeout(checkSession, Math.min(delay, 2_000_000_000));
    const onFocus = () => {
      if (document.visibilityState === "visible" && Date.now() - lastChecked.current >= 60_000) checkSession();
    };
    window.addEventListener("focus", onFocus);
    document.addEventListener("visibilitychange", onFocus);
    return () => {
      clearTimeout(timer);
      window.removeEventListener("focus", onFocus);
      document.removeEventListener("visibilitychange", onFocus);
    };
  }, [state, checkSession]);

  return { ...state, canAnalyze: state.status === "off" || !!state.session?.roles.includes("analyst"),
    logout, retry: () => logoutToken.current ? void logout() : void initialize() };
}

export type AuthControl = ReturnType<typeof useAuth>;
