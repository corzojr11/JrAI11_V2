import streamlit as st
import pandas as pd
from datetime import datetime
import plotly.express as px

from database import init_db, get_all_picks, update_resultado, save_picks
from import_utils import validate_and_load_file
from backtest_engine import calcular_metricas, es_handicap_asiatico
from config import IAS_LIST, STAKE_PORCENTAJE

st.set_page_config(page_title="Backtesting Multi-IA", layout="wide")
init_db()

st.title("🏆 Backtesting Multi-IA – Sistema de Apuestas")
st.caption("Versión 2.0 | 26/02/2026")

tab1, tab2, tab3, tab4 = st.tabs(["📊 Dashboard", "📥 Importar Picks", "✅ Registrar Resultados", "📋 Detalle & Export"])

# ====================== DASHBOARD ======================
with tab1:
    metrics = calcular_metricas()
    
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Bankroll Actual", f"${metrics['bankroll_actual']:.2f}", 
                f"{((metrics['bankroll_actual']/1000)-1)*100:+.1f}%")
    col2.metric("Total Picks", metrics['total_picks'])
    
    # Calcular porcentaje de acierto ponderado (las medias cuentan como medio acierto)
    acierto_ponderado = (metrics['ganadas'] + metrics['medias']/2) / max(1, metrics['total_picks']) * 100
    col3.metric("Acierto", f"{acierto_ponderado:.1f}%")
    col4.metric("ROI Global", f"{metrics['roi_global']}%")

    colA, colB = st.columns(2)
    
    with colA:
        if not metrics['evolucion'].empty:
            fig_bank = px.line(metrics['evolucion'], x='fecha', y='bankroll', 
                               title="Evolución del Bankroll", markers=True)
            st.plotly_chart(fig_bank, use_container_width=True)
        else:
            st.info("📉 No hay suficientes datos para mostrar la evolución del bankroll. Importa picks y registra resultados primero.")

    with colB:
        if not metrics['df_ia'].empty:
            fig_roi = px.bar(metrics['df_ia'], x='ia', y='roi', 
                             title="ROI por IA", color='roi', color_continuous_scale='RdYlGn')
            st.plotly_chart(fig_roi, use_container_width=True)
        else:
            st.info("📊 No hay datos de ROI por IA. Registra resultados para ver métricas.")

# ====================== IMPORTAR PICKS ======================
with tab2:
    st.subheader("Subir archivos de texto con los picks")
    st.markdown("Formato esperado: IA, FECHA, ---, PARTIDO, MERCADO, SELECCION, CUOTA, CONFIANZA, ANALISIS")
    
    uploaded_files = st.file_uploader("Selecciona uno o varios archivos .txt", type="txt", accept_multiple_files=True)
    
    if uploaded_files:
        all_dfs = []
        for file in uploaded_files:
            try:
                df = validate_and_load_file(file)
                all_dfs.append(df)
                st.success(f"✅ {file.name} cargado correctamente")
            except Exception as e:
                st.error(f"❌ {file.name}: {e}")
        
        if all_dfs:
            preview = pd.concat(all_dfs, ignore_index=True)
            st.dataframe(preview, use_container_width=True)
            
            if st.button("🚀 Importar todos los picks seleccionados"):
                batch = datetime.now().strftime("%Y%m%d_%H%M%S")
                save_picks(preview, batch)
                st.success(f"¡{len(preview)} picks importados en batch {batch}!")
                st.rerun()

# ====================== REGISTRAR RESULTADOS ======================
with tab3:
    df = get_all_picks()
    if df.empty:
        st.info("📭 Aún no hay picks. Importa primero desde la pestaña 'Importar Picks'.")
    else:
        pendiente = df[df['resultado'] == 'pendiente']
        if pendiente.empty:
            st.success("✅ ¡Todos los picks ya tienen resultado!")
        else:
            st.subheader(f"⏳ Picks pendientes: {len(pendiente)}")
            for idx, row in pendiente.iterrows():
                with st.container():
                    cols = st.columns([3, 2, 1.5, 2])
                    cols[0].write(f"**{row['ia']}** – {row['partido']} | {row['mercado']} @ {row['cuota']}")
                    cols[1].write(row['seleccion'])
                    
                    opciones = ['ganada', 'perdida']
                    if es_handicap_asiatico(row['seleccion']):
                        opciones.append('media')
                    
                    nuevo = cols[2].selectbox("Resultado", opciones, key=f"res_{row['id']}", label_visibility="collapsed")
                    if cols[3].button("Guardar", key=f"btn_{row['id']}"):
                        update_resultado(row['id'], nuevo)
                        st.success(f"Guardado: {row['seleccion']} → {nuevo}")
                        st.rerun()
                    st.divider()

# ====================== DETALLE & EXPORT ======================
with tab4:
    df = get_all_picks()
    if not df.empty:
        st.dataframe(df, use_container_width=True)
        
        col1, col2, col3 = st.columns(3)
        if col1.button("📥 Exportar CSV completo"):
            csv = df.to_csv(index=False)
            st.download_button("Descargar CSV", csv, "backtest_completo.csv", "text/csv")
        
        if col2.button("🗑️ Borrar TODOS los datos (reset)"):
            if st.checkbox("⚠️ Confirmo que quiero borrar todo"):
                from database import delete_all_picks
                delete_all_picks()
                st.success("Base de datos reseteada")
                st.rerun()
    else:
        st.info("📭 No hay datos para mostrar. Importa picks primero.")

st.sidebar.success("✅ App funcionando • Stake fijo 2% • SQLite local • Formato TXT")