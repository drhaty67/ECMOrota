import streamlit as st

from rota_app.storage import StorageError, build_store
from rota_app.ui import PAGES

st.set_page_config(page_title="Consultant Rota", page_icon="🗓️", layout="wide", initial_sidebar_state="expanded")
st.markdown("""<style>
  .stApp { background: #f7f8fb; }
  [data-testid='stSidebar'] { background: #10233f; }
  [data-testid='stSidebar'] * { color: #f7fafc; }
  h1, h2, h3 { color: #14213d; letter-spacing: -.02em; }
  .rule { background:white; border:1px solid #e2e8f0; border-radius:12px; padding:14px 16px; margin:9px 0; box-shadow:0 2px 8px rgba(15,23,42,.04); }
  .rule span { display:inline-block; color:#0f766e; font-weight:700; width:38px; }
  div[data-testid='stMetric'] { background:white; border:1px solid #e2e8f0; padding:14px; border-radius:14px; }
</style>""", unsafe_allow_html=True)

try:
    store = build_store(st.secrets)
except (StorageError, FileNotFoundError) as exc:
    st.error(f"Storage configuration error: {exc}")
    st.stop()
if "rota_state" not in st.session_state:
    try:
        st.session_state.rota_state = store.load()
    except StorageError as exc:
        st.error(str(exc)); st.info("Check the Supabase migration and Streamlit secrets, then reboot the app."); st.stop()

with st.sidebar:
    st.markdown("## Consultant Rota")
    st.caption("Drafting workspace")
    page = st.radio("Navigation", list(PAGES), label_visibility="collapsed")
    st.divider()
    st.caption(f"{store.backend_name} · {st.session_state.rota_state['period']['status']}")
    if st.button("Reset demo data", use_container_width=True):
        st.session_state.rota_state = store.reset(); st.rerun()

PAGES[page](st.session_state.rota_state, store)
