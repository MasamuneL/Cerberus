# Ejecución D3 · 2026-11-11

Rama de integración: feat/D3-simple-setup. Base: 0ddd560. Sin publicación ni merge autorizados.
Docker diario: no se recrea, detiene ni modifica. .omo/ preexistente se conserva.

## Avance

- D3a: 31684e9, contrato y generador. 19 tests de paquete/inicialización correctos.
- Revisión independiente D3a: carrera worker y Data sin permisos corregidas en distribución.
  Verificación de escritura no privilegiada pendiente de integración.
- D3b/D3c/D3e: agentes en worktrees /tmp/cerberus-D3b, D3c, D3e; propietarios en CONTRACT.md.

## Decisiones e interfaces

- Distribución se genera desde Compose existente para impedir divergencia; Compose del checkout intacto.
- Backend e inicializadores comparten digest; release.json format=1, version, revision, images.
- Datos persistentes en carpeta fija; migración conserva proyecto y resuelve montajes absolutos.
- Diagnóstico exporta códigos permitidos, jamás logs/entornos/rutas personales.
- La autorización del usuario exige paralelismo por worktrees y prevalece sobre ejecución secuencial
  sugerida por skills. No se publican candidatos ni releases durante esta sesión.

## Gates externos

Publicación/descarga GHCR anónima, pruebas Windows/Linux/macOS e inferencia con el artefacto final
requieren evidencia propia. No se considerarán aprobadas mediante tests unitarios ni YAML.
