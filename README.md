[![Streamlit App](https://static.streamlit.io/badges/streamlit_badge_black_white.svg)](https://rainwalk-qngbk8fztagh8auyryg6ck.streamlit.app/)

# ☔ RainWalk
This is a final project for the Data Science and Computer Programming course at NTNU.

## 📌 Project Overview
RainWalk is a Geospatial Web application built with **Python** and **Streamlit**. It aims to enhance the walking experience in Taipei—a city known for its frequent rainfall—by integrating real-time meteorological data with urban spatial analysis.

## 🎬 Project Demonstration
[![Watch the video](https://img.youtube.com/vi/H1cTaqjRts0/maxresdefault.jpg)](https://youtu.be/H1cTaqjRts0)
*Click the image above to watch the 1-minute project demonstration.*

## 🚀 Key Features
- **Real-time Weather Integration**: Fetches live data via the **Central Weather Administration (CWA) API**. The UI features dynamic weather icons and displays current rainfall and humidity levels based on the user's vicinity.
- **Real-time GPS Positioning**: Automatically detects the user's current coordinates to set as the starting point for navigation, providing a seamless "locate-and-go" experience.
- **Dual Routing Modes**:
  - **No Umbrella Mode**: Locates and navigates to the nearest **Raingo** shared-umbrella station using geodesic distance.
  - **Smart Shelter Mode**: An experimental routing system that prioritizes Taipei’s unique **arcade (騎樓) network** to help pedestrians stay dry.
- **Geographic Safety Guard**: Implements a **bounding box** constraint for Northern Taiwan (Taipei/New Taipei City). The system provides an automated warning if a user searches outside the supported service area to ensure data reliability.

## ⚙️ Technical Reflection & Algorithms
The core logic utilizes a **weighted routing algorithm**. By assigning a higher "cost" to unsheltered road segments, the system attempts to calculate paths that maximize arcade coverage. 

**Current Limitations:**
- **Network Topology**: Due to map resolution and node-snapping limitations, some paths may occasionally clip through buildings or result in suboptimal detours.
- **Search Scope**: The current geocoding service is optimized for exact address inputs rather than general place names.

## 🛠️ Future Work
- **Refining Network Topology**: Improving road network connectivity to eliminate geometric errors.
- **Enhanced Search API**: Integrating Google Places or similar APIs to support keyword-based location searching.
- **Weight Optimization**: Tuning algorithm parameters to better simulate realistic human walking decisions in various rain intensities.

## Acknowledgments
Special thanks to the **RainGo** team for providing the dataset of umbrella rental stations in Daan District. Their support made the “No Umbrella” navigation feature possible.
*Developed as a Final Project for the DSCP Course at NTNU.*
