import datetime
import json

import geopandas
import pandas as pd
from .load import load_prepared_data
from . import prepare, travel
from shapely.geometry import Point
import math

def compute_isochrone(gtfs_folder, lat, lon, start_datetime, max_duration_seconds):
    data = load_prepared_data(gtfs_folder)
    print(data)

    return compute_isochrone_with_data(
        data, lat, lon, start_datetime, max_duration_seconds
    )


def compute_isochrone_with_data(data, lat, lon, start_datetime, max_duration_seconds, use_bus=True, use_tram=True):

    end_datetime = start_datetime + datetime.timedelta(seconds=max_duration_seconds)
    data = prepare.prepare_data_for_query(
        data, start_datetime, end_datetime, use_bus, use_tram
    )
    points = travel.compute_arrival_points(data, lat, lon, start_datetime, end_datetime)
    distances = walk_from_points(points, end_datetime)
    geojson = build_isochrone_from_points(distances)

    return geojson


def walk_from_points(points, end_datetime):
    points["duration_seconds"] = (end_datetime - points["arrival_datetime"]).dt.seconds
    points["walking_distance_m"] = (
        points["duration_seconds"] * prepare.WALKING_SPEED_M_S
    )
    distances = points.loc[:, ["lat", "lon", "walking_distance_m"]]
    return distances


def build_isochrone_from_points(distances):
    points = geopandas.GeoDataFrame(
        distances, geometry=geopandas.points_from_xy(distances["lon"], distances["lat"])
    )
    mapping_CRS = "EPSG:2154"
    lonlat_CRS = "EPSG:4326"
    # initial coords: lon, lat
    points = points.set_crs(lonlat_CRS)
    # project to a projection in meters
    # WARNING: the choice of CRS is very important here !
    gdf = points.to_crs(mapping_CRS)
    # expand the points and collapse to a single shape
    print(f'gdf en metre : {gdf["walking_distance_m"]}')
    gdf = gdf.buffer(gdf["walking_distance_m"])
    shape = gdf.unary_union

    # create a geojson from the shame, keeping the same crs as before
    shape = geopandas.GeoSeries(shape, crs=mapping_CRS)
    # convert back to lon, lat
    shape = shape.to_crs(lonlat_CRS)

    # TEMP: show points of stops (and origin)
    # shape = shape.append(points.geometry)

    # convert back to lon, lat to create the geojson
    geojson = json.loads(shape.to_json())
    return geojson


def haversine(lat1, lon1, lat2, lon2):
    """
    Calcule la distance entre deux points géographiques en utilisant la formule de Haversine.
    """
    R = 6371000  # Rayon de la Terre en mètres

    # Conversion des degrés en radians
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    # Calcul de la distance
    a = math.sin(delta_phi / 2) ** 2 + \
        math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return R * c  # Résultat en mètres

def filter_accessible_stops(lat, lon, stops, max_distance_m):
    """
    Filtre les arrêts accessibles à une distance donnée à partir d'une position (lat, lon).
    Utilise la formule de Haversine pour calculer les distances.
    """
    stops["distance"] = stops.apply(
        lambda row: haversine(lat, lon, row["stop_lat"], row["stop_lon"]), axis=1
    )
    return stops[stops["distance"] <= max_distance_m]

def compute_isochrone_arrival(gtfs_folder, lat, lon, arrival_time, max_duration_seconds):
    """
    Calcule les isochrones pour une heure d'arrivée souhaitée à partir d'un point (lat, lon).
    """
    # Charger les données GTFS
     # Charger les données GTFS
    data = load_prepared_data(gtfs_folder)
    stops = data.stops
    stop_times = data.stoptimes
    trips_dates = data.trips_dates

    # Étape 1 : Identifier les arrêts accessibles par marche
    max_distance_m = max_duration_seconds * 1.4  # Marche rapide ~1.4 m/s
    accessible_stops = filter_accessible_stops(lat, lon, stops, max_distance_m)

    if accessible_stops.empty:
        print("Aucun arrêt accessible trouvé.")
        return {"type": "FeatureCollection", "features": []}
    
    print("Accessible stops :", accessible_stops.head())

    # Étape 2 : Identifier les voyages actifs
    valid_trips = stop_times[stop_times["stop_id"].isin(accessible_stops["stop_id"])]
    print("Nombre de voyages après filtrage des stops accessibles :", len(valid_trips))

    # Vérification de la jointure
    valid_trips = valid_trips.merge(trips_dates, on="trip_id", how="inner")
    print("Nombre de voyages après jointure avec trips_dates :", len(valid_trips))

    # Débogage des dates
    print("Avant conversion, format de trips_dates['date'] :", trips_dates["date"].dtype)
    print("Exemple de données dans trips_dates['date'] :", trips_dates["date"].head())

    # Conversion explicite des dates
    valid_trips["date"] = pd.to_datetime(valid_trips["date"], errors="coerce").dt.date
    print("Après conversion, format de valid_trips['date'] :", valid_trips["date"].dtype)
    print("Exemple de dates après conversion :", valid_trips["date"].head())

    # Vérification de l'arrival_time
    print("Arrival date (cible) :", arrival_time.date())

    # Vérifier si la date cible est présente
    if arrival_time.date() not in valid_trips["date"].unique():
        print(f"La date {arrival_time.date()} n'est pas présente dans les données valid_trips.")
        print("Dates disponibles dans valid_trips :", valid_trips["date"].unique())
        return {"type": "FeatureCollection", "features": []}

    # Filtrage par date
    valid_trips = valid_trips[valid_trips["date"] == arrival_time.date()]
    print("Nombre de voyages après filtrage par date :", len(valid_trips))

    if valid_trips.empty:
        print("Aucun voyage actif trouvé pour la date spécifiée.")
        return {"type": "FeatureCollection", "features": []}

    # Fusionner avec les coordonnées des arrêts
    valid_trips = valid_trips.merge(
        stops[["stop_id", "stop_lat", "stop_lon"]], on="stop_id", how="left"
    )

    # Vérifier la présence des colonnes nécessaires
    if "stop_lat" not in valid_trips or "stop_lon" not in valid_trips:
        raise ValueError("Les colonnes nécessaires `stop_lat` et `stop_lon` sont manquantes dans valid_trips.")
    
    # Étape 3 : Calcul des arrêts atteignables
    reachable_stops = compute_reachable_stops(valid_trips, arrival_time, max_duration_seconds)

    if not reachable_stops:
        print("Aucun arrêt atteignable trouvé.")
        return {"type": "FeatureCollection", "features": []}

    # Convertir en DataFrame
    reachable_stops_df = pd.DataFrame(reachable_stops)

    # Étape 4 : Construction des isochrones
    if "stop_lon" in reachable_stops_df.columns and "stop_lat" in reachable_stops_df.columns:
        reachable_stops_df.rename(columns={"stop_lon": "lon", "stop_lat": "lat"}, inplace=True)
    else:
        raise ValueError("Les colonnes `stop_lat` et `stop_lon` sont manquantes dans reachable_stops_df.")

    # Préparer les distances pour l'isochrone
    # Calcul de la durée et de la distance de marche
    reachable_stops_df["duration_seconds"] = (
        arrival_time - reachable_stops_df["arrival_datetime"]
    ).dt.total_seconds()

    # Vérification des valeurs de durée
    print("Durées calculées :", reachable_stops_df["duration_seconds"].head())

    # Ajouter la colonne `walking_distance_m`
    reachable_stops_df["walking_distance_m"] = reachable_stops_df["duration_seconds"] * 1.4

    # Vérification après ajout
    print("Colonnes disponibles après calcul :", reachable_stops_df.columns)
    print(reachable_stops_df[["lon", "lat", "walking_distance_m"]].head())

    # Étape finale pour les distances
    distances = reachable_stops_df[["lon", "lat", "walking_distance_m"]]
    # Debugging
    print("Colonnes utilisées pour construire l'isochrone:", distances.columns)
    print(distances.head())

    # Appeler la fonction pour construire l'isochrone
    isochrone_geojson = build_isochrone_from_points(distances)

    print("Isochrone GeoJSON généré.")
    return isochrone_geojson



def compute_reachable_stops(stop_times, arrival_time, max_duration_seconds):
    """
    Calcul des arrêts atteignables dans une fenêtre temporelle.
    """
        # Calculer les limites de temps
    latest_departure_time = arrival_time - datetime.timedelta(seconds=max_duration_seconds)

    # Ajouter la colonne `arrival_datetime`
    base_datetime = datetime.datetime.combine(arrival_time.date(), datetime.time(0, 0))
    print(f"Base datetime : {base_datetime}")
    print(f"Latest departure time : {latest_departure_time}")

    # Convertir arrival_time en timedelta si nécessaire
    if not pd.api.types.is_timedelta64_dtype(stop_times["arrival_time"]):
        stop_times["arrival_time"] = pd.to_timedelta(stop_times["arrival_time"].astype(str))

    stop_times["arrival_datetime"] = base_datetime + stop_times["arrival_time"]
    print(f"Données après ajout de 'arrival_datetime' :\n{stop_times[['stop_id', 'arrival_datetime']].head()}")

    # Filtrer les arrêts atteignables
    reachable_stops_df = stop_times[
        (stop_times["arrival_datetime"] <= arrival_time) &
        (stop_times["arrival_datetime"] >= latest_departure_time)
    ]

    if reachable_stops_df.empty:
        print("Aucun arrêt atteignable trouvé.")
        return []

    # Construire une liste de dictionnaires pour les arrêts atteignables
    reachable_stops = reachable_stops_df[["stop_id", "arrival_datetime", "stop_lat", "stop_lon"]].to_dict(orient="records")
    print(f"Arrêts atteignables : {reachable_stops}")
    return reachable_stops



# def compute_isochrone_arrival(gtfs_folder, lat, lon, arrival_time, max_duration_seconds):
#     """
#     Calcule les isochrones pour une heure d'arrivée souhaitée à partir d'un point (lat, lon).
#     """

#     # Charger les données GTFS
#     data = load_prepared_data(gtfs_folder)
#     stops = data.stops
#     stop_times = data.stoptimes
#     trips_dates = data.trips_dates

#     # Étape 1 : Identifier les arrêts accessibles à pied
#     nearby_stops = stops.loc[
#         (stops["stop_lat"].between(lat - 0.015, lat + 0.015)) & 
#         (stops["stop_lon"].between(lon - 0.015, lon + 0.015))
#     ]

#     if nearby_stops.empty:
#         print("Aucun arrêt proche trouvé.")
#         return {"type": "FeatureCollection", "features": []}

#     # Étape 2 : Trouver les voyages actifs qui permettent de rejoindre ces arrêts à l'heure souhaitée
#     valid_trips = stop_times[stop_times["stop_id"].isin(nearby_stops["stop_id"])]
#     valid_trips = valid_trips.merge(trips_dates, on="trip_id")
#     valid_trips["date"] = valid_trips["date"].dt.date  # Conversion explicite pour correspondance correcte
#     valid_trips = valid_trips[valid_trips["date"] == arrival_time.date()]

#     if valid_trips.empty:
#         print("Aucun voyage actif trouvé pour la date spécifiée.")
#         return {"type": "FeatureCollection", "features": []}

#     # Étape 3 : Initialiser les arrêts atteignables et définir le temps maximal de départ
#     reachable_stops = []
#     latest_departure_time = arrival_time - datetime.timedelta(seconds=max_duration_seconds)

#     # Parcourir chaque voyage actif pour remonter dans le réseau
#     for trip_id in valid_trips["trip_id"].unique():
#         trip_stops = stop_times[stop_times["trip_id"] == trip_id].copy()

#         # Ajouter la colonne datetime d'arrivée aux arrêts
#         base_datetime = datetime.datetime.combine(arrival_time.date(), datetime.datetime.min.time())
#         trip_stops["arrival_datetime"] = base_datetime + trip_stops["arrival_time"]

#         # Filtrer les arrêts atteignables dans la plage de temps autorisée
#         trip_stops = trip_stops[
#             (trip_stops["arrival_datetime"] <= arrival_time) &
#             (trip_stops["arrival_datetime"] >= latest_departure_time)
#         ].sort_values(by="arrival_datetime", ascending=False)

#         # Remonter dans le réseau pour chaque arrêt
#         for _, stop in trip_stops.iterrows():
#             stop_id = stop["stop_id"]
#             stop_arrival_time = stop["arrival_datetime"]

#             # Calculer le temps total de trajet (transport + marche)
#             time_in_transit = (arrival_time - stop_arrival_time).total_seconds()

#             # Si le temps est négatif ou dépasse la durée maximale, ignorer cet arrêt
#             if time_in_transit > max_duration_seconds or time_in_transit < 0:
#                 continue

#             # Ajouter les détails de l'arrêt au résultat
#             walking_distance_m = time_in_transit * prepare.WALKING_SPEED_M_S
#             reachable_stops.append({
#                 "stop_id": stop_id,
#                 "arrival_datetime": stop_arrival_time,
#                 "lat": stops.loc[stops["stop_id"] == stop_id, "stop_lat"].values[0],
#                 "lon": stops.loc[stops["stop_id"] == stop_id, "stop_lon"].values[0],
#                 "walking_distance_m": walking_distance_m,
#                 "total_duration_seconds": time_in_transit
#             })

#     if not reachable_stops:
#         print("Aucun arrêt atteignable trouvé.")
#         return {"type": "FeatureCollection", "features": []}

#     # Étape 4 : Construire le DataFrame des arrêts atteignables
#     reachable_stops_df = pd.DataFrame(reachable_stops)
#     print("Arrêts atteignables :")
#     print(reachable_stops_df)

#     # Étape 5 : Calculer les distances et classes de temps
#     reachable_stops_df["time_class"] = (reachable_stops_df["total_duration_seconds"] // 60).astype(int)  # Classes en minutes

#     # Étape 6 : Construire l'isochrone
#     distances = reachable_stops_df[["lat", "lon", "walking_distance_m"]]
#     isochrone_geojson = build_isochrone_from_points(distances)

#     print("Isochrone GeoJSON généré.")
#     return isochrone_geojson

