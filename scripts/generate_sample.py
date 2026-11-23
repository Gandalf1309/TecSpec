# generate_sample.py
import numpy as np
import pandas as pd

# Rango típico UV-Vis de LIBS: 200 nm a 600 nm
wavelengths = np.linspace(200, 600, 4000)

# 1. Fondo continuo del plasma (bremsstrahlung) simulado
continuum = 500 * np.exp(-((wavelengths - 250) / 120)**2) + 120

# 2. Líneas de emisión simuladas (centro nm, amplitud, ancho)
peaks = [
    (324.75, 1200, 0.25),  # Cu I
    (327.40, 950, 0.25),   # Cu I
    (288.16, 700, 0.20),   # Si I
    (371.99, 600, 0.22),   # Fe I
    (373.49, 580, 0.22),   # Fe I
    (521.82, 450, 0.30),   # Cu I
]

signal = continuum.copy()
for center, amp, width in peaks:
    signal += amp * np.exp(-((wavelengths - center) / width)**2)

# 3. Ruido blanco instrumental
noise = np.random.normal(0, 15, len(wavelengths))
final_intensity = signal + noise

# Guardar en CSV
df = pd.DataFrame({"wavelength": wavelengths, "intensity": final_intensity})
df.to_csv("muestra_mineral_prueba.csv", index=False)
print("Archivo 'muestra_mineral_prueba.csv' generado con éxito.")