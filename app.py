import streamlit as st
import pandas as pd
import geopandas as gpd
import folium
from streamlit_folium import st_folium
from geopy.distance import geodesic
# 使用 ArcGIS 避免被封鎖 IP
from geopy.geocoders import ArcGIS 
import requests
import osmnx as ox
import networkx as nx
from streamlit_js_eval import get_geolocation
import urllib3
import os

ox.settings.user_agent = "RainWalk_Student_Project_NTNU" 

# 建議同時開啟快取，避免重複下載浪費時間
ox.settings.use_cache = True
# 關閉不安全的連線警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ==========================================
# 0. 系統設定
# ==========================================
st.set_page_config(page_title="RainWalk", page_icon="☔", layout="wide")

# 嘗試從 Streamlit Secrets 讀取，如果沒有就報錯，強迫自己去設定環境變數，而不是寫死在程式碼裡
if "CWA_API_KEY" in st.secrets:
    CWA_API_KEY = st.secrets["CWA_API_KEY"]
else:
    # 這裡可以改成從環境變數讀取，或者直接報錯提示
    st.error("找不到 API Key，請設定 Secrets！")
    st.stop()

API_URL = "https://opendata.cwa.gov.tw/api/v1/rest/datastore/O-A0001-001"

# ==========================================
# 1. 核心功能函式
# ==========================================

@st.cache_data(ttl=600)
def get_weather_data(user_lat, user_lon):
    if "CWA-" not in CWA_API_KEY:
        return None, "API Key Error"

    params = {"Authorization": CWA_API_KEY, "format": "JSON", "StationStatus": "OPEN"}
    try:
        # verify=False 解決 SSL 錯誤
        response = requests.get(API_URL, params=params, timeout=10, verify=False)
        
        if response.status_code != 200:
            return None, f"API Error: {response.status_code}"
            
        data = response.json()
        if "records" not in data: 
            return None, "Data Format Error"
        
        stations = data['records']['Station']
        min_dist = float('inf')
        nearest_station = None

        for s in stations:
            try:
                lat = float(s['GeoInfo']['Coordinates'][1]['StationLatitude'])
                lon = float(s['GeoInfo']['Coordinates'][1]['StationLongitude'])
                dist = (lat - user_lat)**2 + (lon - user_lon)**2
                if dist < min_dist:
                    min_dist = dist
                    nearest_station = s
            except: continue 

        if nearest_station:
            w_elem = nearest_station.get('WeatherElement', {})
            rain = 0.0
            if 'Precipitation' in w_elem: 
                rain = float(w_elem['Precipitation'])
            elif 'Now' in w_elem and 'Precipitation' in w_elem['Now']: 
                rain = float(w_elem['Now']['Precipitation'])
            if rain < 0: rain = 0.0
            
            desc = w_elem.get('Weather', 'Observing')
            
            desc_en = desc
            if "雷" in desc: desc_en = "Thunderstorm"
            elif "雨" in desc: desc_en = "Rainy"
            elif "晴" in desc: desc_en = "Sunny"
            elif "陰" in desc or "雲" in desc: desc_en = "Cloudy"
            
            return {"station": nearest_station.get('StationName'), "rain": rain, "desc": desc, "desc_en": desc_en}, None
            
    except Exception as e: 
        return None, f"Connect Error: {str(e)}"
    return None, "No Data Found"

@st.cache_data
def load_map_data():
    raingo = pd.DataFrame()
    try: 
        raingo = pd.read_csv('raingo.csv')
    except: 
        try: raingo = pd.read_csv('raingo共享傘租借站-大安區-20250613.csv')
        except: pass
    
    arcade = gpd.GeoDataFrame()
    try:
        shp_path = 'Finishgfl97.shp'
        arcade = gpd.read_file(shp_path, encoding='big5')
        if arcade.crs is None: arcade.set_crs(epsg=3826, inplace=True)
        arcade = arcade.to_crs(epsg=4326)
        check = arcade[arcade['GFL_ZONE'] == '大安區']
        
        if check.empty:
            arcade = gpd.read_file(shp_path, encoding='utf-8')
            if arcade.crs is None: arcade.set_crs(epsg=3826, inplace=True)
            arcade = arcade.to_crs(epsg=4326)
            check = arcade[arcade['GFL_ZONE'] == '大安區']
            
        if not check.empty: arcade = check
    except Exception as e:
        st.sidebar.error(f"Map Load Error: {e}")
    
    return raingo, arcade

@st.cache_resource
def load_road_network_optimized(_gdf_arcade): 
    with st.spinner('Analyzing road network data (GIS processing)...'):
        G = ox.graph_from_place("Daan District, Taipei, Taiwan", network_type='walk')
        gdf_edges = ox.graph_to_gdfs(G, nodes=False, fill_edge_geometry=True)
        gdf_edges_proj = gdf_edges.to_crs(epsg=3826)
        
        sheltered_indices = set()
        if not _gdf_arcade.empty:
            arcade_proj = _gdf_arcade.to_crs(epsg=3826)
            arcade_proj['buffer'] = arcade_proj.geometry.buffer(25) 
            arcade_buffer = arcade_proj.set_geometry('buffer')
            sheltered_edges = gpd.sjoin(gdf_edges_proj, arcade_buffer, how='inner', predicate='intersects')
            sheltered_indices = set(sheltered_edges.index)
        
        forced_arcades = ['和平東路', '信義路', '新生南路', '復興南路', '敦化南路', '羅斯福路', '仁愛路', '建國南路', '忠孝東路', '大安路', '金山南路']

        count = 0
        for u, v, k, data in G.edges(keys=True, data=True):
            length = data['length']
            raw_name = data.get('name', '')
            name_str = "".join(raw_name) if isinstance(raw_name, list) else str(raw_name)
            
            is_sheltered = False
            if (u, v, k) in sheltered_indices: is_sheltered = True
            if not is_sheltered:
                for key in forced_arcades:
                    if key in name_str:
                        is_sheltered = True
                        break
            
            if is_sheltered:
                data['rain_cost'] = length * 1.0 
                count += 1
            else:
                data['rain_cost'] = length * 1.5 
        
        print(f"Network analysis complete: Marked {count} sheltered edges.")
        return G

# --- 經緯度範圍檢查 (Bounding Box) ---
def check_bounds(lat, lon):
    # 北北基桃 大致範圍
    # 緯度: 24.5 (苗栗/新竹交界) ~ 25.4 (北海岸)
    # 經度: 120.8 (桃園西側) ~ 122.1 (基隆東側)
    if 24.5 <= lat <= 25.4 and 120.8 <= lon <= 122.1:
        return True
    return False

# ==========================================
# 2. 介面與邏輯
# ==========================================

st.title("☔ RainWalk: Smart Shelter Navigation")

df_raingo, gdf_arcade = load_map_data()

try:
    G = load_road_network_optimized(gdf_arcade)
except Exception as e:
    st.error(f"Failed to load network: {e}")
    st.stop()

# --- Sidebar: Location ---
st.sidebar.header("📍 Set Departure")

default_lat = 25.0264
default_lon = 121.5282
if 'lat' not in st.session_state: st.session_state.lat = default_lat
if 'lon' not in st.session_state: st.session_state.lon = default_lon

# GPS
use_gps = st.sidebar.checkbox("📡 Use GPS Positioning", value=False)
if use_gps:
    loc = get_geolocation(component_key='get_loc')
    if loc:
        new_lat = loc['coords']['latitude']
        new_lon = loc['coords']['longitude']
        if abs(st.session_state.lat - new_lat) > 0.00001:
            st.session_state.lat = new_lat
            st.session_state.lon = new_lon
            st.rerun()

# Address Input
if not use_gps:
    start_address = st.sidebar.text_input(
    "Enter Departure Address", 
    value="", 
    placeholder="e.g., 師大路39巷14號 (Please use Address, not Shop Name)"
)
    if st.sidebar.button("🔍 Search Coordinates"):
        geolocator = ArcGIS(timeout=10) 
        try:
            query = f"{start_address} Taiwan"
            location = geolocator.geocode(query)
            
            if location:
                # 使用經緯度檢查是否在北北基桃
                if check_bounds(location.latitude, location.longitude):
                    st.session_state.lat = location.latitude
                    st.session_state.lon = location.longitude
                    st.sidebar.success(f"Found: {location.address}")
                    st.rerun()
                else:
                    # 抓到外縣市的結果，顯示警告並建議使用者加上縣市
                    st.sidebar.error(f"⚠️ Found location in '{location.address}', but it is too far (outside Taipei Area).")
                    st.sidebar.info(f"💡 Tip: Please add 'Taipei' or 'New Taipei' to your search (e.g., 'Taipei {start_address}').")
            else:
                st.sidebar.error("Address not found.")
        except Exception as e: 
            st.sidebar.error(f"Search failed: {e}")

st.sidebar.markdown("---")

final_lat = st.session_state.lat
final_lon = st.session_state.lon
start_loc = [final_lat, final_lon]

st.sidebar.caption(f"Current Coords: {final_lat:.5f}, {final_lon:.5f}")


# --- Weather Visualization ---
st.sidebar.header("🌦️ Current Weather")
weather_info, w_err = get_weather_data(final_lat, final_lon)

if weather_info:
    rain_val = weather_info['rain']
    desc_text = weather_info['desc']
    desc_en = weather_info['desc_en']
    
    w_icon = "☁️" 
    w_color = "gray"
    
    if "雷" in desc_text:
        w_icon = "⛈️"
        w_color = "#FF0000"
    elif "雨" in desc_text:
        if rain_val > 10 or "豪" in desc_text or "大" in desc_text:
            w_icon = "🌧️"
            w_color = "blue"
        else:
            w_icon = "🌦️"
            w_color = "lightblue"
    elif "晴" in desc_text:
        w_icon = "☀️"
        w_color = "orange"
    else:
        w_icon = "☁️"
        w_color = "gray"

    c1, c2 = st.sidebar.columns([1, 2])
    with c1:
        st.markdown(f"<div style='font-size: 60px; text-align: center;'>{w_icon}</div>", unsafe_allow_html=True)
    with c2:
        st.metric(label="Rainfall (mm)", value=f"{rain_val}")
        st.caption(f"Condition: {desc_en}")
else:
    st.sidebar.warning(f"Weather Status: {w_err}")

# --- Navigation & Layers ---
st.sidebar.header("🏁 Navigation & Layers")

dest_input = st.sidebar.text_input(
    "Enter Destination", 
    value="",  
    placeholder="e.g., 和平東路一段129號"
)

mode = st.sidebar.radio("Navigation Mode", 
                        ["🚶 No Umbrella (Find nearest Raingo)", 
                         "☂️ Smart Shelter Navigation (Arcades)"])

show_arcade = st.sidebar.checkbox("🟦 Show Arcade Coverage (Blue Zones)", value=True)

# --- Map Drawing ---
m = folium.Map(location=start_loc, zoom_start=15)
folium.Marker(start_loc, popup="Start", icon=folium.Icon(color='blue', icon='user')).add_to(m)

if show_arcade and not gdf_arcade.empty:
    folium.GeoJson(
        gdf_arcade,
        name='Arcade Area',
        style_function=lambda x: {'color': '#0000FF', 'weight': 0, 'fillOpacity': 0.3},
        tooltip='Arcade Zone'
    ).add_to(m)

# --- Path Planning ---

if mode == "🚶 No Umbrella (Find nearest Raingo)" and not df_raingo.empty:
    min_dist = float('inf')
    nearest = None
    for idx, row in df_raingo.iterrows():
        site_loc = [row['緯度'], row['經度']]
        dist = geodesic(start_loc, site_loc).meters
        folium.CircleMarker(site_loc, radius=5, color='green', fill=True, popup=row['租借站名稱']).add_to(m)
        if dist < min_dist:
            min_dist = dist
            nearest = row
    
    if nearest is not None:
        dest_coords = [nearest['緯度'], nearest['經度']]
        st.success(f"Recommended Station: {nearest['租借站名稱']}")
        try:
            orig_node = ox.distance.nearest_nodes(G, final_lon, final_lat)
            dest_node = ox.distance.nearest_nodes(G, dest_coords[1], dest_coords[0])
            route = nx.shortest_path(G, orig_node, dest_node, weight='length')
            path_nodes = [(G.nodes[n]['y'], G.nodes[n]['x']) for n in route]
            full_path = [start_loc] + path_nodes + [dest_coords]
            folium.PolyLine(full_path, color='green', weight=5, opacity=0.8).add_to(m)
            folium.Marker(dest_coords, icon=folium.Icon(color='green', icon='umbrella', prefix='fa')).add_to(m)
        except Exception as e:
            st.warning(f"Path planning failed, drawing straight line.")
            folium.PolyLine([start_loc, dest_coords], color="green").add_to(m)

elif mode == "☂️ Smart Shelter Navigation (Arcades)" and dest_input:
    geolocator = ArcGIS(timeout=10)
    try:
        query = f"{dest_input} Taiwan"
        loc = geolocator.geocode(query)
        if loc:
            # 同樣加上邊界檢查
            if check_bounds(loc.latitude, loc.longitude):
                dest_coords = [loc.latitude, loc.longitude]
                folium.Marker(dest_coords, popup=dest_input, icon=folium.Icon(color='red', icon='flag')).add_to(m)
                try:
                    orig_node = ox.distance.nearest_nodes(G, final_lon, final_lat)
                    target_node = ox.distance.nearest_nodes(G, dest_coords[1], dest_coords[0])
                    
                    route = nx.shortest_path(G, orig_node, target_node, weight='rain_cost')
                    path_nodes = [(G.nodes[n]['y'], G.nodes[n]['x']) for n in route]
                    full_path = [start_loc] + path_nodes + [dest_coords]
                    folium.PolyLine(full_path, color='#FFD700', weight=6, opacity=0.9, tooltip="Best Sheltered Route").add_to(m)
                    
                    shortest_route = nx.shortest_path(G, orig_node, target_node, weight='length')
                    short_nodes = [(G.nodes[n]['y'], G.nodes[n]['x']) for n in shortest_route]
                    folium.PolyLine([start_loc]+short_nodes+[dest_coords], color='blue', weight=3, dash_array='5', opacity=0.5, tooltip="Shortest Path (Unsheltered)").add_to(m)
                    
                    st.success("✨ Route planning complete! Gold line indicates the best sheltered path.")
                except Exception as e:
                    st.error(f"Path calculation error: {e}")
                    folium.PolyLine([start_loc, dest_coords], color="blue", dash_array='5').add_to(m)
            else:
                 st.error(f"⚠️ Destination '{loc.address}' is outside the supported area (North Taiwan only).")
                 st.info(f"💡 Tip: Try adding 'Taipei' to your search (e.g., 'Taipei {dest_input}').")
    except Exception as e:
        st.error(f"Destination Search Failed: {e}")

st_folium(m, width=800, height=600)



