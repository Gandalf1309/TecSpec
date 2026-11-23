# nist_lines.py
import pandas as pd

# Base de datos de líneas de emisión atómica típicas en matrices geológicas/mineras
# Longitudes de onda nominales en nanómetros (nm) en aire
NIST_DATABASE = [
    # Cobre (Cu)
    {"element": "Cu", "species": "Cu I", "wavelength": 324.754, "relative_intensity": 1000},
    {"element": "Cu", "species": "Cu I", "wavelength": 327.396, "relative_intensity": 800},
    {"element": "Cu", "species": "Cu I", "wavelength": 510.554, "relative_intensity": 400},
    {"element": "Cu", "species": "Cu I", "wavelength": 515.324, "relative_intensity": 350},
    {"element": "Cu", "species": "Cu I", "wavelength": 521.820, "relative_intensity": 500},
    
    # Silicio (Si)
    {"element": "Si", "species": "Si I", "wavelength": 250.690, "relative_intensity": 400},
    {"element": "Si", "species": "Si I", "wavelength": 251.611, "relative_intensity": 500},
    {"element": "Si", "species": "Si I", "wavelength": 288.158, "relative_intensity": 1000},
    {"element": "Si", "species": "Si I", "wavelength": 390.552, "relative_intensity": 300},
    
    # Hierro (Fe)
    {"element": "Fe", "species": "Fe II", "wavelength": 238.204, "relative_intensity": 700},
    {"element": "Fe", "species": "Fe II", "wavelength": 259.940, "relative_intensity": 850},
    {"element": "Fe", "species": "Fe I",  "wavelength": 371.993, "relative_intensity": 900},
    {"element": "Fe", "species": "Fe I",  "wavelength": 373.486, "relative_intensity": 850},
    {"element": "Fe", "species": "Fe I",  "wavelength": 374.556, "relative_intensity": 600},
    {"element": "Fe", "species": "Fe I",  "wavelength": 404.581, "relative_intensity": 750},
    {"element": "Fe", "species": "Fe I",  "wavelength": 438.355, "relative_intensity": 800},
    
    # Aluminio (Al)
    {"element": "Al", "species": "Al I", "wavelength": 308.215, "relative_intensity": 700},
    {"element": "Al", "species": "Al I", "wavelength": 309.271, "relative_intensity": 900},
    {"element": "Al", "species": "Al I", "wavelength": 394.401, "relative_intensity": 850},
    {"element": "Al", "species": "Al I", "wavelength": 396.152, "relative_intensity": 1000},
    
    # Calcio (Ca)
    {"element": "Ca", "species": "Ca II", "wavelength": 393.366, "relative_intensity": 1000}, # Ca II K
    {"element": "Ca", "species": "Ca II", "wavelength": 396.847, "relative_intensity": 900},  # Ca II H
    {"element": "Ca", "species": "Ca I",  "wavelength": 422.673, "relative_intensity": 950},
    
    # Magnesio (Mg)
    {"element": "Mg", "species": "Mg II", "wavelength": 279.553, "relative_intensity": 1000},
    {"element": "Mg", "species": "Mg II", "wavelength": 280.270, "relative_intensity": 900},
    {"element": "Mg", "species": "Mg I",  "wavelength": 285.213, "relative_intensity": 950},
    {"element": "Mg", "species": "Mg I",  "wavelength": 518.360, "relative_intensity": 600},
    
    # Titanio (Ti)
    {"element": "Ti", "species": "Ti II", "wavelength": 334.941, "relative_intensity": 800},
    {"element": "Ti", "species": "Ti II", "wavelength": 336.121, "relative_intensity": 750},
    {"element": "Ti", "species": "Ti II", "wavelength": 337.280, "relative_intensity": 700},
    
    # Litio (Li)
    {"element": "Li", "species": "Li I", "wavelength": 610.360, "relative_intensity": 300},
    {"element": "Li", "species": "Li I", "wavelength": 670.776, "relative_intensity": 1000},
    {"element": "Li", "species": "Li I", "wavelength": 670.791, "relative_intensity": 900},
    
    # Sodio (Na)
    {"element": "Na", "species": "Na I", "wavelength": 588.995, "relative_intensity": 1000}, # Línea D2
    {"element": "Na", "species": "Na I", "wavelength": 589.592, "relative_intensity": 800},  # Línea D1
    
    # Potasio (K)
    {"element": "K", "species": "K I", "wavelength": 766.490, "relative_intensity": 1000},
    {"element": "K", "species": "K I", "wavelength": 769.896, "relative_intensity": 800}
]

def get_nist_dataframe():
    return pd.DataFrame(NIST_DATABASE)

def match_peaks(detected_peaks, tolerance=0.25, selected_elements=None):
    """
    Cruza los picos detectados con la base NIST dentro de una ventana de tolerancia.
    Retorna una lista con la mejor coincidencia para cada pico detectado.
    """
    df_nist = get_nist_dataframe()
    if selected_elements:
        df_nist = df_nist[df_nist["element"].isin(selected_elements)]
        
    matches = []
    
    for p_wl, p_int, p_prom in detected_peaks:
        # Calcular delta absoluto contra todas las líneas de referencia
        diffs = (df_nist["wavelength"] - p_wl).abs()
        candidates = df_nist[diffs <= tolerance].copy()
        
        if not candidates.empty:
            candidates["delta_nm"] = (candidates["wavelength"] - p_wl).abs()
            # Ordenar por cercanía espectral
            best = candidates.sort_values(by=["delta_nm"]).iloc[0]
            matches.append({
                "detected_wl": p_wl,
                "intensity": p_int,
                "prominence": p_prom,
                "matched_species": best["species"],
                "element": best["element"],
                "nist_wl": best["wavelength"],
                "delta_nm": best["delta_nm"]
            })
        else:
            matches.append({
                "detected_wl": p_wl,
                "intensity": p_int,
                "prominence": p_prom,
                "matched_species": "No identificado",
                "element": "N/A",
                "nist_wl": None,
                "delta_nm": None
            })
            
    return pd.DataFrame(matches)