import type { SegmentationResult } from "../api/types";

const value = (n: number | null | undefined, digits = 3) => n == null ? "—" : n.toFixed(digits);

export default function SegmentationMetrics({ result }: { result: SegmentationResult }) {
  const metrics = result.metrics_vs_gtv;
  return (
    <section aria-label="Métricas de segmentación">
      <h3>Métricas de concordancia con GTV</h3>
      <p className="note">
        Comparación de este estudio con la máscara GTV del dataset. GTV excluye edema;
        WT lo incluye y TC tampoco equivale necesariamente a GTV. Estos valores no validan
        por separado WT/TC/ET ni representan certeza clínica o rendimiento global del modelo.
      </p>
      {metrics || result.dice_vs_gtv ? (
        <table className="data-table">
          <caption>Predicción frente a GTV · estudio actual</caption>
          <thead><tr><th scope="col">Métrica</th><th scope="col">TC / GTV</th><th scope="col">WT / GTV</th></tr></thead>
          <tbody>
            <tr><th scope="row">Dice / F1</th><td>{value(metrics?.tc.dice ?? result.dice_vs_gtv?.tc)}</td><td>{value(metrics?.wt.dice ?? result.dice_vs_gtv?.wt)}</td></tr>
            <tr><th scope="row">Recall / sensibilidad</th><td>{value(metrics?.tc.recall)}</td><td>{value(metrics?.wt.recall)}</td></tr>
            <tr><th scope="row">Precisión / PPV</th><td>{value(metrics?.tc.precision)}</td><td>{value(metrics?.wt.precision)}</td></tr>
            <tr><th scope="row">HD95 (mm)</th><td>{value(metrics?.tc.hd95_mm, 2)}</td><td>{value(metrics?.wt.hd95_mm, 2)}</td></tr>
            <tr><th scope="row">Error de volumen (cm³)</th><td>{value(metrics?.tc.volume_error_cm3, 2)}</td><td>{value(metrics?.wt.volume_error_cm3, 2)}</td></tr>
            <tr><th scope="row">Error de volumen (%)</th><td>{value(metrics?.tc.volume_error_pct, 2)}</td><td>{value(metrics?.wt.volume_error_pct, 2)}</td></tr>
          </tbody>
        </table>
      ) : <p className="placeholder">Sin GTV: no se calculan métricas de referencia.</p>}
      {!metrics && result.dice_vs_gtv && (
        <p className="note">Resultado anterior: vuelve a segmentar para calcular las métricas adicionales.</p>
      )}
      <details>
        <summary>Cómo leer las métricas</summary>
        <ul>
          <li><strong>Dice / F1 (0–1):</strong> solapamiento entre máscaras. 1 indica coincidencia completa; 0, ninguna. 0.90 no significa 90 % de certeza.</li>
          <li><strong>Recall (0–1):</strong> fracción del GTV detectada. Un valor bajo indica más vóxeles de referencia omitidos.</li>
          <li><strong>Precisión (0–1):</strong> fracción de la predicción dentro del GTV. Un valor bajo indica más vóxeles predichos fuera de la referencia.</li>
          <li><strong>HD95 (mm):</strong> discrepancia de bordes: máximo de los percentiles 95 de las distancias en ambos sentidos. Menor es mejor; 0 indica bordes coincidentes.</li>
          <li><strong>Error de volumen:</strong> predicción menos GTV, en cm³ y como porcentaje del volumen GTV. Positivo: sobreestimación; negativo: subestimación; cerca de 0: volúmenes similares, aunque las máscaras podrían estar desalineadas.</li>
          <li><strong>—:</strong> dato no disponible o cálculo indefinido. Sin referencia positiva, recall y error porcentual no se definen; sin predicción positiva, precisión tampoco. HD95 requiere ambas máscaras no vacías. Dice vale 1 si ambas están vacías.</li>
          <li><strong>Accuracy:</strong> no se usa como indicador principal; el predominio del fondo puede producir valores altos aunque se omita la lesión.</li>
        </ul>
        <p className="note">Métricas calculadas por vóxel en un grid común de 1 mm, con umbral de probabilidad &gt; 0.5. No hay umbrales universales de aprobación; interpreta los valores junto a las imágenes y los avisos de canales faltantes.</p>
        <p className="note">Para evaluar el modelo completo hacen falta referencias compatibles, varios pacientes independientes, dispersión e intervalos de confianza. Un estudio aislado no demuestra generalización.</p>
      </details>
    </section>
  );
}
