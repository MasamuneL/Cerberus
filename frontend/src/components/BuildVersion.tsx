const version = import.meta.env.VITE_CERBERUS_VERSION || "dev";
const revision = import.meta.env.VITE_CERBERUS_REVISION || "dev";

export default function BuildVersion() {
  return <small className="build-version" title={`Versión ${version}; commit ${revision}`}>
    Versión {version} · {revision === "dev" ? "dev" : revision.slice(0, 12)}
  </small>;
}
