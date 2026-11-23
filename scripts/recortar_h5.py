# recortar_h5.py
from pathlib import Path
import h5py
import numpy as np

# Ajusta INPUT_H5 a la ruta real donde tienes tu archivo pesado de HIDSAG
BASE_DIR = Path(__file__).resolve().parent
INPUT_H5 = BASE_DIR / "swir_low.h5"
OUTPUT_H5 = BASE_DIR / "sample_swir_mini.h5"
PATCH_SIZE = 10  # Ventana espacial 10x10 (100 píxeles) conservando todas las bandas


def recortar_hdf5(input_path: Path, output_path: Path, patch_size: int = 10):
  output_path.parent.mkdir(parents=True, exist_ok=True)

  with h5py.File(input_path, "r") as src, h5py.File(output_path, "w") as dst:
    # Copiar atributos de la raíz
    for k, v in src.attrs.items():
      dst.attrs[k] = v
    if len(src.attrs) > 0:
      print(f"Atributos raíz: {list(src.attrs.keys())}")

    def copiar_nodo(name, obj):
      if isinstance(obj, h5py.Group):
        grp = dst.require_group(name)
        for k, v in obj.attrs.items():
          grp.attrs[k] = v

      elif isinstance(obj, h5py.Dataset):
        shape = obj.shape
        ndim = obj.ndim
        is_numeric = obj.dtype.kind in ("i", "u", "f")
        print(
            f"Dataset: '{name}' | shape={shape} | dtype={obj.dtype} |"
            f" attrs={list(obj.attrs.keys())}"
        )

        # Caso cubo hiperespectral 3D (H, W, Bandas)
        if ndim == 3 and obj.size > 50_000:
          h, w, _ = shape
          cy, cx = h // 2, w // 2
          half = patch_size // 2
          y0, y1 = max(0, cy - half), min(h, cy + half)
          x0, x1 = max(0, cx - half), min(w, cx + half)
          data = obj[y0:y1, x0:x1, :]
          ds = dst.create_dataset(
              name, data=data, compression="gzip", compression_opts=9
          )
          print(f"  -> Recortado a shape={data.shape}")

        # Caso matriz 2D grande (N muestras, Bandas)
        elif ndim == 2 and shape[0] > 50 and obj.size > 50_000:
          data = obj[:50, :]
          ds = dst.create_dataset(
              name, data=data, compression="gzip", compression_opts=9
          )
          print(f"  -> Recortado a shape={data.shape}")

        # Datasets pequeños, 1D (longitudes de onda), polígonos o texto se copian completos
        else:
          data = obj[()]
          if ndim > 0 and is_numeric:
            ds = dst.create_dataset(
                name, data=data, compression="gzip", compression_opts=9
            )
          else:
            ds = dst.create_dataset(name, data=data)

        # Copiar atributos del dataset
        for k, v in obj.attrs.items():
          ds.attrs[k] = v

    src.visititems(copiar_nodo)

  orig_mb = input_path.stat().st_size / (1024 * 1024)
  new_kb = output_path.stat().st_size / 1024
  print(f"\nArchivo generado: {output_path}")
  print(f"Peso original: {orig_mb:.2f} MB  -->  Peso mini: {new_kb:.1f} KB")


if __name__ == "__main__":
  recortar_hdf5(INPUT_H5, OUTPUT_H5, PATCH_SIZE)