import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import networkx as nx
from database.postgres import SessionLocal
from database.models import Lecturer, Profile, Publication, Keyword, Collaboration, Recommendation

st.set_page_config(page_title="Lecturer Profiling Dashboard", page_icon="🎓", layout="wide")

@st.cache_data
def load_all_lecturers():
    db = SessionLocal()
    try:
        lecturers = db.query(Lecturer).order_by(Lecturer.full_name).all()
        return [{
            "code": l.code,
            "name": l.full_name,
            "name_with_title": l.full_name,
            "lecturer_code": l.lecturer_code,
            "research_group": l.research_group,
            "study_program": l.study_program,
            "field": l.field
        } for l in lecturers]
    finally:
        db.close()

@st.cache_data
def load_lecturer_detail(code):
    db = SessionLocal()
    try:
        lect = db.query(Lecturer).filter(Lecturer.code == code).first()
        if not lect:
            return None
            
        # Fetch profiles
        profs = db.query(Profile).filter(Profile.lecturer_id == lect.id).all()
        profiles_dict = {p.platform: p.url for p in profs}
        
        # Fetch publications
        pubs = db.query(Publication).filter(Publication.lecturer_id == lect.id).order_by(Publication.year.desc()).all()
        pub_titles = [p.title for p in pubs]
        
        # Fetch keywords
        kws = db.query(Keyword).filter(Keyword.lecturer_id == lect.id).all()
        keywords_list = [k.keyword for k in kws]
        
        # Fetch recommendations
        recs = db.query(Recommendation).filter(Recommendation.lecturer_id == lect.id).order_by(Recommendation.score.desc()).all()
        recommendations_list = []
        for r in recs:
            rec_lect = db.query(Lecturer).filter(Lecturer.id == r.recommended_lecturer_id).first()
            if rec_lect:
                recommendations_list.append({
                    "recommended_lecturer_id": rec_lect.code,
                    "score": r.score,
                    "reasons": r.reasons,
                    "name": rec_lect.full_name,
                    "research_group": rec_lect.research_group,
                    "lecturer_code": rec_lect.lecturer_code
                })
                
        return {
            "basic_info": {
                "name": lect.full_name,
                "code": lect.code,
                "lecturer_code": lect.lecturer_code,
                "study_program": lect.study_program,
                "research_group": lect.research_group,
                "academic_rank": lect.academic_rank,
                "field": lect.field
            },
            "identity": {
                "name_with_title": lect.full_name,
                "full_name": lect.full_name,
                "email": lect.email,
                "photo": lect.photo
            },
            "profiles": profiles_dict,
            "sinta_metrics": lect.sinta_metrics or {},
            "research": {
                "citation_count": lect.citation_count,
                "h_index": lect.h_index,
                "i10_index": lect.i10_index,
                "publication_titles": pub_titles,
                "keywords": keywords_list
            },
            "recommendations": recommendations_list
        }
    finally:
        db.close()

@st.cache_data
def load_db_stats():
    db = SessionLocal()
    try:
        total_lecturers = db.query(Lecturer).count()
        total_pubs = db.query(Publication).count()
        total_collabs = db.query(Collaboration).count()
        
        years_query = db.query(Publication.year).filter(Publication.year.isnot(None)).all()
        years = [y[0] for y in years_query]
        
        ai_cats_query = db.query(Lecturer.ai_categories).all()
        ai_categories = []
        for row in ai_cats_query:
            if row[0]:
                ai_categories.extend(row[0])
                
        study_progs_query = db.query(Lecturer.study_program).all()
        study_programs = [row[0] for row in study_progs_query if row[0]]
        
        rgroups_query = db.query(Lecturer.research_group).all()
        research_groups = [row[0] for row in rgroups_query if row[0]]
        
        return {
            "total_lecturers": total_lecturers,
            "total_pubs": total_pubs,
            "total_collabs": total_collabs,
            "years": years,
            "ai_categories": ai_categories,
            "study_programs": study_programs,
            "research_groups": research_groups
        }
    finally:
        db.close()

@st.cache_data
def load_db_collaborations():
    db = SessionLocal()
    try:
        collabs = db.query(Collaboration).order_by(Collaboration.collaboration_count.desc()).all()
        result = []
        for c in collabs:
            l1 = db.query(Lecturer).filter(Lecturer.id == c.lecturer_id_1).first()
            l2 = db.query(Lecturer).filter(Lecturer.id == c.lecturer_id_2).first()
            if l1 and l2:
                result.append({
                    "Lecturer 1": l1.full_name,
                    "Lecturer 2": l2.full_name,
                    "L1_Group": l1.research_group,
                    "L2_Group": l2.research_group,
                    "L1_Prodi": l1.study_program,
                    "L2_Prodi": l2.study_program,
                    "Papers Count": c.collaboration_count,
                    "Shared Publications": c.shared_publications
                })
        return result
    finally:
        db.close()

st.title("🎓 Lecturer Profiling & Recommendation Dashboard")

lecturers = load_all_lecturers()

if not lecturers:
    st.error("No lecturer data found in the database. Please run the sync script first.")
    st.stop()

# Sidebar for selection
st.sidebar.header("Search & Select Lecturer")

# Sidebar cache refresh
if st.sidebar.button("🔄 Clear Cache & Reload Data"):
    st.cache_data.clear()
    st.rerun()

# Search query
search_query = st.sidebar.text_input("🔍 Search by Name, NIP, Field, or Group", "").strip().lower()

# Filter options based on search query
if search_query:
    filtered_lecturers = []
    for l in lecturers:
        match_text = f"{l['name']} {l['name_with_title']} {l['code']} {l['field']} {l['study_program']} {l['research_group']}".lower()
        if search_query in match_text:
            filtered_lecturers.append(l)
else:
    filtered_lecturers = lecturers

if not filtered_lecturers:
    st.sidebar.warning("No lecturers match your search.")
    selected_code = None
else:
    # Create dropdown list
    options_map = {}
    for l in filtered_lecturers:
        name_display = l["name_with_title"]
        code = l["code"]
        lect_code = l["lecturer_code"]
        options_map[code] = f"{name_display} ({lect_code})" if lect_code else f"{name_display} ({code})"
        
    selected_code = st.sidebar.selectbox(
        "Choose a lecturer to view their profile and recommendations",
        options=list(options_map.keys()),
        format_func=lambda x: options_map[x]
    )

# 4-Tab Main Layout
tab1, tab2, tab3, tab4 = st.tabs(["👤 Lecturer Profiles", "📊 FIF Research Statistics", "🤝 Collaboration Network", "🔍 Database Inspector"])

# ================= TAB 1: LECTURER PROFILES =================
with tab1:
    if selected_code:
        lecturer = load_lecturer_detail(selected_code)
        if lecturer:
            basic = lecturer.get("basic_info", {})
            research = lecturer.get("research", {})
            identity = lecturer.get("identity", {})
            
            col1, col2 = st.columns([2, 1])
            
            with col1:
                full_name = identity.get("name_with_title") or identity.get("full_name") or basic.get("name", "Unknown")
                lect_code = basic.get("lecturer_code")
                if lect_code:
                    st.header(f"{full_name} ({lect_code})")
                else:
                    st.header(full_name)
                st.subheader(f"NIP / Code: {basic.get('code', selected_code)}")
                
                st.markdown("### Basic Information")
                st.write(f"**Study Program:** {basic.get('study_program', 'N/A')}")
                st.write(f"**Research Group:** {basic.get('research_group', 'N/A')}")
                st.write(f"**Academic Rank:** {basic.get('academic_rank', 'N/A')}")
                st.write(f"**Field:** {basic.get('field', 'N/A')}")
                if identity.get("email"):
                    st.write(f"**Email:** {identity.get('email')}")
                    
                # Display external profile links
                st.markdown("### Profiles & Links")
                profiles = lecturer.get("profiles", {})
                scopus_url = profiles.get("scopus")
                
                profile_links = []
                for platform in ["google_scholar", "sinta", "orcid", "scopus"]:
                    url = profiles.get(platform)
                    platform_label = platform.replace("_", " ").title()
                    if url:
                        if platform == "scopus" and not url.startswith("http"):
                            formatted_url = f"https://www.scopus.com/authid/detail.uri?authorId={url}"
                        else:
                            formatted_url = url
                        profile_links.append(f"[{platform_label}]({formatted_url})")
                    else:
                        profile_links.append(f"*{platform_label} (Unlinked)*")
                        
                if profile_links:
                    st.markdown(" | ".join(profile_links))
                else:
                    st.write("No external profile links found.")
                    
                st.write("")
                with st.expander("✏️ Manage Scopus Link"):
                    if scopus_url:
                        st.info(f"**Current Scopus Link:** {scopus_url}")
                    else:
                        st.warning("No Scopus link set for this profile.")
                        
                    scopus_input = st.text_input("Enter Scopus Author ID or Profile URL:", key=f"scopus_in_{selected_code}")
                    if st.button("Save Scopus Link", key=f"save_scopus_{selected_code}"):
                        if scopus_input:
                            import re
                            match = re.search(r'authorId=(\d+)', scopus_input)
                            if match:
                                author_id = match.group(1)
                            elif scopus_input.isdigit():
                                author_id = scopus_input
                            else:
                                digits = re.findall(r'\d+', scopus_input)
                                author_id = digits[0] if digits else None
                                    
                            if author_id:
                                new_scopus_url = f"https://www.scopus.com/authid/detail.uri?authorId={author_id}"
                                
                                try:
                                    db = SessionLocal()
                                    db_lect = db.query(Lecturer).filter(Lecturer.code == selected_code).first()
                                    if db_lect:
                                        sc_prof = db.query(Profile).filter(Profile.lecturer_id == db_lect.id, Profile.platform == 'scopus').first()
                                        if sc_prof:
                                            sc_prof.url = new_scopus_url
                                        else:
                                            db.add(Profile(lecturer_id=db_lect.id, platform='scopus', url=new_scopus_url))
                                        db.commit()
                                        st.success(f"Scopus link updated to: {new_scopus_url}")
                                        st.cache_data.clear()
                                        st.rerun()
                                    else:
                                        st.error("Lecturer not found in database.")
                                except Exception as db_err:
                                    st.error(f"Failed to update database: {db_err}")
                                finally:
                                    db.close()
                            else:
                                st.error("Could not parse a valid Scopus Author ID.")
                        else:
                            st.error("Please enter a value first.")
                    
            with col2:
                if identity.get("photo"):
                    st.image(identity.get("photo"), width=180)
                    
                st.markdown("### Research Profile (SINTA)")
                s_met = lecturer.get("sinta_metrics", {})
                if not s_met or not any(s_met.values()):
                    st.metric("Citations", research.get("citation_count", 0))
                    st.metric("h-index", research.get("h_index", 0))
                    st.metric("i10-index", research.get("i10_index", 0))
                else:
                    scopus_cit = s_met.get("scopus", {}).get("citation", 0)
                    scopus_h = s_met.get("scopus", {}).get("h_index", 0)
                    scopus_i10 = s_met.get("scopus", {}).get("i10_index", 0)
                    
                    gs_cit = s_met.get("google_scholar", {}).get("citation", 0)
                    gs_h = s_met.get("google_scholar", {}).get("h_index", 0)
                    gs_i10 = s_met.get("google_scholar", {}).get("i10_index", 0)
                    
                    sub_col1, sub_col2 = st.columns(2)
                    with sub_col1:
                        st.markdown("**Scopus**")
                        st.metric("Citations", scopus_cit)
                        st.metric("h-index", scopus_h)
                        st.metric("i10-index", scopus_i10)
                    with sub_col2:
                        st.markdown("**Scholar**")
                        st.metric("Citations", gs_cit)
                        st.metric("h-index", gs_h)
                        st.metric("i10-index", gs_i10)
         
            # SINTA Metrics Section
            sinta_metrics = lecturer.get("sinta_metrics", {})
            if sinta_metrics:
                st.divider()
                st.markdown("## 📊 SINTA Publications & Citations Metrics")
                
                metrics_rows = []
                keys = [
                    ("article", "Article"),
                    ("citation", "Citation"),
                    ("cited_document", "Cited Document"),
                    ("h_index", "H-Index"),
                    ("i10_index", "i10-Index"),
                    ("g_index", "G-Index")
                ]
                for key, label in keys:
                    metrics_rows.append({
                        "Metric": label,
                        "Scopus": sinta_metrics.get("scopus", {}).get(key, 0),
                        "Google Scholar": sinta_metrics.get("google_scholar", {}).get(key, 0),
                        "WOS": sinta_metrics.get("wos", {}).get(key, 0)
                    })
                
                df_metrics = pd.DataFrame(metrics_rows).set_index("Metric")
                st.table(df_metrics)
        
            st.divider()
        
            col_res, col_pub = st.columns(2)
            with col_res:
                st.markdown("### Research Interests & Keywords")
                interests = research.get("research_interests", [])
                keywords = research.get("keywords", [])
                
                if interests:
                    st.write("**Interests:**")
                    for interest in interests:
                        st.markdown(f"- {interest}")
                else:
                    st.write("No specific interests extracted.")
                    
                if keywords:
                    st.write("**Keywords:**")
                    st.write(", ".join(keywords))
                    
            with col_pub:
                st.markdown("### Publications")
                publications = research.get("publication_titles", [])
                if publications:
                    for pub in publications[:10]: # Show top 10
                        st.markdown(f"📄 {pub}")
                    if len(publications) > 10:
                        st.write(f"*...and {len(publications) - 10} more*")
                else:
                    st.write("No publications found.")
        
            st.divider()
            
            st.markdown("## 🤝 Recommended Collaborators")
            recommendations = lecturer.get("recommendations", [])
            
            if recommendations:
                rec_list = recommendations[:10]
                
                # Display top 3 prominently in cards
                st.markdown("### Top Matches")
                cols = st.columns(min(3, len(rec_list)))
                for idx, rec in enumerate(rec_list[:3]):
                    score = rec.get("score", 0)
                    reasons = rec.get("reasons", [])
                    rec_name = rec.get("name", "Unknown")
                    rec_group = rec.get("research_group", "")
                    rec_code = rec.get("recommended_lecturer_id")
                    rec_lect_code = rec.get("lecturer_code")
                    
                    with cols[idx]:
                        st.info(f"**Match Score: {score:.2f}**")
                        if rec_lect_code:
                            st.markdown(f"#### {rec_name} ({rec_lect_code})")
                        else:
                            st.markdown(f"#### {rec_name}")
                        st.write(f"NIP: `{rec_code}`")
                        st.write(f"Research Group: `{rec_group}`")
                        
                        if reasons:
                            st.write("**Reasons:**")
                            for reason in reasons:
                                st.write(f"- {reason}")
                                
                if len(rec_list) > 3:
                    st.markdown("### Other Potential Collaborators (Ranks 4-10)")
                    other_recs = []
                    for idx, rec in enumerate(rec_list[3:]):
                        score = rec.get("score", 0)
                        reasons = rec.get("reasons", [])
                        name = rec.get("name", "Unknown")
                        rec_code = rec.get("recommended_lecturer_id")
                        rec_lect_code = rec.get("lecturer_code", "")
                        if rec_lect_code:
                            name = f"{name} ({rec_lect_code})"
                        group = rec.get("research_group", "")
                        
                        other_recs.append({
                            "Rank": idx + 4,
                            "Name": name,
                            "Code": rec_code,
                            "Research Group": group,
                            "Match Score": f"{score:.2f}",
                            "Reasons": ", ".join(reasons) if reasons else "General research overlap"
                        })
                    df_recs = pd.DataFrame(other_recs)
                    st.dataframe(df_recs, use_container_width=True, hide_index=True)
            else:
                st.write("No recommendations generated for this lecturer.")
    else:
        st.info("Select a lecturer from the sidebar to view their profile.")

# ================= TAB 2: RESEARCH STATISTICS =================
with tab2:
    st.header("📊 FIF Research Statistics Summary")
    stats = load_db_stats()
    
    if not stats:
        st.warning("Could not load stats from the database.")
    else:
        m1, m2, m3 = st.columns(3)
        with m1:
            st.metric("Total Lecturers", stats["total_lecturers"])
        with m2:
            st.metric("Total Publications", stats["total_pubs"])
        with m3:
            st.metric("Total Collaborative Partnerships", stats["total_collabs"])
            
        st.divider()
        
        # 1. Publication Trend
        st.subheader("📈 Publications Trend by Year")
        if stats["years"]:
            df_years = pd.Series(stats["years"]).value_counts().reset_index()
            df_years.columns = ["Year", "Publications Count"]
            df_years = df_years.sort_values("Year")
            
            fig_years = px.bar(
                df_years, 
                x="Year", 
                y="Publications Count",
                color="Publications Count",
                color_continuous_scale="Viridis",
                labels={"Year": "Publication Year", "Publications Count": "Number of Publications"}
            )
            st.plotly_chart(fig_years, use_container_width=True)
        else:
            st.info("No publication year records available.")
            
        st.divider()
        
        # 2. AI Categories & Demographics
        c_ai, c_demo = st.columns([1, 1])
        
        with c_ai:
            st.subheader("🧠 Specialization Domains (AI & Computing)")
            if stats["ai_categories"]:
                df_ai = pd.Series(stats["ai_categories"]).value_counts().reset_index()
                df_ai.columns = ["AI Specialization", "Lecturer Count"]
                fig_ai = px.pie(
                    df_ai,
                    names="AI Specialization",
                    values="Lecturer Count",
                    hole=0.4,
                    color_discrete_sequence=px.colors.qualitative.Pastel
                )
                st.plotly_chart(fig_ai, use_container_width=True)
            else:
                st.info("No AI category mappings available.")
                
        with c_demo:
            st.subheader("🏫 Department / Study Program Breakdown")
            if stats["study_programs"]:
                df_prog = pd.Series(stats["study_programs"]).value_counts().reset_index()
                df_prog.columns = ["Study Program", "Count"]
                fig_prog = px.bar(
                    df_prog,
                    x="Count",
                    y="Study Program",
                    orientation="h",
                    color="Study Program",
                    color_discrete_sequence=px.colors.qualitative.Set3
                )
                st.plotly_chart(fig_prog, use_container_width=True)
            else:
                st.info("No Study Program data available.")
                
        st.divider()
        
        st.subheader("🔬 Research Group Distribution")
        if stats["research_groups"]:
            df_rg = pd.Series(stats["research_groups"]).value_counts().reset_index()
            df_rg.columns = ["Research Group", "Lecturers Count"]
            fig_rg = px.bar(
                df_rg,
                x="Research Group",
                y="Lecturers Count",
                color="Research Group",
                color_discrete_sequence=px.colors.qualitative.Safe
            )
            st.plotly_chart(fig_rg, use_container_width=True)

# ================= TAB 3: COLLABORATION NETWORK =================
with tab3:
    st.header("🤝 Collaboration Network & Co-Authorships")
    
    collabs = load_db_collaborations()
    
    if not collabs:
        st.info("No co-authorship relationships calculated in the database.")
    else:
        # Create sub-tabs inside Tab 3
        sub_tab_graph, sub_tab_list = st.tabs(["🕸️ Network Clusters Graph", "📋 Co-Authorship Directory"])
        
        # --- SUB-TAB 1: Network Graph ---
        with sub_tab_graph:
            st.subheader("Visualizing Research Group Clusters")
            st.write("This interactive force-directed graph displays connections between lecturers. Two lecturers are connected by an edge if they co-authored publications. The size of the node represents their number of connections, and the color indicates their **Research Group (CITI, SEAL, DSIS)**.")
            
            threshold = st.slider(
                "Filter connections: Min. shared publications between a pair",
                min_value=1,
                max_value=20,
                value=3,
                key="threshold_slider"
            )
            
            # Filter collabs by slider threshold
            filtered = [c for c in collabs if c["Papers Count"] >= threshold]
            
            if not filtered:
                st.warning(f"No collaborations found with at least {threshold} co-authored papers. Try lowering the filter value.")
            else:
                # Build networkx graph
                G = nx.Graph()
                groups = {}
                
                for c in filtered:
                    u, v = c["Lecturer 1"], c["Lecturer 2"]
                    G.add_edge(u, v, weight=c["Papers Count"])
                    groups[u] = c["L1_Group"] or "Unknown"
                    groups[v] = c["L2_Group"] or "Unknown"
                
                # Compute coordinates using spring layout
                pos = nx.spring_layout(G, k=0.4, seed=42)
                
                # Setup colors for CITI, SEAL, DSIS
                group_colors = {
                    "CITI": "#FF6B6B", # Red
                    "SEAL": "#4D96FF", # Blue
                    "DSIS": "#6BCB77", # Green
                    "Unknown": "#9E9E9E" # Grey
                }
                
                # 1. Edge lines trace
                edge_x = []
                edge_y = []
                for edge in G.edges():
                    x0, y0 = pos[edge[0]]
                    x1, y1 = pos[edge[1]]
                    edge_x.extend([x0, x1, None])
                    edge_y.extend([y0, y1, None])
                    
                edge_trace = go.Scatter(
                    x=edge_x, y=edge_y,
                    line=dict(width=1, color='#888'),
                    hoverinfo='none',
                    mode='lines'
                )
                
                # 2. Node markers trace
                node_x = []
                node_y = []
                node_text = []
                node_color = []
                node_size = []
                
                for node in G.nodes():
                    x, y = pos[node]
                    node_x.append(x)
                    node_y.append(y)
                    
                    deg = G.degree(node)
                    node_text.append(f"Lecturer: {node}<br>Group: {groups[node]}<br>Ties in graph: {deg}")
                    node_color.append(group_colors.get(groups[node], "#9E9E9E"))
                    node_size.append(10 + deg * 2.5) # Scale size by degree
                    
                node_trace = go.Scatter(
                    x=node_x, y=node_y,
                    mode='markers',
                    hoverinfo='text',
                    text=node_text,
                    marker=dict(
                        showscale=False,
                        color=node_color,
                        size=node_size,
                        line=dict(width=1.5, color='#fff')
                    )
                )
                
                # Build Figure
                fig = go.Figure(
                    data=[edge_trace, node_trace],
                    layout=go.Layout(
                        showlegend=False,
                        hovermode='closest',
                        margin=dict(b=0, l=0, r=0, t=10),
                        xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
                        yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
                        plot_bgcolor="rgba(0,0,0,0)",
                        paper_bgcolor="rgba(0,0,0,0)",
                        height=600
                    )
                )
                
                # Legend description
                st.markdown("""
                **Research Group Legend:** &nbsp;&nbsp;
                🔴 <span style="color:#FF6B6B">**CITI**</span> &nbsp;&nbsp;&nbsp;&nbsp;
                🔵 <span style="color:#4D96FF">**SEAL**</span> &nbsp;&nbsp;&nbsp;&nbsp;
                🟢 <span style="color:#6BCB77">**DSIS**</span> &nbsp;&nbsp;&nbsp;&nbsp;
                ⚪ <span style="color:#9E9E9E">**Unknown / None**</span>
                """, unsafe_allow_html=True)
                
                st.plotly_chart(fig, use_container_width=True)
                
                # Insights
                st.markdown("### 🔍 Network Statistics")
                i_col1, i_col2 = st.columns(2)
                with i_col1:
                    st.write(f"**Nodes in view (Lecturers):** {G.number_of_nodes()}")
                    st.write(f"**Edges in view (Collaboration Ties):** {G.number_of_edges()}")
                with i_col2:
                    # Find hubs
                    degrees = sorted(G.degree, key=lambda x: x[1], reverse=True)[:5]
                    st.write("**Top 3 Collaborative Hubs (Highest connections in view):**")
                    for name, deg in degrees[:3]:
                        st.markdown(f"- **{name}** ({groups[name]}) — *{deg} connections*")
                        
        # --- SUB-TAB 2: Co-Authorship List ---
        with sub_tab_list:
            st.subheader("📋 Search Co-Authorship Connections")
            
            # Search filter
            search_collab = st.text_input("🔍 Search Connections by Lecturer Name", "").strip().lower()
            
            if search_collab:
                filtered_collabs = [
                    c for c in collabs 
                    if search_collab in c["Lecturer 1"].lower() or search_collab in c["Lecturer 2"].lower()
                ]
            else:
                filtered_collabs = collabs
                
            st.markdown(f"Showing **{len(filtered_collabs)}** co-authorship connections.")
            
            # Display list of collaborations
            for idx, col in enumerate(filtered_collabs[:50]): # Show top 50
                with st.expander(f"🔗 {col['Lecturer 1']} ({col['L1_Group']}) & {col['Lecturer 2']} ({col['L2_Group']}) — {col['Papers Count']} Co-authored Papers"):
                    st.write(f"**Lecturer 1 Prodi:** {col['L1_Prodi']}")
                    st.write(f"**Lecturer 2 Prodi:** {col['L2_Prodi']}")
                    st.write("**Shared Publications:**")
                    for pub in col["Shared Publications"]:
                        st.write(f"- 📄 {pub}")
                        
            if len(filtered_collabs) > 50:
                st.write(f"*...and {len(filtered_collabs) - 50} more connections.*")

# ================= TAB 4: DATABASE INSPECTOR =================
with tab4:
    st.header("🔍 Database Column & Value Inspector")
    st.write("Inspect the raw database column values for the selected lecturer.")
    
    if selected_code:
        db = SessionLocal()
        try:
            lect = db.query(Lecturer).filter(Lecturer.code == selected_code).first()
            if lect:
                columns_data = []
                for column in Lecturer.__table__.columns:
                    val = getattr(lect, column.name)
                    # format json/list/vector values nicely
                    if isinstance(val, (list, dict)):
                        import json
                        val_str = json.dumps(val, indent=2)
                    else:
                        val_str = str(val)
                    columns_data.append({
                        "Column Name": column.name,
                        "Type": str(column.type),
                        "Value": val_str
                    })
                
                df_cols = pd.DataFrame(columns_data)
                st.dataframe(df_cols, use_container_width=True, hide_index=True, height=600)
            else:
                st.error("Lecturer not found in database.")
        except Exception as e:
            st.error(f"Error loading columns: {e}")
        finally:
            db.close()
    else:
        st.info("Select a lecturer from the sidebar to inspect their columns.")
