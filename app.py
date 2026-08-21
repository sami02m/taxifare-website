import datetime
import pandas as pd
import pydeck as pdk
import requests
import streamlit as st

st.set_page_config(page_title="TaxiFareModel", page_icon="🚕", layout="centered")

st.title("TaxiFareModel front")

st.markdown(
    """
Predict the price of a taxi ride in New York from addresses and visualize the route.
"""
)

d = st.date_input("Pickup date", datetime.date(2019, 7, 6))
t = st.time_input("Pickup time", datetime.time(8, 45))

pickup_address = st.text_input(
    "Pickup address",
    placeholder="Ex: Times Square, New York, NY",
)

dropoff_address = st.text_input(
    "Dropoff address",
    placeholder="Ex: Central Park, New York, NY",
)

passenger_count = st.slider("Passenger count", 1, 8, 1)

route_style = st.radio(
    "Route style",
    ["Straight line", "Manhattan grid", "Real route (OSRM)"],
    horizontal=True,
)

fare_api_url = "https://taxifare-624760050665.europe-west1.run.app/predict"


def geocode_address(address):
    geocode_url = "https://nominatim.openstreetmap.org/search"
    headers = {
        "User-Agent": "taxifare-streamlit-app"
    }
    params = {
        "q": address,
        "format": "jsonv2",
        "limit": 1,
    }

    response = requests.get(geocode_url, params=params, headers=headers, timeout=20)
    data = response.json()

    if response.status_code == 200 and len(data) > 0:
        lat = float(data[0]["lat"])
        lon = float(data[0]["lon"])
        display_name = data[0]["display_name"]
        return lat, lon, display_name

    return None, None, None


if st.button("Estimate Fare"):
    if not pickup_address or not dropoff_address:
        st.warning("Please enter both pickup and dropoff addresses.")
    else:
        try:
            pickup_latitude, pickup_longitude, pickup_label = geocode_address(pickup_address)
            dropoff_latitude, dropoff_longitude, dropoff_label = geocode_address(dropoff_address)

            if pickup_latitude is None or dropoff_latitude is None:
                st.error("Could not geocode one or both addresses.")
                st.stop()

            st.write("Pickup found:", pickup_label)
            st.write("Dropoff found:", dropoff_label)

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
            pred = fare_response.json()

            if fare_response.status_code == 200 and "fare" in pred:
                st.success(f"Your ride's estimated cost is: ${round(pred['fare'], 2)}")
            else:
                st.error("The API did not return a valid fare.")
                st.json(pred)
                st.stop()

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

            route_segments = None
            route_path = None

            if route_style == "Straight line":
                route_segments = pd.DataFrame(
                    [
                        {
                            "start_lon": pickup_longitude,
                            "start_lat": pickup_latitude,
                            "end_lon": dropoff_longitude,
                            "end_lat": dropoff_latitude,
                        }
                    ]
                )

            elif route_style == "Manhattan grid":
                turn_lon = dropoff_longitude
                turn_lat = pickup_latitude

                route_segments = pd.DataFrame(
                    [
                        {
                            "start_lon": pickup_longitude,
                            "start_lat": pickup_latitude,
                            "end_lon": turn_lon,
                            "end_lat": turn_lat,
                        },
                        {
                            "start_lon": turn_lon,
                            "start_lat": turn_lat,
                            "end_lon": dropoff_longitude,
                            "end_lat": dropoff_latitude,
                        },
                    ]
                )

            else:
                osrm_url = (
                    "https://router.project-osrm.org/route/v1/driving/"
                    f"{pickup_longitude},{pickup_latitude};"
                    f"{dropoff_longitude},{dropoff_latitude}"
                    "?overview=full&geometries=geojson"
                )

                osrm_response = requests.get(osrm_url, timeout=20)
                osrm_data = osrm_response.json()

                if (
                    osrm_response.status_code == 200
                    and "routes" in osrm_data
                    and len(osrm_data["routes"]) > 0
                ):
                    coordinates = osrm_data["routes"][0]["geometry"]["coordinates"]
                    route_path = pd.DataFrame([{"path": coordinates}])

                    distance_km = osrm_data["routes"][0]["distance"] / 1000
                    duration_min = osrm_data["routes"][0]["duration"] / 60

                    st.info(
                        f"Approximate road distance: {distance_km:.2f} km · "
                        f"Estimated drive time: {duration_min:.0f} min"
                    )
                else:
                    st.warning("Could not retrieve real route. Falling back to straight line.")
                    route_segments = pd.DataFrame(
                        [
                            {
                                "start_lon": pickup_longitude,
                                "start_lat": pickup_latitude,
                                "end_lon": dropoff_longitude,
                                "end_lat": dropoff_latitude,
                            }
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

            st.subheader("Trip map")
            st.pydeck_chart(deck, use_container_width=True)

        except Exception as e:
            st.error("Uh oh... something went wrong.")
            st.write(str(e))
