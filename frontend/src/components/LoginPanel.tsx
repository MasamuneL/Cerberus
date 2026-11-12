import { useEffect, useRef } from "react";
import type { AuthControl } from "../hooks/useAuth";
import "./auth.css";
import BuildVersion from "./BuildVersion";

export default function LoginPanel({ auth }: { auth: AuthControl }) {
  const heading = useRef<HTMLHeadingElement>(null);
  const busy = auth.status === "loading" || auth.status === "signing_out";
  const title = auth.title ?? (auth.status === "expired" ? "Sesión expirada" : auth.status === "forbidden" ? "Sin permisos"
    : auth.status === "unavailable" ? "Servicio no disponible" : busy ? "Cerberus" : "Inicia sesión en Cerberus");
  const description = auth.message ?? (auth.status === "expired" ? "Vuelve a iniciar sesión para consultar los estudios."
    : auth.status === "forbidden" ? "Tu cuenta no tiene permisos de Cerberus. Solicita acceso al administrador de la demo."
    : auth.status === "unavailable" ? "No se pudo comprobar la sesión. Reintenta en unos momentos."
    : auth.status === "signing_out" ? "Cerrando sesión…" : busy ? "Comprobando sesión…" : "Explora estudios, volúmenes y reportes del dataset CFB-GBM.");
  useEffect(() => { if (!busy) heading.current?.focus(); }, [auth.status, busy]);
  return <main className="auth-page">
    <section className="auth-card" aria-labelledby="auth-heading" aria-describedby="auth-description" aria-busy={busy}>
      <BuildVersion />
      <p className="auth-brand">CERBERUS <span>Demo académica</span></p>
      <h1 id="auth-heading" ref={heading} tabIndex={-1}>{title}</h1>
      <p id="auth-description" role={busy ? "status" : undefined}>{description}</p>
      {!busy && <div className="auth-actions">
        <a className="auth-login" href="/api/auth/login">Iniciar sesión</a>
        {auth.canRetry && <button type="button" className="btn-secondary" onClick={auth.retry}>Reintentar</button>}
      </div>}
      <aside className="auth-help" aria-labelledby="auth-help-heading">
        <h2 id="auth-help-heading">Tu cuenta y tu sesión</h2>
        <p>Usa la cuenta que te proporcionó el administrador de la demo. Si no puedes entrar, solicita su ayuda.</p>
        <p>«Recordarme» conserva la sesión del proveedor en este navegador. Cerberus volverá a pedir tus credenciales al entrar y mantiene sus límites predeterminados: 30 minutos sin actividad y 60 minutos en total.</p>
      </aside>
    </section>
  </main>;
}
