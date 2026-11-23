# app.py
from pathlib import Path
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from scipy.signal import find_peaks, savgol_filter
from scipy.spatial import ConvexHull
from src.loaders import load_spectrum
import streamlit as st

from nist_lines import get_nist_dataframe, match_peaks

st.set_page_config(page_title="TecSpec | Multi-Spectral Analyzer", layout="wide")


# --- UTILIDADES DE CARGA LOCAL Y PROCESAMIENTO ---
class LocalFileWrapper:
  """Adapta un archivo local (Path) para que sea compatible con load_spectrum."""

  def __init__(self, path: Path):
    self.path = path
    self.name = path.name

  def getvalue(self) -> bytes:
    return self.path.read_bytes()


def discover_sample_spectra(base_dir: Path) -> dict:
  """Escanea data/sample_spectra/ buscando muestras de LIBS, USGS y HIDSAG."""
  samples = {}
  if not base_dir.exists():
    return samples

  # Mapa insensible a mayúsculas/minúsculas para las subcarpetas
  subdirs = {p.name.lower(): p for p in base_dir.iterdir() if p.is_dir()}

  # 1. Muestras LIBS (.csv / .txt)
  if "libs" in subdirs:
    for f in sorted(subdirs["libs"].iterdir()):
      if f.is_file() and f.suffix.lower() in (".csv", ".txt"):
        samples[f"LIBS | {f.name}"] = {
            "file": f,
            "wl_file": None,
            "default_mode": "LIBS (Emisión Atómica)",
        }

  # 2. Muestras USGS (.txt + emparejamiento automático de Wavelengths)
  if "usgs" in subdirs:
    usgs_txts = [
        f
        for f in sorted(subdirs["usgs"].iterdir())
        if f.is_file() and f.suffix.lower() == ".txt"
    ]
    wl_files = [f for f in usgs_txts if "wavelength" in f.name.lower()]
    spec_files = [f for f in usgs_txts if "wavelength" not in f.name.lower()]
    default_wl = wl_files[0] if wl_files else None

    for f in spec_files:
      samples[f"USGS | {f.name}"] = {
          "file": f,
          "wl_file": default_wl,
          "default_mode": "Reflectancia (VNIR-SWIR)",
      }

  # 3. Muestras HIDSAG (.h5 / .hdf5)
  if "hidsag" in subdirs:
    for f in sorted(subdirs["hidsag"].iterdir()):
      if f.is_file() and f.suffix.lower() in (".h5", ".hdf5", ".hdf"):
        samples[f"HIDSAG | {f.name}"] = {
            "file": f,
            "wl_file": None,
            "default_mode": "Reflectancia (VNIR-SWIR)",
        }

  return samples


def continuum_removal(x, y):
  """Calcula la envolvente superior (convex hull) y divide el espectro (Reflectancia / Continuo)."""
  points = np.column_stack((x, y))
  y_min = np.min(y) - 1.0
  extended = np.vstack(([x[0], y_min], points, [x[-1], y_min]))
  hull = ConvexHull(extended)
  upper_idx = sorted(
      [v - 1 for v in hull.vertices if 0 < v < len(extended) - 1]
  )
  continuum = np.interp(x, x[upper_idx], y[upper_idx])
  return (
      np.divide(y, continuum, out=np.ones_like(y), where=continuum > 1e-9),
      continuum,
  )


# --- CABECERA ---
st.title("🔬 TecSpec | Multi-Spectral Mineral Analyzer")
st.caption(
    "Procesamiento y análisis espectral compatible con LIBS (NIST), USGS"
    " splib07a y HIDSAG (HDF5)"
)

# Descubrir ejemplos integrados en el repositorio
SAMPLE_DIR = Path(__file__).resolve().parent / "data" / "sample_spectra"
available_samples = discover_sample_spectra(SAMPLE_DIR)

if "analysis_mode" not in st.session_state:
  st.session_state["analysis_mode"] = "LIBS (Emisión Atómica)"

active_file = None
active_wl_file = None

# --- BARRA LATERAL ---
with st.sidebar:
  st.header("1. Carga de Espectro")

  source_options = (
      ["Ejemplo integrado (Demo)", "Subir archivo propio"]
      if available_samples
      else ["Subir archivo propio"]
  )
  data_source = st.radio("Origen de datos", options=source_options)

  if data_source == "Ejemplo integrado (Demo)":
    selected_sample = st.selectbox(
        "Selecciona un espectro de prueba",
        options=list(available_samples.keys()),
    )
    sample_info = available_samples[selected_sample]
    active_file = LocalFileWrapper(sample_info["file"])
    active_wl_file = (
        LocalFileWrapper(sample_info["wl_file"])
        if sample_info["wl_file"] is not None
        else None
    )

    # Cambiar modo automáticamente solo cuando el usuario elige otro ejemplo
    if st.session_state.get("last_selected_sample") != selected_sample:
      st.session_state["last_selected_sample"] = selected_sample
      st.session_state["analysis_mode"] = sample_info["default_mode"]
  else:
    st.session_state["last_selected_sample"] = None
    active_file = st.file_uploader(
        "Archivo espectral (.csv, .txt, .h5, .hdf5)",
        type=["csv", "txt", "h5", "hdf5", "hdf"],
    )
    active_wl_file = st.file_uploader(
        "Opcional: Archivo Wavelengths USGS (.txt)",
        type=["txt"],
        help=(
            "Solo necesario si subes un .txt de 1 columna de USGS splib07a (ej."
            " BECK) para graficar en µm."
        ),
    )

  st.header("2. Modo de Análisis")
  analysis_mode = st.radio(
      "Tipo de Espectroscopía",
      options=["LIBS (Emisión Atómica)", "Reflectancia (VNIR-SWIR)"],
      key="analysis_mode",
  )

  st.header("3. Preprocesamiento")
  apply_smoothing = st.checkbox("Filtro Savitzky-Golay", value=True)
  window_length = st.slider("Ventana Suavizado", 5, 51, 11, 2)
  polyorder = st.slider("Orden Polinomio", 1, 4, 2)

  if analysis_mode == "LIBS (Emisión Atómica)":
    apply_baseline = st.checkbox("Sustracción de Continuo (Plasma)", value=True)
    baseline_window = st.slider("Ventana de Fondo (rolling min)", 20, 400, 150, 10)

    st.header("4. Detección de Picos e Identificación NIST")
    peak_prominence = st.slider("Prominencia Mínima", 10.0, 500.0, 80.0, 10.0)
    peak_distance = st.slider("Distancia Mínima (pts)", 1, 50, 5)
    nist_tolerance = st.slider("Tolerancia ± nm", 0.05, 0.50, 0.25, 0.01)

    df_nist_all = get_nist_dataframe()
    available_elements = sorted(df_nist_all["element"].unique())
    selected_elements = st.multiselect(
        "Elementos de Interés",
        options=available_elements,
        default=["Cu", "Fe", "Si", "Al", "Ca"],
    )
    show_nist_lines = st.checkbox(
        "Superponer líneas de referencia NIST", value=True
    )
  else:
    apply_cr = st.checkbox("Remoción de Continuo (Convex Hull)", value=True)
    st.header("4. Detección de Bandas de Absorción")
    dip_prominence = st.slider(
        "Profundidad Mínima de Absorción",
        min_value=0.001,
        max_value=0.300,
        value=0.005,
        step=0.001,
        format="%.3f",
    )
    dip_distance = st.slider("Distancia Mínima entre Bandas (pts)", 1, 50, 10)

# --- PROCESAMIENTO PRINCIPAL ---
if active_file is not None:
  try:
    spec = load_spectrum(active_file, usgs_wl_file=active_wl_file)
  except Exception as e:
    st.error(f"Error al leer el archivo: {e}")
    st.stop()

  x = spec["x"]
  y_raw = spec["y"]

  st.info(f"**Formato detectado:** {spec['format']} — {spec['meta']}")
  if spec["suggested_mode"] != analysis_mode:
    st.warning(
        f"Este archivo parece ser de tipo **{spec['suggested_mode']}**, pero"
        f" tienes activo **{analysis_mode}**. Puedes cambiarlo en la barra"
        " lateral."
    )

  eff_window = min(
      window_length, len(y_raw) if len(y_raw) % 2 == 1 else len(y_raw) - 1
  )

  # =========================================================================
  # MODO 1: LIBS (EMISIÓN ATÓMICA + NIST)
  # =========================================================================
  if analysis_mode == "LIBS (Emisión Atómica)":
    y_proc = y_raw.copy()

    if apply_baseline:
      baseline = (
          pd.Series(y_proc)
          .rolling(baseline_window, center=True, min_periods=1)
          .min()
          .to_numpy()
      )
      y_proc = np.maximum(y_proc - baseline, 0)

    if apply_smoothing and eff_window > polyorder:
      y_proc = savgol_filter(y_proc, eff_window, polyorder)

    peaks_idx, props = find_peaks(
        y_proc, prominence=peak_prominence, distance=peak_distance
    )
    peak_x = x[peaks_idx]
    peak_y = y_proc[peaks_idx]
    peak_prominences = props["prominences"]

    peak_data = list(zip(peak_x, peak_y, peak_prominences))
    df_matched = match_peaks(
        peak_data, tolerance=nist_tolerance, selected_elements=selected_elements
    )

    detected_elements = (
        df_matched[df_matched["element"] != "N/A"]["element"].unique().tolist()
        if not df_matched.empty
        else []
    )
    m1, m2, m3 = st.columns(3)
    m1.metric("Picos Detectados", len(peaks_idx))
    m2.metric(
        "Picos Identificados",
        len(df_matched[df_matched["element"] != "N/A"])
        if not df_matched.empty
        else 0,
    )
    m3.metric(
        "Fases Elementales Clave",
        ", ".join(detected_elements) if detected_elements else "Ninguna",
    )

    col1, col2 = st.columns([2.6, 1.4])
    with col1:
      fig = go.Figure()
      fig.add_trace(
          go.Scatter(
              x=x,
              y=y_raw,
              mode="lines",
              name="Crudo",
              line=dict(color="#666666", width=1),
              opacity=0.35,
          )
      )
      fig.add_trace(
          go.Scatter(
              x=x,
              y=y_proc,
              mode="lines",
              name="Procesado",
              line=dict(color="#00D2D3", width=1.5),
          )
      )

      if show_nist_lines and selected_elements:
        nist_sub = df_nist_all[df_nist_all["element"].isin(selected_elements)]
        nist_sub = nist_sub[
            (nist_sub["wavelength"] >= x.min())
            & (nist_sub["wavelength"] <= x.max())
        ]
        for _, row in nist_sub.iterrows():
          fig.add_vline(
              x=row["wavelength"],
              line_width=1,
              line_dash="dot",
              line_color="#E056FD",
              opacity=0.4,
          )

      if not df_matched.empty:
        labels = [
            f"<b>{row['matched_species']}</b><br>{row['detected_wl']:.2f}"
            if row["matched_species"] != "No identificado"
            else f"{row['detected_wl']:.2f}"
            for _, row in df_matched.iterrows()
        ]
        fig.add_trace(
            go.Scatter(
                x=df_matched["detected_wl"],
                y=df_matched["intensity"],
                mode="markers+text",
                name="Picos Analizados",
                text=labels,
                textposition="top center",
                marker=dict(
                    color=np.where(
                        df_matched["matched_species"] != "No identificado",
                        "#FF5252",
                        "#FFA726",
                    ),
                    size=8,
                    symbol="triangle-up",
                ),
            )
        )

      fig.update_layout(
          title="Espectro LIBS con Asignación Automática de Líneas NIST",
          xaxis_title=f"Longitud de Onda ({spec['x_unit']})",
          yaxis_title="Intensidad Neta (cuentas)",
          template="plotly_dark",
          height=600,
          hovermode="x unified",
      )
      st.plotly_chart(fig, use_container_width=True)

    with col2:
      st.subheader("Clasificación Atómica")
      if not df_matched.empty:
        df_display = df_matched[
            ["detected_wl", "matched_species", "nist_wl", "delta_nm", "intensity"]
        ].copy()
        df_display.columns = ["Exp.", "Especie", "NIST", "Δ (nm)", "Intensidad"]
        st.dataframe(
            df_display.sort_values(by="Intensidad", ascending=False).style.format({
                "Exp.": "{:.2f}",
                "NIST": lambda v: f"{v:.3f}" if pd.notnull(v) else "-",
                "Δ (nm)": lambda v: f"{v:.3f}" if pd.notnull(v) else "-",
                "Intensidad": "{:.1f}",
            }),
            height=480,
            use_container_width=True,
            hide_index=True,
        )
        st.download_button(
            "Exportar Clasificación (.csv)",
            data=df_display.to_csv(index=False).encode("utf-8"),
            file_name="clasificacion_libs_tecspec.csv",
            mime="text/csv",
        )
      else:
        st.info("No se hallaron picos con los filtros actuales.")

  # =========================================================================
  # MODO 2: REFLECTANCIA VNIR-SWIR (USGS / HIDSAG)
  # =========================================================================
  else:
    y_smooth = (
        savgol_filter(y_raw, eff_window, polyorder)
        if (apply_smoothing and eff_window > polyorder)
        else y_raw.copy()
    )

    if apply_cr and len(x) > 3:
      y_proc, continuum = continuum_removal(x, y_smooth)
      y_label = "Reflectancia sin Continuo (CR)"
    else:
      y_proc = y_smooth
      continuum = None
      y_label = "Reflectancia"

    dips_idx, props = find_peaks(
        -y_proc, prominence=dip_prominence, distance=dip_distance
    )
    dip_x = x[dips_idx]
    dip_y = y_proc[dips_idx]
    dip_depth = props["prominences"]

    m1, m2, m3 = st.columns(3)
    m1.metric("Bandas de Absorción", len(dips_idx))
    m2.metric(
        "Absorción Más Profunda",
        f"{dip_x[np.argmax(dip_depth)]:.3f} {spec['x_unit']}"
        if len(dips_idx) > 0
        else "N/A",
    )
    m3.metric("Puntos Espectrales", len(x))

    col1, col2 = st.columns([2.6, 1.4])
    with col1:
      fig = go.Figure()
      if not apply_cr:
        fig.add_trace(
            go.Scatter(
                x=x,
                y=y_raw,
                mode="lines",
                name="Reflectancia Cruda",
                line=dict(color="#666666", width=1),
                opacity=0.4,
            )
        )
      fig.add_trace(
          go.Scatter(
              x=x,
              y=y_proc,
              mode="lines",
              name="Espectro Procesado",
              line=dict(color="#00D2D3", width=1.8),
          )
      )

      if len(dips_idx) > 0:
        fig.add_trace(
            go.Scatter(
                x=dip_x,
                y=dip_y,
                mode="markers+text",
                name="Bandas de Absorción",
                text=[f"{val:.3f}" for val in dip_x],
                textposition="bottom center",
                marker=dict(color="#FF5252", size=9, symbol="triangle-down"),
            )
        )

      fig.update_layout(
          title="Espectro de Reflectancia y Detección de Bandas de Absorción",
          xaxis_title=f"Longitud de Onda ({spec['x_unit']})",
          yaxis_title=y_label,
          template="plotly_dark",
          height=600,
          hovermode="x unified",
      )
      st.plotly_chart(fig, use_container_width=True)

    with col2:
      st.subheader("Bandas de Absorción")
      if len(dips_idx) > 0:
        df_dips = pd.DataFrame({
            f"Posición ({spec['x_unit']})": dip_x,
            "Valor": dip_y,
            "Profundidad": dip_depth,
        }).sort_values(by="Profundidad", ascending=False)
        st.dataframe(
            df_dips.style.format({
                f"Posición ({spec['x_unit']})": "{:.2f}",
                "Valor": "{:.4f}",
                "Profundidad": "{:.4f}",
            }),
            height=480,
            use_container_width=True,
            hide_index=True,
        )
        st.download_button(
            "Exportar Bandas (.csv)",
            data=df_dips.to_csv(index=False).encode("utf-8"),
            file_name="bandas_absorcion_tecspec.csv",
            mime="text/csv",
        )
      else:
        st.info("Ajusta la profundidad mínima para detectar absorciones.")
else:
  st.info(
      "👈 Selecciona un ejemplo integrado o sube un archivo LIBS (`.csv`), USGS"
      " (`.txt`) o HIDSAG (`.h5`/`.hdf5`) en la barra lateral."
  )