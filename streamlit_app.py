import streamlit as st
import ezdxf
import pdfplumber
import math
import tempfile
import os
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from shapely.geometry import Polygon, box
from shapely.ops import unary_union

# --- DEFINICE FORMÁTŮ PAPÍRU / ARCHŮ (v mm) ---
FORMATY_ARCHU = {
    "Vlastní (zadám v mm)": None,
    "A4 (210 x 297 mm)": (210, 297),
    "A3 (297 x 420 mm)": (297, 420),
    "A2 (420 x 594 mm)": (420, 594),
    "A1 (594 x 841 mm)": (594, 841),
    "A0 (841 x 1189 mm)": (841, 1189),
    "B2 (500 x 707 mm)": (500, 707),
    "B1 (707 x 1000 mm)": (707, 1000),
    "B0 (1000 x 1414 mm)": (1000, 1414),
}

# --- GEOMETRICKÉ FUNKCE ---

def ziskej_rozmery_a_delku_dxf(doc):
    """Vrátí celkovou délku hran v metrech a bounding box (šířka, výška v mm) dílce."""
    msp = doc.modelspace()
    celkova_delka_mm = 0.0
    x_coords, y_coords = [], []

    for entity in msp:
        if entity.dxftype() == 'LINE':
            celkova_delka_mm += math.dist(entity.dxf.start, entity.dxf.end)
            x_coords.extend([entity.dxf.start.x, entity.dxf.end.x])
            y_coords.extend([entity.dxf.start.y, entity.dxf.end.y])
        elif entity.dxftype() == 'CIRCLE':
            celkova_delka_mm += 2 * math.pi * entity.dxf.radius
            x_coords.extend([entity.dxf.center.x - entity.dxf.radius, entity.dxf.center.x + entity.dxf.radius])
            y_coords.extend([entity.dxf.center.y - entity.dxf.radius, entity.dxf.center.y + entity.dxf.radius])
        elif entity.dxftype() == 'ARC':
            r = entity.dxf.radius
            uhel = (entity.dxf.end_angle - entity.dxf.start_angle) % 360
            celkova_delka_mm += (2 * math.pi * r) * (uhel / 360.0)
            x_coords.extend([entity.dxf.center.x - r, entity.dxf.center.x + r])
            y_coords.extend([entity.dxf.center.y - r, entity.dxf.center.y + r])
        elif entity.dxftype() in ('LWPOLYLINE', 'POLYLINE'):
            points = entity.get_points() if entity.dxftype() == 'POLYLINE' else entity.vertices()
            pts = [p for p in points]
            for i in range(len(pts) - 1):
                celkova_delka_mm += math.dist(pts[i][:2], pts[i+1][:2])
                x_coords.append(pts[i][0])
                y_coords.append(pts[i][1])
            if pts:
                x_coords.append(pts[-1][0])
                y_coords.append(pts[-1][1])
            if entity.closed and pts:
                celkova_delka_mm += math.dist(pts[-1][:2], pts[0][:2])

    if x_coords and y_coords:
        sirka = max(x_coords) - min(x_coords)
        vyska = max(y_coords) - min(y_coords)
        return celkova_delka_mm / 1000.0, sirka, vyska
    return 0.0, 0.0, 0.0

def hnezdni_dilce(sirka_archu, vyska_archu, sirka_dilce, vyska_dilce, celkovy_pocet_ks, okraj=5):
    """Algoritmus pro pravoúhlý nesting dílců na archy."""
    w_dil_okraj = sirka_dilce + okraj
    h_dil_okraj = vyska_dilce + okraj
    
    # Kolik se jich vejde na jeden arch (zkusíme variantu na výšku i na šířku)
    stlpce_v1 = int((sirka_archu - okraj) // w_dil_okraj)
    radky_v1 = int((vyska_archu - okraj) // h_dil_okraj)
    ks_na_arch_v1 = max(0, stlpce_v1 * radky_v1)
    
    # Otočení dílce o 90 stupňů pro optimalizaci
    stlpce_v2 = int((sirka_archu - okraj) // h_dil_okraj)
    radky_v2 = int((vyska_archu - okraj) // w_dil_okraj)
    ks_na_arch_v2 = max(0, stlpce_v2 * radky_v2)
    
    # Vybereme lepší rotaci
    if ks_na_arch_v2 > ks_na_arch_v1:
        w_d, h_d = h_dil_okraj, w_dil_okraj
        w_vykres, h_vykres = vyska_dilce, sirka_dilce
        ks_na_arch = ks_na_arch_v2
        stlpce, radky = stlpce_v2, radky_v2
    else:
        w_d, h_d = w_dil_okraj, h_dil_okraj
        w_vykres, h_vykres = sirka_dilce, vyska_dilce
        ks_na_arch = ks_na_arch_v1
        stlpce, radky = stlpce_v1, radky_v1

    if ks_na_arch == 0:
        return 0, 0, [], 0.0

    potrebne_archy = math.ceil(celkovy_pocet_ks / ks_na_arch)
    
    # Generování souřadnic pro náhled prvního archu
    souradnice_na_archu = []
    vlozeno = 0
    for r in range(radky):
        for s in range(stlpce):
            if vlozeno < celkovy_pocet_ks:
                x = okraj + s * w_d
                y = okraj + r * h_d
                souradnice_na_archu.append((x, y, w_vykres, h_vykres))
                vlozeno += 1

    # Výpočet využití plochy na 1 archu
    plocha_archu = sirka_archu * vyska_archu
    plocha_dilců_na_archu = min(ks_na_arch, celkovy_pocet_ks) * (sirka_dilce * vyska_dilce)
    vyuziti_procento = (plocha_dilců_na_archu / plocha_archu) * 100

    return ks_na_arch, potrebne_archy, souradnice_na_archu, vyuziti_procento

# --- MAIN STREAMLIT APP ---

st.set_page_config(page_title="Výrobní Nesting Kalkulátor", layout="wide")
st.title("📦 Výrobní kalkulátor s Nestingem (skládáním na arch)")

# Sidebar nastavení
st.sidebar.header("⚙️ Výrobní parametry")
celkovy_pocet_ks = st.sidebar.number_input("Požadovaný počet kusů výrobku (ks)", value=50, min_value=1, step=5)
okraj_mezi_dilci = st.sidebar.number_input("Min. mezera mezi dílci / okraj (mm)", value=5, min_value=0, step=1)

st.sidebar.subheader("📐 Rozměry polotovaru / archu")
vybrany_format = st.sidebar.selectbox("Vyberte formát archu", list(FORMATY_ARCHU.keys()))

if vybrany_format == "Vlastní (zadám v mm)":
    sirka_archu = st.sidebar.number_input("Šířka archu (mm)", value=1000, min_value=1)
    vyska_archu = st.sidebar.number_input("Výška archu (mm)", value=1000, min_value=1)
else:
    sirka_archu, vyska_archu = FORMATY_ARCHU[vybrany_format]
    st.sidebar.disabled = True
    st.sidebar.write(f"Rozměr: {sirka_archu} x {vyska_archu} mm")

st.sidebar.subheader("💰 Ekonomika")
cena_archu = st.sidebar.number_input("Nákupní cena jednoho archu (Kč)", value=150.0, step=10.0)
rychlost_stroje = st.sidebar.number_input("Rychlost řezu (mm/min)", value=2000, step=100)
cena_stroj_hod = st.sidebar.number_input("Sazba stroje (Kč/hod)", value=450, step=10)

# Hlavní plocha pro nahrání
uploaded_file = st.file_uploader("Nahrajte výkres rozvinu (.dxf)", type=["dxf"])

if uploaded_file is not None:
    bytes_data = uploaded_file.getvalue()
    
    with st.spinner("Analyzuji geometrii rozvinu..."):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".dxf") as tmp:
            tmp.write(bytes_data)
            tmp_path = tmp.name
        try:
            doc = ezdxf.readfile(tmp_path)
            delka_m, sirka_dilce, vyska_dilce = ziskej_rozmery_a_delku_dxf(doc)
            os.unlink(tmp_path)
        except Exception as e:
            os.unlink(tmp_path)
            st.error(f"Chyba při zpracování DXF: {e}")
            delka_m = 0

    if delka_m > 0:
        # Spuštění Nesting algoritmu
        ks_na_arch, potrebne_archy, souradnice, vyuziti_procento = hnezdni_dilce(
            sirka_archu, vyska_archu, sirka_dilce, vyska_dilce, celkovy_pocet_ks, okraj_mezi_dilci
        )
        
        # --- ZOBRAZENÍ VÝSLEDKŮ ---
        st.header("📊 Výrobní a materiálová bilance")
        
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Rozměr jednoho dílce", f"{sirka_dilce:.1f} x {vyska_dilce:.1f} mm")
            st.metric("Délka obvodu/vektorů", f"{delka_m:.2f} m / ks")
        with col2:
            st.metric("Kusů na jeden arch", f"{ks_na_arch} ks / arch")
            st.metric("Potřebný počet archů", f"{potrebnep_archy if ks_na_arch > 0 else 0} ks")
        with col3:
            st.metric("Využití plochy archu", f"{vyuziti_procento:.1f} %")
            st.metric("Odpad materiálu", f"{100 - vyuziti_procento:.1f} %")
        with col4:
            if ks_na_arch > 0:
                celkovy_cas_min = (delka_m * 1000 * celkovy_pocet_ks) / rrychlost_stroje
                cena_mat_celkem = potrebne_archy * cena_archu
                cena_stroj_celkem = (celkovy_cas_min / 60) * cena_stroj_hod
                cena_vyroby_celkem = cena_mat_celkem + cena_stroj_celkem
                
                st.metric("Celkový čas řezání", f"{celkovy_cas_min:.1f} min")
                st.metric("Celková odhadovaná cena", f"{cena_vyroby_celkem:.2f} Kč")
            else:
                st.metric("Celkový čas řezání", "N/A")

        if ks_na_arch == 0:
            st.error("❌ Rozměr dílce (včetně okrajů) je větší než vybraný formát archu! Zvolte větší arch nebo zadejte vlastní rozměry.")
        else:
            # --- VYKRESLENÍ NÁHLEDU (NESTING) ---
            st.header("🗺️ Grafický náhled rozložení (Nesting na 1. archu)")
            
            fig, ax = plt.subplots(figsize=(10, 6))
            # Vykreslení archu
            arch_patch = patches.Rectangle((0, 0), sirka_archu, vyska_archu, linewidth=2, edgecolor='black', facecolor='#f0f2f6', label='Arch polotovaru')
            ax.add_patch(arch_patch)
            
            # Vykreslení jednotlivých dílců (obálek)
            for i, (x, y, w, h) in enumerate(souradnice):
                # První dílec zvýrazníme, ostatní jsou běžné
                barva = '#ff4b4b' if i == 0 else '#1f77b4'
                dil_patch = patches.Rectangle((x, y), w, h, linewidth=1, edgecolor='white', facecolor=barva, alpha=0.7)
                ax.add_patch(dil_patch)
                # Přidání čísla dílce pro přehlednost
                ax.text(x + w/2, y + h/2, str(i+1), color='white', ha='center', va='center', fontsize=8, fontweight='bold')
            
            # Nastavení grafu
            ax.set_xlim(-50, sirka_archu + 50)
            ax.set_ylim(-50, vyska_archu + 50)
            ax.set_aspect('equal', adjustable='box')
            plt.title(f"Schéma osazení archu (Zobrazeno {len(souradnice)} z {celkovy_pocet_ks} ks)")
            plt.xlabel("mm")
            plt.ylabel("mm")
            ax.grid(True, linestyle=':', alpha=0.6)
            
            st.pyplot(fig)
