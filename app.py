import datetime
import pandas as pd
import pydeck as pdk
import requests
import streamlit as st

st.set_page_config(page_title="TaxiFareModel", page_icon="🚕", layout="wide")

if "history" not in st.session_state:
    st.session_state.history = []

if "pickup_address" not in st.session_state:
    st.session_state.pickup_address = ""

if "dropoff_address" not in st.session_state:
    st.session_state.dropoff_address = ""


def swap_addresses():
    st.session_state.pickup_address, st.session_state.dropoff_address = (
        st.session_state.dropoff_address,
        st.session_state.pickup_address,
    )


def safe_json(response, source_name):
    try:
        return response.json()
    except Exception:
        st.error(f"{source_name} did not return valid JSON.")
        st.write("URL:", response.url)
        st.write("Status code:", response.status_code)
        st.code(response.text[:500])
        return None


@st.cache_data(show_spinner=False)
def geocode_address(address):
    geocode_url = "https://photon.komoot.io/api"

    params = {
        "q": address,
        "limit": 1,
        "lat": 40.7580,
        "lon": -73.9855,
    }

    headers = {
        "User-Agent": "TaxiFareModel/1.0",
        "Accept": "application/json",
    }

    response = requests.get(
        geocode_url,
        params=params,
        headers=headers,
        timeout=20,
    )

    if response.status_code != 200:
        return None, None, None, f"Geocoding API error ({response.status_code})"

    data = safe_json(response, "Photon")


    features = data.get("features", [])
    if not features:
        return None, None, None, "No result found for this address."

    feature = features[0]
    coordinates = feature["geometry"]["coordinates"]
    properties = feature.get("properties", {})

    longitude = float(coordinates[0])
    latitude = float(coordinates[1])

    name = properties.get("name", "")
    street = properties.get("street", "")
    house_number = properties.get("housenumber", "")
    city = properties.get("city", "")
    state = properties.get("state", "")

    display_name = ", ".join(
        part for part in [
            " ".join(part for part in [house_number, street] if part).strip(),
            name,
            city,
            state,
        ] if part
    ).strip()

    if not display_name:
        display_name = address

    return latitude, longitude, display_name, None


def build_route_layers(route_style, pickup_lon, pickup_lat, dropoff_lon, dropoff_lat):
    route_segments = None
    route_path = None
    distance_km = None
    duration_min = None

    if route_style == "Straight line":
        route_segments = pd.DataFrame(
            [
                {
                    "start_lon": pickup_lon,
                    "start_lat": pickup_lat,
                    "end_lon": dropoff_lon,
                    "end_lat": dropoff_lat,
                }
            ]
        )

    elif route_style == "Manhattan grid":
        turn_lon = dropoff_lon
        turn_lat = pickup_lat

        route_segments = pd.DataFrame(
            [
                {
                    "start_lon": pickup_lon,
                    "start_lat": pickup_lat,
                    "end_lon": turn_lon,
                    "end_lat": turn_lat,
                },
                {
                    "start_lon": turn_lon,
                    "start_lat": turn_lat,
                    "end_lon": dropoff_lon,
                    "end_lat": dropoff_lat,
                },
            ]
        )

    else:
        osrm_url = (
            "https://router.project-osrm.org/route/v1/driving/"
            f"{pickup_lon},{pickup_lat};"
            f"{dropoff_lon},{dropoff_lat}"
            "?overview=full&geometries=geojson"
        )

        osrm_response = requests.get(osrm_url, timeout=60)

        if osrm_response.status_code != 200:
            route_segments = pd.DataFrame(
                [
                    {
                        "start_lon": pickup_lon,
                        "start_lat": pickup_lat,
                        "end_lon": dropoff_lon,
                        "end_lat": dropoff_lat,
                    }
                ]
            )
            return route_segments, route_path, distance_km, duration_min

        osrm_data = safe_json(osrm_response, "OSRM")
        if not osrm_data or "routes" not in osrm_data or len(osrm_data["routes"]) == 0:
            route_segments = pd.DataFrame(
                [
                    {
                        "start_lon": pickup_lon,
                        "start_lat": pickup_lat,
                        "end_lon": dropoff_lon,
                        "end_lat": dropoff_lat,
                    }
                ]
            )
            return route_segments, route_path, distance_km, duration_min

        coordinates = osrm_data["routes"][0]["geometry"]["coordinates"]
        route_path = pd.DataFrame([{"path": coordinates}])
        distance_km = osrm_data["routes"][0]["distance"] / 1000
        duration_min = osrm_data["routes"][0]["duration"] / 60

    return route_segments, route_path, distance_km, duration_min


st.title("TaxiFareModel")
st.caption("Estimate a New York taxi fare from addresses and visualize the trip.")

with st.sidebar:
    st.header("Trip setup")

    st.button("Swap pickup ↔ dropoff", on_click=swap_addresses)

    with st.form("trip_form"):
        d = st.date_input("Pickup date", datetime.date(2019, 7, 6))
        t = st.time_input("Pickup time", datetime.time(8, 45))

        pickup_address = st.text_input(
            "Pickup address",
            key="pickup_address",
            placeholder="Ex: MoMA, New York, NY, USA",
        )

        dropoff_address = st.text_input(
            "Dropoff address",
            key="dropoff_address",
            placeholder="Ex: JFK Airport, Queens, NY, USA",
        )

        passenger_count = st.slider("Passenger count", 1, 8, 1)

        route_style = st.radio(
            "Route style",
            ["Straight line", "Manhattan grid", "Real route (OSRM)"],
        )

        submitted = st.form_submit_button("Estimate Fare")

fare_api_url = "https://taxifare-624760050665.europe-west1.run.app/predict"

if submitted:
    if not pickup_address or not dropoff_address:
        st.warning("Please enter both pickup and dropoff addresses.")
    else:
        try:
            pickup_query = f"{pickup_address}, New York, NY, USA"
            dropoff_query = f"{dropoff_address}, New York, NY, USA"

            pickup_latitude, pickup_longitude, pickup_label, pickup_error = geocode_address(pickup_query)
            dropoff_latitude, dropoff_longitude, dropoff_label, dropoff_error = geocode_address(dropoff_query)

            if pickup_error:
                st.error(f"Pickup geocoding error: {pickup_error}")
                st.stop()

            if dropoff_error:
                st.error(f"Dropoff geocoding error: {dropoff_error}")
                st.stop()

            if pickup_latitude is None or dropoff_latitude is None:
                st.error("Could not geocode one or both addresses.")
                st.stop()

            pickup_datetime = datetime.datetime.combine(d, t)

            fare_params = {
                "pickup_datetime": pickup_datetime.isoformat(),
                "pickup_longitude": pickup_longitude,
                "pickup_latitude": pickup_latitude,
                "dropoff_longitude": dropoff_longitude,
                "dropoff_latitude": dropoff_latitude,
                "passenger_count": passenger_count,
            }

            fare_response = requests.get(
                url=fare_api_url,
                params=fare_params,
                timeout=20,
            )

            if fare_response.status_code != 200:
                st.error("Fare API error.")
                st.write("Status code:", fare_response.status_code)
                st.code(fare_response.text[:500])
                st.stop()

            pred = safe_json(fare_response, "Fare API")
            if pred is None or "fare" not in pred:
                st.error("The API did not return valid JSON with a fare.")
                st.stop()

            fare_value = round(pred["fare"], 2)

            route_segments, route_path, distance_km, duration_min = build_route_layers(
                route_style,
                pickup_longitude,
                pickup_latitude,
                dropoff_longitude,
                dropoff_latitude,
            )

            st.session_state.history.insert(
                0,
                {
                    "pickup": pickup_label,
                    "dropoff": dropoff_label,
                    "fare": fare_value,
                    "route_style": route_style,
                    "passengers": passenger_count,
                },
            )
            st.session_state.history = st.session_state.history[:5]

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Estimated fare", f"${fare_value}")
            c2.metric("Passengers", passenger_count)
            c3.metric("Distance", f"{distance_km:.2f} km" if distance_km is not None else "N/A")
            c4.metric("Duration", f"{duration_min:.0f} min" if duration_min is not None else "N/A")

            st.success(f"Your ride's estimated cost is: ${fare_value}")

            tab1, tab2, tab3 = st.tabs(["Map", "Trip summary", "Technical details"])

            with tab1:
                map_col, info_col = st.columns([2, 1])

                with map_col:
                    points = pd.DataFrame(
                        [
                            {
                                "label": "Pickup",
                                "lat": pickup_latitude,
                                "lon": pickup_longitude,
                                "color": [0, 180, 0],
                            },
                            {
                                "label": "Dropoff",
                                "lat": dropoff_latitude,
                                "lon": dropoff_longitude,
                                "color": [220, 30, 30],
                            },
                        ]
                    )

                    center_lat = (pickup_latitude + dropoff_latitude) / 2
                    center_lon = (pickup_longitude + dropoff_longitude) / 2

                    view_state = pdk.ViewState(
                        latitude=center_lat,
                        longitude=center_lon,
                        zoom=11,
                        pitch=0,
                    )

                    layers = [
                        pdk.Layer(
                            "ScatterplotLayer",
                            data=points,
                            get_position="[lon, lat]",
                            get_fill_color="color",
                            get_radius=120,
                            pickable=True,
                        )
                    ]

                    if route_path is not None:
                        layers.append(
                            pdk.Layer(
                                "PathLayer",
                                data=route_path,
                                get_path="path",
                                get_color=[30, 144, 255],
                                width_scale=20,
                                width_min_pixels=4,
                                get_width=5,
                            )
                        )
                    elif route_segments is not None:
                        layers.append(
                            pdk.Layer(
                                "LineLayer",
                                data=route_segments,
                                get_source_position="[start_lon, start_lat]",
                                get_target_position="[end_lon, end_lat]",
                                get_color=[30, 144, 255],
                                get_width=5,
                            )
                        )

                    deck = pdk.Deck(
                        map_style="light",
                        initial_view_state=view_state,
                        layers=layers,
                        tooltip={"text": "{label}"},
                    )

                    st.pydeck_chart(deck, use_container_width=True)

                with info_col:
                    st.subheader("Addresses")
                    st.write("**Pickup**")
                    st.caption(pickup_label)
                    st.write("**Dropoff**")
                    st.caption(dropoff_label)

                    st.subheader("Route")
                    st.write(f"Style: {route_style}")
                    if distance_km is not None and duration_min is not None:
                        st.write(f"Distance: {distance_km:.2f} km")
                        st.write(f"Duration: {duration_min:.0f} min")

            with tab2:
                st.subheader("Trip summary")
                st.write(f"This trip for {passenger_count} passenger(s) is estimated at ${fare_value}.")
                st.write(f"Pickup: {pickup_label}")
                st.write(f"Dropoff: {dropoff_label}")
                st.write(f"Route style selected: {route_style}")

                if distance_km is not None and duration_min is not None:
                    st.info(
                        f"Approximate road distance: {distance_km:.2f} km · "
                        f"Estimated drive time: {duration_min:.0f} min"
                    )

                if st.session_state.history:
                    st.subheader("Recent trips")
                    st.dataframe(pd.DataFrame(st.session_state.history), use_container_width=True)

            with tab3:
                with st.expander("Coordinates", expanded=True):
                    st.json(
                        {
                            "pickup_latitude": pickup_latitude,
                            "pickup_longitude": pickup_longitude,
                            "dropoff_latitude": dropoff_latitude,
                            "dropoff_longitude": dropoff_longitude,
                        }
                    )

                with st.expander("Fare API response"):
                    st.json(pred)

                with st.expander("Fare API params"):
                    st.json(fare_params)

        except Exception as e:
            st.error("Uh oh... something went wrong.")
            st.write(str(e))
else:
    st.info("Fill in the trip details in the sidebar, then click Estimate Fare.")
