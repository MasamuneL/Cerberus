import { useEffect, useRef } from "react";
import type { AuthControl } from "../hooks/useAuth";
import "./auth.css";

export default function LoginPanel({ auth }: { auth: AuthControl }) {
  const heading = useRef<HTMLHeadingElement>(null);
  const busy = auth.status === "loading" || auth.status === "signing_out";
  const title = auth.status === "expired" ? "Sesión expirada" : auth.status === "forbidden" ? "Sin permisos"
    : auth.status === "unavailable" ? "Servicio no disponible" : busy ? "Cerberus" : "Inicia sesión en Cerberus";
  const description = auth.message ?? (auth.status === "expired" ? "Vuelve a iniciar sesión para consultar los estudios."
    : auth.status === "forbidden" ? "Tu cuenta no tiene permisos de Cerberus. Solicita acceso al administrador de la demo."
    : auth.status === "unavailable" ? "No se pudo comprobar la sesión. Reintenta en unos momentos."
    : auth.status === "signing_out" ? "Cerrando sesión…" : busy ? "Comprobando sesión…" : "Explora estudios, volúmenes y reportes del dataset CFB-GBM.");
  useEffect(() => { if (!busy) heading.current?.focus(); }, [auth.status, busy]);
  return <main className="auth-page">
    <section className="auth-card" aria-labelledby="auth-heading">
      <p className="auth-brand">CERBERUS</p>
      <h1 id="auth-heading" ref={heading} tabIndex={-1}>{title}</h1>
      <p role={busy ? "status" : undefined}>{description}</p>
      {!busy && <div className="auth-actions">
        <a className="auth-login" href="/api/auth/login">Iniciar sesión</a>
        {auth.status === "unavailable" && <button type="button" className="btn-secondary" onClick={auth.retry}>Reintentar</button>}
      </div>}
    </section>
  </main>;
}
