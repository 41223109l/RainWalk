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

# 關閉不安全的連線警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ==========================================
# 0. 系統設定
# ==========================================
st.set_page_config(page_title="RainWalk Pro", page_icon="☔", layout="wide")

try:
    CWA_API_KEY = st.secrets["CWA_API_KEY"]
except:
    CWA_API_KEY = "CWA-42942699-8B8B-4B7B-8800-110D1D769E6D"

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

# --- 檢驗地點是否在北北基桃 ---
def is_valid_location(address):
    valid_keywords = ['台北', 'Taipei', '新北', 'New Taipei', '基隆', 'Keelung', '桃園', 'Taoyuan']
    # 檢查地址字串中是否包含上述任一關鍵字
    return any(keyword in address for keyword in valid_keywords)

# ==========================================
# 2. 介面與邏輯
# ==========================================

st.title("☔ RainWalk Pro: Smart Shelter Navigation")

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
    start_address = st.sidebar.text_input("Enter Departure Address (e.g., NTNU Library)", "")
    if st.sidebar.button("🔍 Search Coordinates"):
        geolocator = ArcGIS(timeout=10) 
        try:
            # 搜尋時加上 "Taiwan" 確保不會跑去國外
            query = f"{start_address} Taiwan"
            location = geolocator.geocode(query)
            
            if location:
                # 【新增功能】檢查是否在北北基桃
                if is_valid_location(location.address):
                    st.session_state.lat = location.latitude
                    st.session_state.lon = location.longitude
                    st.sidebar.success(f"Found: {location.address}")
                    st.rerun()
                else:
                    st.sidebar.error(f"⚠️ Location found: '{location.address}', but it is outside Taipei/New Taipei/Keelung/Taoyuan area.")
            else:
                st.sidebar.error("Address not found.")
        except Exception as e: 
            st.sidebar.error(f"Search failed: {e}")

st.sidebar.markdown("---")

final_lat = st.session_state
