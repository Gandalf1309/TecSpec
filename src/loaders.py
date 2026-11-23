# src/loaders.py
import io
import h5py
import numpy as np
import pandas as pd


def load_usgs_wavelengths(wl_file):
  """Lee el archivo maestro de longitudes de onda del USGS (ej. BECK)."""
  lines = wl_file.getvalue().decode("utf-8", errors="ignore").splitlines()
  vals = []
  for line in lines[1:]:
    s = line.strip()
    if s:
      try:
        vals.append(float(s))
      except ValueError:
        continue
  arr = np.array(vals, dtype=float)
  arr[arr < -1e30] = np.nan
  return arr


def _find_datasets_hdf5(h5_obj):
  """Recorre recursivamente un archivo HDF5 y lista todos sus datasets."""
  datasets = {}

  def visitor(name, node):
    if isinstance(node, h5py.Dataset):
      datasets[name] = node

  h5_obj.visititems(visitor)
  return datasets


def load_hidsag_hdf5(uploaded_file):
  """
    Lee un archivo HIDSAG en formato HDF5 (.h5 / .hdf5).
    Extrae 'hsi_data' (o el dataset numérico principal), calcula el espectro
    promedio si es matriz 2D o cubo 3D, y busca longitudes de onda en datasets/atributos.
    """
  bio = io.BytesIO(uploaded_file.getvalue())
  with h5py.File(bio, "r") as f:
    datasets = _find_datasets_hdf5(f)
    if not datasets:
      raise ValueError("El archivo HDF5 no contiene datasets legibles.")

    # Priorizar dataset llamado 'hsi_data' (estructura estándar HIDSAG)
    data_key = next(
        (k for k in datasets if "hsi_data" in k.lower()),
        None,
    )
    if data_key is None:
      # Respaldo: elegir el dataset numérico de mayor tamaño
      numeric_keys = [
          k for k, ds in datasets.items() if np.issubdtype(ds.dtype, np.number)
      ]
      if not numeric_keys:
        raise ValueError(
            "No se encontraron datasets numéricos en el archivo HDF5."
        )
      data_key = max(numeric_keys, key=lambda k: datasets[k].size)

    raw_data = np.array(datasets[data_key], dtype=float)

    # Limpiar posibles banderas nulas o NaNs
    raw_data[np.abs(raw_data) > 1e30] = np.nan

    # Reducir a 1D (espectro promedio) si es cubo hiperespectral (H, W, Bandas) o matriz (N, Bandas)
    original_shape = raw_data.shape
    if raw_data.ndim == 3:
      y = np.nanmean(raw_data, axis=(0, 1))
    elif raw_data.ndim == 2:
      # Asumir que el eje espectral es el que tiene mayor número de bandas o el último eje
      y = np.nanmean(raw_data, axis=0)
    elif raw_data.ndim == 1:
      y = raw_data
    else:
      raise ValueError(f"Dimensionalidad no soportada en HDF5: {raw_data.ndim}")

    # Buscar eje de longitudes de onda dentro de los datasets o atributos
    x = None
    unit = "Banda / Índice"
    wl_key = next(
        (
            k
            for k in datasets
            if any(w in k.lower() for w in ["wave", "wl", "band", "lambda"])
        ),
        None,
    )
    if wl_key is not None and datasets[wl_key].size == len(y):
      x = np.array(datasets[wl_key], dtype=float).ravel()
      unit = "nm" if np.nanmax(x) > 50 else "µm"
    else:
      # Revisar atributos del dataset o de la raíz
      for attrs in [datasets[data_key].attrs, f.attrs]:
        for attr_name, attr_val in attrs.items():
          if any(
              w in attr_name.lower() for w in ["wave", "wl", "band", "lambda"]
          ):
            arr = np.array(attr_val, dtype=float).ravel()
            if arr.size == len(y):
              x = arr
              unit = "nm" if np.nanmax(x) > 50 else "µm"
              break

    if x is None:
      x = np.arange(len(y), dtype=float)

    valid = np.isfinite(x) & np.isfinite(y)
    return {
        "x": x[valid],
        "y": y[valid],
        "format": "HIDSAG (HDF5)",
        "suggested_mode": "Reflectancia (VNIR-SWIR)",
        "x_unit": unit,
        "meta": (
            f"Dataset: `{data_key}` | Forma original: {original_shape} | Claves"
            f" HDF5: {list(datasets.keys())[:6]}"
        ),
    }


def load_spectrum(uploaded_file, usgs_wl_file=None):
  """
    Cargador universal para TecSpec:
    1. HIDSAG (.h5, .hdf5)
    2. USGS splib07a (.txt de 1 columna con cabecera y bandera -1.23e+034)
    3. Estándar 2 columnas (.csv / .txt) para LIBS o Reflectancia
    """
  filename = uploaded_file.name.lower()

  # --- CASO 1: HIDSAG (HDF5) ---
  if filename.endswith((".h5", ".hdf5", ".hdf")):
    return load_hidsag_hdf5(uploaded_file)

  # --- LEER TEXTO PARA DISTINGUIR USGS vs CSV/TXT 2 COLUMNAS ---
  raw_bytes = uploaded_file.getvalue()
  # Detección de respaldo por firma binaria HDF5 aunque el archivo no tenga extensión .h5
  if raw_bytes.startswith(b"\x89HDF"):
    return load_hidsag_hdf5(uploaded_file)

  text = raw_bytes.decode("utf-8", errors="ignore")
  lines = [l.strip() for l in text.splitlines() if l.strip()]

  if not lines:
    raise ValueError("El archivo está vacío.")

  first_line = lines[0]

  # --- CASO 2: USGS splib07a (.txt de 1 columna) ---
  is_usgs = ("splib07" in first_line.lower()) or (
      filename.endswith(".txt")
      and len(lines) > 2
      and len(lines[2].replace(",", " ").split()) == 1
  )

  if is_usgs:
    vals = []
    for line in lines[1:]:
      try:
        vals.append(float(line))
      except ValueError:
        continue
    y = np.array(vals, dtype=float)
    # Limpiar bandera nula oficial del USGS (-1.2300000e+034)
    y[y < -1e30] = np.nan

    if usgs_wl_file is not None:
      x_wl = load_usgs_wavelengths(usgs_wl_file)
      n = min(len(x_wl), len(y))
      x, y = x_wl[:n], y[:n]
      x_unit = "µm" if np.nanmax(x) < 50 else "nm"
    else:
      x = np.arange(len(y), dtype=float)
      x_unit = "Canal espectral (sube archivo Wavelengths para µm)"

    valid = np.isfinite(x) & np.isfinite(y)
    return {
        "x": x[valid],
        "y": y[valid],
        "format": "USGS splib07a",
        "suggested_mode": "Reflectancia (VNIR-SWIR)",
        "x_unit": x_unit,
        "meta": first_line,
    }

  # --- CASO 3: CSV / TXT estándar de 2 columnas (LIBS o Reflectancia) ---
  df = pd.read_csv(io.StringIO(text), sep=None, engine="python")
  if df.shape[1] < 2:
    raise ValueError(
        "El archivo CSV/TXT requiere al menos 2 columnas (Wavelength,"
        " Intensity/Reflectance)."
    )

  x = pd.to_numeric(df.iloc[:, 0], errors="coerce").to_numpy()
  y = pd.to_numeric(df.iloc[:, 1], errors="coerce").to_numpy()
  valid = np.isfinite(x) & np.isfinite(y)
  x, y = x[valid], y[valid]

  # Heurística simple para sugerir modo y unidad
  is_reflectance = np.nanmax(y) <= 2.0 and np.nanmin(y) >= -0.1
  x_unit = "µm" if np.nanmax(x) < 50 else "nm"

  return {
      "x": x,
      "y": y,
      "format": "CSV / TXT (2 columnas)",
      "suggested_mode": (
          "Reflectancia (VNIR-SWIR)"
          if is_reflectance
          else "LIBS (Emisión Atómica)"
      ),
      "x_unit": x_unit,
      "meta": f"Columnas detectadas: {df.columns[0]} vs {df.columns[1]}",
  }