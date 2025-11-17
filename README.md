# PluginsInddigoDG — Outils de géotraitement QGIS

Ce dépôt contient un ensemble d'algorithmes et d'outils de géotraitement destinés à être utilisés comme plugin QGIS (traitements Processing). Les scripts fournis couvrent plusieurs fonctionnalités utiles pour le transport, l'analyse d'isochrones, la transformation de données GTFS, et des exports Excel.

**Fonctionnalités principales**
- **Isochrones**: génération d'isochrones à partir de services IGN (`isochrone_ign`).
- **Itinéraires**: calcul d'itinéraires routiers (`Itineraire_ign`).
- **GTFS → isochrone / routes**: outils d'extraction et de conversion à partir de données GTFS (`TcIsoFromGtfs`, `gtfs_stops_to_routes_ign`, `gtfs_isochrone`).
- **Flux INSEE / exports Excel**: extraction/formatage de données de flux et export Excel (`flux_insee`, `lib/xlsxwriter` adapté).
- **Arbre de rabattement**: algorithme spécialisé dans la création d'arbres de rabattement (`Arbre_de_rabattement`).
- **TEOM / chargement SQL**: scripts d'import/exports et requêtes SQL liés aux données locales (`teom`, `sql/`).

**Installation**
- Copier le dossier `pluginsinddigodg` dans le répertoire des plugins QGIS utilisateur. Sur Windows, le chemin habituel est : `%APPDATA%\QGIS\QGIS3\profiles\default\python\plugins\`.
- Redémarrer QGIS.
- Activer le plugin dans le gestionnaire d'extensions de QGIS (Plugins > Manage and Install Plugins).
- Les algorithmes apparaîtront alors dans la boîte à outils Processing sous le nom du plugin (ou dans le menu correspondant).

**Utilisation (générale)**
- Ouvrir la `Processing Toolbox` dans QGIS.
- Rechercher le nom du traitement (ex. `ItineraireParLaRoute`, `isochrone_ign`, etc.).
- Lancer l'algorithme, renseigner les paramètres (couches d'entrée, options d'export, rayon/temps pour isochrones, etc.).

**Paramètres courants**
- **Couche d'entrée**: vecteur (points/linéaires) selon l'algorithme.
- **Champ identifiant**: lorsque nécessaire pour joindre ou agréger.
- **Rayon / temps**: pour les isochrones ou buffers.
- **Fichier de sortie**: GeoPackage, Shapefile, ou autre format supporté par QGIS.

Consultez la docstring de chaque fichier d'algorithme (par ex. `Arbre_de_rabattement/Arbre_de_rabattement_algorithm.py`) pour connaître la liste exacte des paramètres et leurs descriptions.


**Dépendances**
- Le plugin s'appuie essentiellement sur l'environnement Python de QGIS (PyQGIS). Certains scripts utilisent des bibliothèques standard incluses dans QGIS.
- Le dossier `lib/xlsxwriter` inclut une copie de `XlsxWriter` adaptée à l'export Excel sans nécessiter d'installation supplémentaire.



**Auteurs et contact**
- Mainteneur: `JLHI`. Pour questions ou signalement de bugs, ouvrir une issue ou me contacter directement.


