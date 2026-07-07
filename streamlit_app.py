import streamlit as st
import ezdxf
import pdfplumber
import math
import tempfile
import os

# --- POMOCNÉ FUNKCE PRO VÝPOČET GEOMETRIE ---

def spocitej_delku_dxf_struktury(doc):
    """Projde modelspace DXF dokumentu a spočítá délku všech vektorů."""
    msp = doc.modelspace()
    celkova_delka_mm = 0.0

    for entity in msp:
        # Úsečky
        if entity.dxftype() == 'LINE':
            celkova_delka_mm += math.dist(entity.dxf.start, entity.dxf.end)
        
        # Kružnice
        elif entity.dxftype() == 'CIRCLE':
            celkova_delka_mm += 2 * math.pi * entity.dxf.radius
        
        # Oblouky
        elif entity.dxftype() == 'ARC':
            r = entity.dxf.radius
            start_w = entity.dxf.start_angle
            end_w = entity.dxf.end_angle
            if end_w < start_w:
                end_w += 360
            uhel = end_w - start_w
            celkova_delka_mm += (2 * math.pi * r) * (uhel / 360.0)
        
        # Složité křivky (Polylines)
        elif entity.dxftype() in ('LWPOLYLINE', 'POLYLINE'):
            points = entity.get_points() if entity.dxftype() == 'POLYLINE' else entity.vertices()
            pts = [p for p in points]
            for i in range(len(pts) - 1):
                celkova_delka_mm += math.dist(pts[i][:2], pts[i+1][:2])
            if entity.closed:
                celkova_delka_mm += math.dist(pts[-1][:2], pts[0][:2])

    return celkova_delka_mm / 1000.0  # Převod na metry


def zpracuj_pdf_vektory(file_bytes, dpi_meritko):
    """Vytáhne z vektorového PDF délky všech nakreslených čar a geometrických cest."""
    celkova_delka_pt = 0.0
    
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name

    try:
        with pdfplumber.open(tmp_path) as pdf:
            for page in pdf.pages:
                # 1. Získání přímých čar (lines)
                for line in page.lines:
                    x0, y0 = float(line['x0']), float(line['y0'])
                    x1, y1 = float(line['x1']), float(line['y1'])
                    celkova_delka_pt += math.hypot(x1 - x0, y1 - y0)
                
                # 2. Získání obdélníků / uzavřených cest (rects)
                for rect in page.rects:
                    w = float(rect['width'])
                    h = float(rect['height'])
                    celkova_delka_pt += (2 * w + 2 * h)
                    
                # 3. Získání komplexních křivek (curves/paths)
                for curve in page.curves:
                    x0, y0 = float(curve['x0']), float(curve['y0'])
                    x1, y1 = float(curve['x1']), float(curve['y1'])
                    celkova_delka_pt += math.hypot(x1 - x0, y1 - y0)
        
        os.unlink(tmp_path)
        # PDF standardně používá body (1 bod = 1/72 palce = 0.3528 mm)
        # Použijeme uživatelské měřítko pro převod bodů přímo na reálné metry rozvinu
        delka_m = (celkova_delka_pt * 0.3528 / 1000.0) * dpi_meritko
        return delka_m
    except Exception as e:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        st.error(f"Chyba při analýze PDF: {e}. Ujistěte se, že jde o vektorové PDF z CADu, ne naskenovaný obrázek.")
        return None

# --- MAIN STREAMLIT APP ---

st.set_page_config(page_title="Profi Výrobní Kalkulačka", layout="centered")
st.title("📐 Multi-formátový kalkulátor z rozvinů")
st.write("Podporované formáty: **.dxf, .dwg (textové verze), .pdf (vektorové výkresy)**")

# Výběr souboru
uploaded_file = st.file_uploader("Nahrajte výkres rozvinu", type=["dxf", "dwg", "pdf"])

# Boční panel nastavení
st.sidebar.header("⚙️ Nastavení nákladů")
rychlost_stroje = st.sidebar.number_input("Rychlost řezu (mm/min)", value=2000, step=100)
cena_stroj_hod = st.sidebar.number_input("Sazba stroje (Kč/hod)", value=450, step=10)
cena_prace_hod = st.sidebar.number_input("Sazba operátora (Kč/hod)", value=350, step=10)
marze_procento = st.sidebar.number_input("Požadovaná marže (%)", value=20, step=5)

# Specifické nastavení pro PDF měřítko
pdf_meritko = 1.0
if uploaded_file and uploaded_file.name.endswith('.pdf'):
    st.info("💡 U PDF výkresů je potřeba zadat koeficient měřítka exportu (jak moc je výkres zmenšen oproti realitě 1:1).")
    pdf_meritko = st.number_input("Koeficient měřítka PDF (např. pokud je výkres 1:10, zadejte 10)", value=1.0, step=0.1)

if uploaded_file is not None:
    bytes_data = uploaded_file.getvalue()
    file_extension = uploaded_file.name.split('.')[-1].lower()
    delka_rezu_m = None
    
    with st.spinner("Chroustám geometrii a počítám délku vektorů..."):
        if file_extension in ('dxf', 'dwg'):
            with tempfile.NamedTemporaryFile(delete=False, suffix=f".{file_extension}") as tmp:
                tmp.write(bytes_data)
                tmp_path = tmp.name
            try:
                # ezdxf umí načíst nativní DXF a novější verze umí parsovat i DWG schémata
                doc = ezdxf.readfile(tmp_path)
                delka_rezu_m = spocitej_delku_dxf_struktury(doc)
                os.unlink(tmp_path)
            except Exception as e:
                os.unlink(tmp_path)
                st.error(f"Chyba formátu CAD souboru: {e}. Pokud jde o staré binární DWG, uložte ho v CADu jako verzi DXF 2010 nebo novější.")
        
        elif file_extension == 'pdf':
            delka_rezu_m = zpracuj_pdf_vektory(bytes_data, pdf_meritko)

    # VÝSLEDKY A KALKULACE
    if delka_rezu_m and delka_rezu_m > 0:
        delka_rezu_mm = delka_rezu_m * 1000
        
        # Výpočet času řezu
        cas_v_minutach = delka_rezu_mm / rychlost_stroje
        cas_v_hodinach = cas_v_minutach / 60
        
        # Ekonomika
        naklady_stroj = cas_v_hodinach * cena_stroj_hod
        naklady_prace = cas_v_hodinach * cena_prace_hod
        naklady_celkem = naklady_stroj + naklady_prace
        cena_s_marzi = naklady_celkem * (1 + (marze_procento / 100))
        
        st.success("Vektory úspěšně spočteny!")
        
        col1, col2 = st.columns(2)
        with col1:
            st.metric("Celková délka vektorů", f"{delka_rezu_m:.2f} m")
            st.metric("Čas zpracování strojem", f"{cas_v_minutach:.2f} min")
        with col2:
            st.metric("Interní výrobní náklady", f"{naklady_celkem:.2f} Kč")
            st.metric("Výsledná cena pro zákazníka", f"{cena_s_marzi:.2f} Kč", delta=f"Marže {marze_procento}%")
            
        with st.expander("🔍 Detail kalkulační matice"):
            st.write(f"**Náklady na stroj (odpisy, energie):** {naklady_stroj:.2f} Kč")
            st.write(f"**Lidská práce (manipulace/řez):** {naklady_prace:.2f} Kč")
    else:
        st.warning("V souboru nebyly nalezeny žádné měřitelné vektory. Ujistěte se, že výkres neobsahuje pouze vložený rastrový obrázek.")
