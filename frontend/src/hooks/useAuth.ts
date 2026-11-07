import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, clearAuthContext, getAuthConfig, getAuthSession, logoutSession, RequestTimeoutError, setAuthContext } from "../api/client";
import type { AuthSession } from "../api/types";

export type AuthStatus = "loading" | "off" | "authenticated" | "anonymous" | "expired" | "forbidden" | "unavailable" | "signing_out";
interface AuthState { status: AuthStatus; session: AuthSession | null; message?: string; title?: string }
type SessionEvent = "session-changed" | "session-cleared";
const WARNING_MS = 60_000;

/** Sesión opaca en cookie; React conserva únicamente roles, vencimiento y CSRF en memoria. */
export function useAuth() {
  const [state, setState] = useState<AuthState>({ status: "loading", session: null });
  const [warning, setWarning] = useState(false);
  const [returnedError] = useState(() => new URL(location.href).searchParams.get("auth_error"));
  const [returnedLogin] = useState(() => new URL(location.href).searchParams.get("auth_event") === "login");
  const mounted = useRef(false);
  const checking = useRef<AbortController | null>(null);
  const current = useRef<AuthSession | null>(null);
  const logoutToken = useRef<string | null>(null);
  const channel = useRef<BroadcastChannel | null>(null);
  const mode = useRef<"off" | "oidc" | null>(null);
  const signingOut = useRef(false);

  const broadcast = useCallback((type: SessionEvent) => {
    channel.current?.postMessage({ type });
  }, []);

  const expire = useCallback(() => {
    checking.current?.abort();
    clearAuthContext();
    current.current = null;
    logoutToken.current = null;
    signingOut.current = false;
    setWarning(false);
    if (mounted.current) setState({ status: "expired", session: null });
  }, []);

  const updateExpiry = useCallback((expiresAt: number) => {
    const session = current.current;
    if (!session || !mounted.current || !Number.isFinite(expiresAt) || expiresAt <= 0 || expiresAt > 8.64e15) return;
    const expires_at = new Date(expiresAt).toISOString();
    if (expiresAt <= Date.parse(session.expires_at)) return;
    const updated = { ...session, expires_at };
    current.current = updated;
    setState(previous => previous.status === "authenticated" ? { ...previous, session: updated } : previous);
  }, []);

  const readSession = useCallback(async (signal: AbortSignal, wasAuthenticated: boolean, notify = false) => {
    try {
      const session = await getAuthSession(signal);
      if (signal.aborted || !mounted.current) return;
      if (!session.roles.length || !session.roles.every(role => role === "reader" || role === "analyst") || !session.csrf_token || !Number.isFinite(Date.parse(session.expires_at))) {
        throw new Error("Respuesta de sesión inválida");
      }
      current.current = session;
      setAuthContext(session.csrf_token, expire, updateExpiry);
      setState({ status: "authenticated", session });
      if (notify) broadcast("session-changed");
    } catch (error) {
      if (signal.aborted || !mounted.current) return;
      clearAuthContext();
      current.current = null;
      const status: AuthStatus = error instanceof ApiError && error.status === 401
        ? (wasAuthenticated ? "expired" : "anonymous")
        : error instanceof ApiError && error.status === 403 ? "forbidden" : "unavailable";
      setState({ status, session: null, message: error instanceof RequestTimeoutError ? error.message : undefined });
    }
  }, [broadcast, expire, updateExpiry]);

  const initialize = useCallback(async (showReturnedError = false) => {
    checking.current?.abort();
    clearAuthContext();
    const controller = new AbortController();
    checking.current = controller;
    current.current = null;
    logoutToken.current = null;
    signingOut.current = false;
    setWarning(false);
    setState({ status: "loading", session: null });
    try {
      const config = await getAuthConfig(controller.signal);
      if (controller.signal.aborted || !mounted.current) return;
      if (config.mode === "off") {
        mode.current = "off";
        setState({ status: "off", session: null });
        return;
      }
      if (config.mode !== "oidc") throw new Error("Modo de autenticación inválido");
      mode.current = "oidc";
      if (showReturnedError && ["forbidden", "failed", "unavailable"].includes(returnedError ?? "")) {
        setState({ status: returnedError === "forbidden" ? "forbidden" : returnedError === "unavailable" ? "unavailable" : "anonymous", session: null,
          message: returnedError === "failed" ? "No se pudo completar el inicio de sesión. Inténtalo de nuevo." : undefined });
        return;
      }
      await readSession(controller.signal, false, showReturnedError && returnedLogin);
    } catch (error) {
      if (!controller.signal.aborted && mounted.current) setState({ status: "unavailable", session: null,
        message: error instanceof RequestTimeoutError ? error.message : undefined });
    }
  }, [readSession, returnedError, returnedLogin]);

  const checkSession = useCallback(() => {
    const wasAuthenticated = current.current !== null;
    checking.current?.abort();
    clearAuthContext();
    const controller = new AbortController();
    checking.current = controller;
    current.current = null;
    logoutToken.current = null;
    signingOut.current = false;
    setWarning(false);
    // Una cookie compartida puede pertenecer a otra cuenta: retirar datos antes de consultar /me.
    setState({ status: "loading", session: null });
    void readSession(controller.signal, wasAuthenticated);
  }, [readSession]);

  const logout = useCallback(async () => {
    const token = logoutToken.current ?? current.current?.csrf_token;
    if (!token || signingOut.current) return;
    signingOut.current = true;
    logoutToken.current = token;
    current.current = null;
    checking.current?.abort();
    clearAuthContext();
    const controller = new AbortController();
    checking.current = controller;
    setWarning(false);
    setState({ status: "signing_out", session: null });
    try {
      await logoutSession(token, controller.signal);
    } catch (error) {
      if (controller.signal.aborted || !mounted.current) return;
      if (!(error instanceof ApiError && error.status === 401)) {
        signingOut.current = false;
        const forbidden = error instanceof ApiError && error.status === 403;
        setState({ status: forbidden ? "forbidden" : "unavailable", session: null,
          title: forbidden ? "No se pudo cerrar sesión" : undefined,
          message: forbidden ? "No se pudo autorizar el cierre de sesión. Reintenta para comprobar la sesión vigente."
            : "No se pudo confirmar el cierre de sesión. Reintenta para completarlo." });
        return;
      }
    }
    if (controller.signal.aborted || !mounted.current) return;
    signingOut.current = false;
    logoutToken.current = null;
    broadcast("session-cleared");
    setState({ status: "anonymous", session: null, message: "Sesión cerrada." });
  }, [broadcast]);

  useEffect(() => {
    mounted.current = true;
    if (typeof BroadcastChannel !== "undefined") {
      const connection = new BroadcastChannel("cerberus.auth");
      channel.current = connection;
      connection.onmessage = (event: MessageEvent<unknown>) => {
        if (mode.current !== "oidc" || !event.data || typeof event.data !== "object") return;
        const payload = event.data as { type?: unknown };
        if (Object.keys(payload).length !== 1) return;
        // Los eventos recibidos nunca se retransmiten ni llevan identidad o credenciales.
        if (payload.type === "session-cleared") expire();
        else if (payload.type === "session-changed") checkSession();
      };
    }
    const url = new URL(location.href);
    if (url.searchParams.has("auth_error") || url.searchParams.has("auth_event")) {
      url.searchParams.delete("auth_error");
      url.searchParams.delete("auth_event");
      history.replaceState(null, "", url.pathname + url.search + url.hash);
    }
    void initialize(true);
    return () => {
      mounted.current = false;
      checking.current?.abort();
      clearAuthContext();
      channel.current?.close();
      channel.current = null;
    };
  }, [checkSession, expire, initialize]);

  useEffect(() => {
    if (state.status !== "authenticated" || !state.session) return;
    const remaining = Date.parse(state.session.expires_at) - Date.now();
    setWarning(remaining <= WARNING_MS);
    const warningTimer = window.setTimeout(() => setWarning(true), Math.max(0, remaining - WARNING_MS));
    // Caducar localmente no renueva idle. Solo una acción explícita del usuario consulta /me.
    const expiryTimer = window.setTimeout(expire, Math.max(0, remaining));
    return () => {
      clearTimeout(warningTimer);
      clearTimeout(expiryTimer);
    };
  }, [state.status, state.session?.expires_at, expire]);

  return { ...state, canAnalyze: state.status === "off" || !!state.session?.roles.includes("analyst"),
    warning, canRetry: ["expired", "forbidden", "unavailable"].includes(state.status),
    refresh: checkSession, logout, retry: () => logoutToken.current ? void logout() : void initialize() };
}

export type AuthControl = ReturnType<typeof useAuth>;
