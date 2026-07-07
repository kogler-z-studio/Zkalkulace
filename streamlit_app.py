import streamlit as st
import ezdxf
import math
import tempfile

# 1. Funkce pro výpočet délky všech entit v DXF
def spocitej_metraz_dxf(file_bytes):
    # Streamlit dává soubory v bajtech, musíme je dočasně uložit pro ezdxf knihovnu
    with tempfile.NamedTemporaryFile(delete=False, suffix=".dxf") as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name

    try:
        doc = ezdxf.readfile(tmp_path)
        msp = doc.modelspace()
        celkova_delka_mm = 0.0

        for entity in msp:
            # Úsečky (Lines)
            if entity.dxftype() == 'LINE':
                celkova_delka_mm += math.dist(entity.dxf.start, entity.dxf.end)
            
            # Kružnice (Circles)
            elif entity.dxftype() == 'CIRCLE':
                celkova_delka_mm += 2 * math.pi * entity.dxf.radius
            
            # Oblouky (Arcs)
            elif entity.dxftype() == 'ARC':
                # Přibližný výpočet délky oblouku
                r = entity.dxf.radius
                start_w = entity.dxf.start_angle
                end_w = entity.dxf.end_angle
                if end_w < start_w:
                    end_w += 360
                uhel = end_w - start_w
                celkova_delka_mm += (2 * math.pi * r) * (uhel / 360.0)
            
            # Složité křivky (Polylines / LwPolyline) - často používané v rozvinech
            elif entity.dxftype() in ('LWPOLYLINE', 'POLYLINE'):
                points = entity.get_points() if entity.dxftype() == 'POLYLINE' else entity.vertices()
                # Spočítá vzdálenosti mezi body křivky
                pts = [p for p in points]
                for i in range(len(pts) - 1):
                    celkova_delka_mm += math.dist(pts[i][:2], pts[i+1][:2])
                if entity.closed:
                    celkova_delka_mm += math.dist(pts[-1][:2], pts[0][:2])

        return celkova_delka_mm / 1000.0 # Převod na metry
    except Exception as e:
        st.error(f"Chyba při zpracování DXF: {e}")
        return None

# 2. Webové rozhraní aplikace
st.set_page_config(page_title="Firemní DXF Kalkulačka", layout="centered")
st.title("🧮 Výrobní kalkulátor z DXF rozvinů")
st.write("Nahrajte soubor .dxf, zadejte parametry a systém spočítá náklady.")

# Nahrání souboru
uploaded_file = st.file_uploader("Vyberte DXF soubor rozvinu", type=["dxf"])

# Vstupní parametry (Kalkulační matice)
st.sidebar.header("⚙️ Nastavení nákladů a stroje")
rychlost_stroje = st.sidebar.number_input("Rychlost řezu (mm/min)", value=2000, step=100)
cena_stroj_hod = st.sidebar.number_input("Odpisy a servis stroje (Kč/hod)", value=450, step=10)
cena_prace_hod = st.sidebar.number_input("Mzda operátora (Kč/hod)", value=350, step=10)
prikon_stroje = st.sidebar.number_input("Příkon stroje (kW)", value=15.0, step=1.0)
cena_elektřina_kwh = st.sidebar.number_input("Cena elektřiny (Kč/kWh)", value=5.5, step=0.1)
marze_procento = st.sidebar.number_input("Požadovaná marže (%)", value=20, step=5)

if uploaded_file is not None:
    bytes_data = uploaded_file.getvalue()
    
    with st.spinner("Analyzuji geometrii..."):
        delka_rezu_m = spocitej_metraz_dxf(bytes_data)
        
    if delka_rezu_m:
        delka_rezu_mm = delka_rezu_m * 1000
        
        # Výpočty času a ekonomiky
        cas_v_minutach = delka_rezu_mm / rychlost_stroje
        cas_v_hodinach = cas_v_minutach / 60
        
        naklady_stroj = cas_v_hodinach * cena_stroj_hod
        naklady_prace = cas_v_hodinach * cena_prace_hod
        naklady_elektro = cas_v_hodinach * prikon_stroje * cena_elektřina_kwh
        
        naklady_celkem = naklady_stroj + naklady_prace + naklady_elektro
        cena_s_marzi = naklady_celkem * (1 + (marze_procento / 100))
        
        # Výstup pro uživatele
        st.success("Analýza hotova!")
        
        col1, col2 = st.columns(2)
        with col1:
            st.metric("Celková délka hran (řezu)", f"{delka_rezu_m:.2f} m")
            st.metric("Odhadovaný čas výroby", f"{cas_v_minutach:.2f} min")
        with col2:
            st.metric("Čisté výrobní náklady", f"{naklady_celkem:.2f} Kč")
            st.metric("Doporučená cena (s marží)", f"{cena_s_marzi:.2f} Kč", delta=f"Marže {marze_procento}%")
            
        # Detailní rozpad
        with st.expander("🔍 Zobrazit detailní rozpad nákladů"):
            st.write(f"**Režie stroje:** {naklady_stroj:.2f} Kč")
            st.write(f"**Lidská práce:** {naklady_prace:.2f} Kč")
            st.write(f"**Spotřebovaná energie:** {naklady_elektro:.2f} Kč")
