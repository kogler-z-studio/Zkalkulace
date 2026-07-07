import streamlit as st
import ezdxf
import pdfplumber
import math
import tempfile
import os
import matplotlib.pyplot as plt
import matplotlib.patches as patches

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

# --- 1. GEOMETRICKÉ FUNKCE PRO DXF / DWG ---
def ziskej_rozmery_a_delku_dxf(doc):
    """Vrátí celkovou délku hran v metrech a bounding box (šířka, výška v mm) dílce z CADu."""
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


# --- 2. GEOMETRICKÉ FUNKCE PRO VECTOR PDF ---
def zpracuj_pdf_vektory_a_rozmery(file_bytes, dpi_meritko):
    """Vytáhne z PDF délky čar a spočítá bounding box (šířka, výška v mm) podle měřítka."""
    celkova_delka_pt = 0.0
    x_coords, y_coords = [], []
    
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name

    try:
        with pdfplumber.open(tmp_path) as pdf:
            for page in pdf.pages:
                for line in page.lines:
                    x0, y0 = float(line['x0']), float(line['y0'])
                    x1, y1 = float(line['x1']), float(line['y1'])
                    celkova_delka_pt += math.hypot(x1 - x0, y1 - y0)
                    x_coords.extend([x0, x1])
                    y_coords.extend([y0, y1])
                
                for rect in page.rects:
                    w = float(rect['width'])
                    h = float(rect['height'])
                    celkova_delka_pt += (2 * w + 2 * h)
                    x_coords.extend([float(rect['x0']), float(rect['x1'])])
                    y_coords.extend([float(rect['y0']), float(rect['y1'])])
                    
                for curve in page.curves:
                    x0, y0 = float(curve['x0']), float(curve['y0'])
                    x1, y1 = float(curve['x1']), float(curve['y1'])
                    celkova_delka_pt += math.hypot(x1 - x0, y1 - y0)
                    x_coords.extend([x0, x1])
                    y_coords.extend([y0, y1])
        
        os.unlink(tmp_path)
        
        if x_coords and y_coords:
            # Převod z bodů (pt) na mm: 1 pt = 0.3528 mm
            sirka_mm = (max(x_coords) - min(x_coords)) * 0.3528 * dpi_meritko
            vyska_mm = (max(y_coords) - min(y_coords)) * 0.3528 * dpi_meritko
            delka_m = (celkova_delka_pt * 0.3528 / 1000.0) * dpi_meritko
            return delka_m, sirka_mm, vyska_mm
        return 0.0, 0.0, 0.0
    except Exception as e:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        st.error(f"Chyba při analýze PDF: {e}")
        return 0.0, 0.0, 0.0


# --- 3. ALGORITMUS PRO NESTING (Skládání) ---
def hnezdni_dilce(sirka_archu, vyska_archu, sirka_dilce, vyska_dilce, celkovy_pocet_ks, okraj=5):
    w_dil_okraj = sirka_dilce + okraj
    h_dil_okraj = vyska_dilce + okraj
    
    # Varianta 1: bez rotace
    stlpce_v1 = int((sirka_archu - okraj) // w_dil_okraj)
    radky_v1 = int((vyska_archu - okraj) // h_dil_okraj)
    ks_na_arch_v1 = max(0, stlpce_v1 * radky_v1)
    
    # Varianta 2: s rotací o 90°
    stlpce_v2 = int((sirka_archu - okraj) // h_dil_okraj)
    radky_v2 = int((vyska_archu - okraj) // w_dil_okraj)
    ks_na_arch_v2 = max(0, stlpce_v2 * radky_v2)
    
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
    
    souradnice_na_archu = []
    vlozeno = 0
    for r in range(radky):
        for s in range(stlpce):
            if vlozeno < celkovy_pocet_ks:
                x = okraj + s * w_d
                y = okraj + r * h_d
                souradnice_na_archu.append((x, y, w_vykres, h_vykres))
                vlozeno += 1

    plocha_archu = sirka_archu * vyska_archu
    plocha_dilců_na_archu = min(ks_na_arch, celkovy_pocet_ks) * (sirka_dilce * vyska_dilce)
    vyuziti_procento = (plocha_dilců_na_archu / plocha_archu) * 100

    return ks_na_arch, potrebne_archy, souradnice_na_archu, vyuziti_procento


# --- MAIN STREAMLIT APP ---
st.set_page_config(page_title="Profi Nesting Kalkulátor", layout="wide")
st.title("📐 Výrobní multi-formátový kalkulátor s Nestingem")
st.write("Podporuje soubory: **.dxf, .dwg (novější), .pdf (vektorové výkresy)**")

# Boční panel nastavení
st.sidebar.header("⚙️ Výrobní parametry")
celkovy_pocet_ks = st.sidebar.number_input("Požadovaný počet kusů (ks)", value=50, min_value=1, step=5)
okraj_mezi_dilci = st.sidebar.number_input("Min. mezera mezi dílci / okraj (mm)", value=5, min_value=0, step=1)

st.sidebar.subheader("📐 Rozměry archu / materiálu")
vybrany_format = st.sidebar.selectbox("Vyberte formát archu", list(FORMATY_ARCHU.keys()))

if vybrany_format == "Vlastní (zadám v mm)":
    sirka_archu = st.sidebar.number_input("Šířka archu (mm)", value=1000, min_value=1)
    vyska_archu = st.sidebar.number_input("Výška archu (mm)", value=1000, min_value=1)
else:
    sirka_archu, vyska_archu = FORMATY_ARCHU[vybrany_format]
    st.sidebar.write(f"**Rozměr:** {sirka_archu} x {vyska_archu} mm")

st.sidebar.subheader("💰 Kalkulační matice (Ceny)")
cena_archu = st.sidebar.number_input("Nákupní cena jednoho archu (Kč)", value=150.0, step=10.0)
rychlost_stroje = st.sidebar.number_input("Rychlost řezu (mm/min)", value=2000, step=100)
cena_stroj_hod = st.sidebar.number_input("Sazba stroje (Kč/hod)", value=450, step=10)

# Hlavní plocha pro nahrání výkresu
uploaded_file = st.file_uploader("Nahrajte výkres rozvinu", type=["dxf", "dwg", "pdf"])

pdf_meritko = 1.0
if uploaded_file and uploaded_file.name.endswith('.pdf'):
    st.info("💡 U PDF výkresů zadejte měřítko exportu.")
    pdf_meritko = st.number_input("Koeficient měřítka PDF (pokud je výkres 1:10, zadejte 10)", value=1.0, step=0.1)

if uploaded_file is not None:
    bytes_data = uploaded_file.getvalue()
    file_extension = uploaded_file.name.split('.')[-1].lower()
    
    delka_m, sirka_dilce, vyska_dilce = 0.0, 0.0, 0.0
    
    with st.spinner("Provádím hloubkovou analýzu geometrie a vektorů..."):
        if file_extension in ('dxf', 'dwg'):
            with tempfile.NamedTemporaryFile(delete=False, suffix=f".{file_extension}") as tmp:
                tmp.write(bytes_data)
                tmp_path = tmp.name
            try:
                doc = ezdxf.readfile(tmp_path)
                delka_m, sirka_dilce, vyska_dilce = ziskej_rozmery_a_delku_dxf(doc)
                os.unlink(tmp_path)
            except Exception as e:
                os.unlink(tmp_path)
                st.error(f"Chyba formátu CAD souboru: {e}. Zkuste uložit jako standardní verzi DXF.")
        
        elif file_extension == 'pdf':
            delka_m, sirka_dilce, vyska_dilce = zpracuj_pdf_vektory_a_rozmery(bytes_data, pdf_meritko)

    # --- VYHODNOCENÍ VÝSLEDKŮ ---
    if delka_m > 0:
        ks_na_arch, potrebne_archy, souradnice, vyuziti_procento = hnezdni_dilce(
            sirka_archu, vyska_archu, sirka_dilce, vyska_dilce, celkovy_pocet_ks, okraj_mezi_dilci
        )
        
        st.header("📊 Výrobní, materiálová a cenová bilance")
        
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Rozměr jednoho dílce", f"{sirka_dilce:.1f} x {vyska_dilce:.1f} mm")
            st.metric("Metráž řezu / 1 ks", f"{delka_m:.2f} m")
        with col2:
            st.metric("Kusů na jeden arch", f"{ks_na_arch} ks")
            st.metric("Potřebný počet archů", f"{potrebne_archy if ks_na_arch > 0 else 0} ks")
        with col3:
            st.metric("Využití plochy archu", f"{vyuziti_procento:.1f} %")
            st.metric("Odpad materiálu", f"{100 - vyuziti_procento:.1f} %")
        with col4:
            if ks_na_arch > 0:
                celkovy_cas_min = (delka_m * 1000 * celkovy_pocet_ks) / rychlost_stroje
                cena_mat_celkem = potrebne_archy * cena_archu
                cena_stroj_celkem = (celkovy_cas_min / 60) * cena_stroj_hod
                cena_vyroby_celkem = cena_mat_celkem + cena_stroj_celkem
                
                st.metric("Celkový čas práce stroje", f"{celkovy_cas_min:.1f} min")
                st.metric("Celková odhadovaná cena", f"{cena_vyroby_celkem:.2f} Kč")
            else:
                st.metric("Celková odhadovaná cena", "N/A")

        if ks_na_arch == 0:
            st.error("❌ Rozměr dílce je větší než vybraný formát archu! Zvolte větší formát nebo zadejte vlastní mm rozměry v bočním panelu.")
        else:
            # --- NESTING NÁHLED ---
            st.header("🗺️ Grafický náhled rozložení (Nesting na 1. archu)")
            
            fig, ax = plt.subplots(figsize=(10, 6))
            arch_patch = patches.Rectangle((0, 0), sirka_archu, vyska_archu, linewidth=2, edgecolor='black', facecolor='#f0f2f6')
            ax.add_patch(arch_patch)
            
            for i, (x, y, w, h) in enumerate(souradnice):
                barva = '#ff4b4b' if i == 0 else '#1f77b4'
                dil_patch = patches.Rectangle((x, y), w, h, linewidth=1, edgecolor='white', facecolor=barva, alpha=0.7)
                ax.add_patch(dil_patch)
                ax.text(x + w/2, y + h/2, str(i+1), color='white', ha='center', va='center', fontsize=8, fontweight='bold')
            
            ax.set_xlim(-50, sirka_archu + 50)
            ax.set_ylim(-50, vyska_archu + 50)
            ax.set_aspect('equal', adjustable='box')
            plt.xlabel("mm")
            plt.ylabel("mm")
            ax.grid(True, linestyle=':', alpha=0.6)
            
            st.pyplot(fig)
    else:
        st.warning("V souboru nebyly nalezeny žádné měřitelné vektory. Ujistěte se, že nejde o čistý scan/obrázek.")
