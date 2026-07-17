import streamlit as st
import pandas as pd
import os
import json
from database.postgres import SessionLocal
from database.models import Lecturer
from config import settings

st.set_page_config(page_title="Lecturer Column Inspector", page_icon="🔍", layout="wide")

st.title("🔍 Lecturer Column & Value Inspector Dashboard")
st.write("This dashboard allows you to inspect the raw database columns and local JSON properties for every lecturer.")

@st.cache_data
def load_all_lecturers():
    db = SessionLocal()
    try:
        lecturers = db.query(Lecturer).order_by(Lecturer.full_name).all()
        return [{"code": l.code, "name": l.full_name, "lecturer_code": l.lecturer_code} for l in lecturers]
    finally:
        db.close()

lecturers = load_all_lecturers()

if not lecturers:
    st.error("No lecturer data found in the database. Please run the sync script first.")
    st.stop()

# Sidebar for selection
st.sidebar.header("Select Lecturer")
search_query = st.sidebar.text_input("Search by Name or Code", "").strip().lower()

if search_query:
    filtered = [l for l in lecturers if search_query in l["name"].lower() or search_query in l["code"]]
else:
    filtered = lecturers

if not filtered:
    st.sidebar.warning("No matches found.")
    selected_code = None
else:
    options_map = {l["code"]: f"{l['name']} ({l['lecturer_code'] or l['code']})" for l in filtered}
    selected_code = st.sidebar.selectbox(
        "Choose a lecturer:",
        options=list(options_map.keys()),
        format_func=lambda x: options_map[x]
    )

if selected_code:
    # 2 columns layout: Left is Database, Right is Local JSON
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("🗄️ Database Columns & Values")
        db = SessionLocal()
        try:
            lect = db.query(Lecturer).filter(Lecturer.code == selected_code).first()
            if lect:
                columns_data = []
                for column in Lecturer.__table__.columns:
                    val = getattr(lect, column.name)
                    if isinstance(val, (list, dict)):
                        val_str = json.dumps(val, indent=2)
                    else:
                        val_str = str(val)
                    columns_data.append({
                        "Column Name": column.name,
                        "Type": str(column.type),
                        "Value": val_str
                    })
                df_cols = pd.DataFrame(columns_data)
                st.dataframe(df_cols, use_container_width=True, hide_index=True, height=650)
            else:
                st.error("Lecturer not found in database.")
        except Exception as e:
            st.error(f"Error: {e}")
        finally:
            db.close()
            
    with col2:
        st.subheader("📄 Local JSON File Content")
        json_path = os.path.join(settings.JSON_DIR, f"{selected_code}.json")
        if os.path.exists(json_path):
            st.code(f"File Path: {json_path}", language="bash")
            with open(json_path, 'r', encoding='utf-8') as f:
                json_data = json.load(f)
            st.json(json_data)
        else:
            st.warning(f"No local JSON file found at {json_path}")
else:
    st.info("Please select a lecturer from the sidebar to inspect.")
