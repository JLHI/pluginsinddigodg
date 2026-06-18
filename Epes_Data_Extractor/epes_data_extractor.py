# -*- coding: utf-8 -*-
__author__ = 'JL HUMBERT'
__date__ = '2026-02-25'
__copyright__ = '(C) 2026 by JL HUMBERT'

import os
import traceback
import threading
import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

import shutil

from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingParameterVectorLayer,
    QgsProcessingParameterNumber,
    QgsProcessingParameterEnum,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterFile,
    QgsProcessingException,
    QgsProcessing,
    QgsProject,
    QgsGeometry,
    QgsCoordinateTransform,
    QgsCoordinateReferenceSystem,
    QgsRasterLayer,
    QgsExpressionContextUtils,
)

from .sources import DEFAULT_CONFIG
from .connectors import fetch_source, save_layer_as_gpkg, reproject_layer, clear_mnt_cache


def _source_sort_key(src):
    """Clé de tri : dossier cible puis nom alphabétique."""
    folder = src.get('target', {}).get('folder', '')
    return (folder, src.get('name', '').casefold())


def _sorted_sources(group_key):
    """Retourne les sources d'un groupe triées par dossier cible puis par nom."""
    return sorted(DEFAULT_CONFIG['groups'][group_key]['sources'], key=_source_sort_key)


def _write_log_files(output_folder, log_results, buffer_dist):
    """Écrit EpesDataExtractorLogs.log dans les dossiers vecteur et raster."""
    user_name = (
        QgsExpressionContextUtils.globalScope().variable('user_full_name')
        or os.environ.get('USERNAME', 'inconnu')
    )
    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
    header = [
        f'=== EpesDataExtractor — {now} ===',
        f'Utilisateur : {user_name}',
        f'Buffer : {buffer_dist / 1000:.1f} km',
        '',
    ]

    vector_lines = list(header) + ['Couches vecteur :']
    raster_lines = list(header) + ['Couches raster :']

    for src, save_path, err, feat_count, is_raster in sorted(
        log_results, key=lambda x: _source_sort_key(x[0])
    ):
        name = src.get('name', src.get('id', '?'))
        if err:
            entry = f'  ✗ {name} — ERREUR : {err}'
        elif not save_path:
            entry = f'  — {name} (ignoré)'
        elif is_raster:
            entry = f'  ✓ {name}'
        else:
            entry = f'  ✓ {name} : {feat_count} entité(s)'

        if is_raster:
            raster_lines.append(entry)
        else:
            vector_lines.append(entry)

    for folder_name, lines in (('4-DATA VECTEUR', vector_lines), ('3-DATA RASTER', raster_lines)):
        log_dir = os.path.join(output_folder, folder_name)
        os.makedirs(log_dir, exist_ok=True)
        log_path = os.path.join(log_dir, 'EpesDataExtractorLogs.log')
        mode = 'a' if os.path.exists(log_path) else 'w'
        with open(log_path, mode, encoding='utf-8') as f:
            f.write('\n'.join(lines) + '\n\n')


# ---------- Feedback thread-safe ----------

_LOG_SKIP = (
    'URL : ', 'CRS couche', 'CRS WFS', 'Service URL →',
    'Retry ', 'DATAtourisme page', 'Page ', 'Overpass query :',
    'IGN champs disponibles', 'Clés ',
)

class _ThreadFeedback:
    """Bufferise les logs d'un thread ; flush atomique en fin de tâche."""
    def __init__(self, base_feedback, name=''):
        self._base = base_feedback
        self.name = name
        self._buf = []   # liste de ('info'|'warn'|'error', msg)

    def pushInfo(self, msg):
        self._buf.append(('info', msg.strip()))

    def pushWarning(self, msg):
        self._buf.append(('warn', msg.strip()))

    def reportError(self, msg, fatalError=False):
        self._buf.append(('error', msg.strip()))

    def isCanceled(self):
        return self._base.isCanceled()

    def flush(self, lock, save_path=None, err=None, verbose=True):
        """Vide le buffer vers feedback de façon atomique.

        verbose=True  → logs détaillés (comportement actuel)
        verbose=False → une seule ligne : ✓ nom ou ✗ nom
        """
        with lock:
            if verbose:
                self._base.pushInfo(f'\n┌── {self.name}')
                for level, msg in self._buf:
                    if any(msg.startswith(p) for p in _LOG_SKIP):
                        continue
                    if level == 'info':
                        self._base.pushInfo(f'│  {msg}')
                    elif level == 'warn':
                        self._base.pushWarning(f'│  ⚠ {msg}')
                    else:
                        self._base.reportError(f'│  ✗ {msg}')
                if err:
                    self._base.reportError(f'└─ ✗ {err}', fatalError=False)
                elif save_path:
                    self._base.pushInfo(f'└─ ✓ {os.path.basename(save_path)}')
                else:
                    self._base.pushInfo('└─ (ignoré)')
            else:
                if err:
                    self._base.reportError(f'✗  {self.name} — {err}', fatalError=False)
                elif save_path:
                    self._base.pushInfo(f'✓  {self.name}')
                # ignoré → silencieux en mode simple


# ---------- Géométrie ----------

def make_buffer_lambert(geom, input_crs, distance_m):
    """Retourne le buffer en EPSG:2154 (mètres)."""
    lambert = QgsCoordinateReferenceSystem('EPSG:2154')
    from qgis.core import QgsGeometry as _QgsGeometry
    g = _QgsGeometry(geom)
    if input_crs.authid() != 'EPSG:2154':
        tr = QgsCoordinateTransform(input_crs, lambert, QgsProject.instance())
        g.transform(tr)
    return g.buffer(distance_m, 64)


def centroid_wgs84(geom_lambert):
    """Retourne le centroïde du buffer (lambert) en WGS84."""
    lambert = QgsCoordinateReferenceSystem('EPSG:2154')
    wgs84 = QgsCoordinateReferenceSystem('EPSG:4326')
    tr = QgsCoordinateTransform(lambert, wgs84, QgsProject.instance())
    return tr.transform(geom_lambert.centroid().asPoint())


# ---------- Algorithme ----------

class AutoDataPrepAlgorithm(QgsProcessingAlgorithm):

    INPUT_POLYGON = 'INPUT_POLYGON'
    BUFFER_DISTANCE = 'BUFFER_DISTANCE'
    GROUP_COMMUNS = 'GROUP_COMMUNS'
    LAYERS_COMMUNS = 'LAYERS_COMMUNS'
    GROUP_PAYSAGE = 'GROUP_PAYSAGE'
    LAYERS_PAYSAGE = 'LAYERS_PAYSAGE'
    GROUP_EIE = 'GROUP_EIE'
    LAYERS_EIE = 'LAYERS_EIE'
    GROUP_MNB = 'GROUP_MNB'
    LAYERS_MNB = 'LAYERS_MNB'
    OUTPUT_FOLDER = 'OUTPUT_FOLDER'
    VERBOSE_LOGS = 'VERBOSE_LOGS'
    WRITE_LOGS = 'WRITE_LOGS'

    def initAlgorithm(self, config=None):  # noqa: ARG002
        self.addParameter(
            QgsProcessingParameterVectorLayer(
                self.INPUT_POLYGON,
                'Couche de polygone (emprise)',
                [QgsProcessing.TypeVectorPolygon]
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.BUFFER_DISTANCE,
                'Distance de buffer (km)',
                type=QgsProcessingParameterNumber.Double,
                defaultValue=10.0,
                minValue=0.5
            )
        )

        # --- Communs ---
        self.addParameter(QgsProcessingParameterBoolean(self.GROUP_COMMUNS, 'Groupe : Communs', defaultValue=True))
        communs = [s['name'] for s in _sorted_sources('Communs')]
        self.addParameter(QgsProcessingParameterEnum(
            self.LAYERS_COMMUNS, '  Couches Communs à extraire',
            options=communs, allowMultiple=True, defaultValue=list(range(len(communs)))
        ))

        # --- Paysage ---
        self.addParameter(QgsProcessingParameterBoolean(self.GROUP_PAYSAGE, 'Groupe : Paysage', defaultValue=True))
        paysage = [s['name'] for s in _sorted_sources('Paysage')]
        self.addParameter(QgsProcessingParameterEnum(
            self.LAYERS_PAYSAGE, '  Couches Paysage à extraire',
            options=paysage, allowMultiple=True, defaultValue=list(range(len(paysage)))
        ))

        # --- EIE ---
        self.addParameter(QgsProcessingParameterBoolean(self.GROUP_EIE, 'Groupe : EIE', defaultValue=True))
        eie = [s['name'] for s in _sorted_sources('EIE')]
        self.addParameter(QgsProcessingParameterEnum(
            self.LAYERS_EIE, '  Couches EIE à extraire',
            options=eie, allowMultiple=True, defaultValue=list(range(len(eie)))
        ))

        # --- MNB ---
        self.addParameter(QgsProcessingParameterBoolean(self.GROUP_MNB, 'Groupe : MNB', defaultValue=True))
        mnb = [s['name'] for s in _sorted_sources('MNB')]
        self.addParameter(QgsProcessingParameterEnum(
            self.LAYERS_MNB, '  Couches MNB à extraire',
            options=mnb, allowMultiple=True, defaultValue=list(range(len(mnb)))
        ))

        # --- Dossier export ---
        project_path = QgsProject.instance().absoluteFilePath()
        default_folder = os.path.dirname(project_path) if project_path else ''
        self.addParameter(QgsProcessingParameterFile(
            self.OUTPUT_FOLDER, "Dossier d'export",
            behavior=QgsProcessingParameterFile.Folder,
            defaultValue=default_folder
        ))

        # --- Logs ---
        self.addParameter(QgsProcessingParameterBoolean(
            self.VERBOSE_LOGS, 'Logs détaillés', defaultValue=False
        ))
        self.addParameter(QgsProcessingParameterBoolean(
            self.WRITE_LOGS, 'Générer un fichier de logs (EpesDataExtractorLogs.log)', defaultValue=False
        ))

    # ------------------------------------------------------------------

    def processAlgorithm(self, parameters, context, feedback):
        input_layer = self.parameterAsVectorLayer(parameters, self.INPUT_POLYGON, context)
        buffer_dist = self.parameterAsDouble(parameters, self.BUFFER_DISTANCE, context)*1000.0
        output_folder = self.parameterAsFile(parameters, self.OUTPUT_FOLDER, context)
        verbose_logs = self.parameterAsBool(parameters, self.VERBOSE_LOGS, context)
        write_logs = self.parameterAsBool(parameters, self.WRITE_LOGS, context)

        clear_mnt_cache()  # purger tout cache résiduel d'un run précédent
        feats = list(input_layer.getFeatures())
        if not feats:
            raise QgsProcessingException("La couche d'emprise est vide")

        geom = (QgsGeometry.unaryUnion([f.geometry() for f in feats])
                if len(feats) > 1 else feats[0].geometry())

        buffer_geom = make_buffer_lambert(geom, input_layer.crs(), buffer_dist)
        buffer_bbox = buffer_geom.boundingBox()
        centroid_pt = centroid_wgs84(buffer_geom)
        dist_km = buffer_dist / 1000.0

        groups_config = [
            (self.GROUP_COMMUNS, self.LAYERS_COMMUNS, 'Communs'),
            (self.GROUP_PAYSAGE, self.LAYERS_PAYSAGE, 'Paysage'),
            (self.GROUP_EIE,     self.LAYERS_EIE,     'EIE'),
            (self.GROUP_MNB,     self.LAYERS_MNB,     'MNB'),
        ]

        # Collecter toutes les sources à traiter (tous groupes confondus)
        tasks = []
        for group_param, layers_param, group_key in groups_config:
            if not self.parameterAsBool(parameters, group_param, context):
                feedback.pushInfo(f'Groupe {group_key} : ignoré (décoché)')
                continue
            selected = self.parameterAsEnums(parameters, layers_param, context)
            if not selected:
                feedback.pushInfo(f'Groupe {group_key} : aucune couche sélectionnée')
                continue
            sources = _sorted_sources(group_key)
            feedback.pushInfo(f'Groupe {group_key} : {len(selected)} couche(s) planifiée(s)')
            for idx in selected:
                if idx < len(sources):
                    tasks.append((group_key, sources[idx]))

        if not tasks:
            return {}

        feedback.pushInfo(f'\n=== Lancement parallèle : {len(tasks)} source(s) ===')
        log_lock = threading.Lock()

        def _run(group_key, src):
            name = src.get('name', src['id'])
            fb = _ThreadFeedback(feedback, name)
            thread_temp = []
            feat_count = -1
            is_raster = False
            try:
                if fb.isCanceled():
                    return fb, None, None, feat_count, is_raster
                layer = fetch_source(src, buffer_bbox, dist_km, centroid_pt, fb, thread_temp, output_folder=output_folder)
                if layer is None or fb.isCanceled():
                    return fb, None, None, feat_count, is_raster
                nomenclature = src.get('nomenclature', src['id'])
                target_folder = src.get('target', {}).get('folder', '')
                if isinstance(layer, QgsRasterLayer):
                    is_raster = True
                    save_path = os.path.join(output_folder, target_folder, f'{nomenclature}.tif')
                    os.makedirs(os.path.dirname(save_path), exist_ok=True)
                    shutil.copy2(layer.dataProvider().dataSourceUri(), save_path)
                    if fb:
                        fb.pushInfo(f'    Raster sauvegardé : {os.path.basename(save_path)}')
                else:
                    layer = reproject_layer(layer)
                    feat_count = layer.featureCount()
                    save_path = os.path.join(output_folder, target_folder, f'{nomenclature}.gpkg')
                    save_layer_as_gpkg(layer, save_path, nomenclature, fb)
                return fb, save_path, None, feat_count, is_raster
            except Exception as e:
                return fb, None, str(e), feat_count, is_raster
            finally:
                for f in thread_temp:
                    try:
                        os.unlink(f)
                    except Exception:
                        pass

        # Phase 1 : toutes les sources sauf raster_slope (en parallèle)
        regular_tasks = [(g, s) for g, s in tasks if s.get('type') != 'raster_slope']
        slope_tasks   = [(g, s) for g, s in tasks if s.get('type') == 'raster_slope']

        log_results = []
        cancelled = False

        if regular_tasks:
            feedback.pushInfo(f'\n=== Phase 1 — {len(regular_tasks)} source(s) en parallèle ===')
            executor = ThreadPoolExecutor(max_workers=8)
            futures = {executor.submit(_run, g, s): (g, s) for g, s in regular_tasks}
            try:
                for future in as_completed(futures):
                    fb, save_path, err, feat_count, is_raster = future.result()
                    fb.flush(log_lock, save_path=save_path, err=err, verbose=verbose_logs)
                    if write_logs:
                        _, s = futures[future]
                        log_results.append((s, save_path, err, feat_count, is_raster))
                    if feedback.isCanceled():
                        feedback.pushInfo('\nAnnulation : arrêt des tâches en attente…')
                        for f in futures:
                            f.cancel()
                        cancelled = True
                        break
            finally:
                executor.shutdown(wait=False)

        # Phase 2 : couches de pente — lisent le MNT sauvegardé en phase 1
        if slope_tasks and not cancelled:
            feedback.pushInfo(f'\n=== Phase 2 — {len(slope_tasks)} couche(s) de pente ===')
            for g, s in slope_tasks:
                if feedback.isCanceled():
                    break
                fb, save_path, err, feat_count, is_raster = _run(g, s)
                fb.flush(log_lock, save_path=save_path, err=err, verbose=verbose_logs)
                if write_logs:
                    log_results.append((s, save_path, err, feat_count, is_raster))

        clear_mnt_cache()

        if write_logs and log_results:
            _write_log_files(output_folder, log_results, buffer_dist)

        return {}

    def name(self):
        return 'autodataprep'

    def groupId(self):
        return 'EPES'

    def group(self):
        return 'EPES'

    def displayName(self):
        return 'Extraction de données'

    def shortHelpString(self):
        return (
            'Récupère et exporte les données référentielles depuis PostGIS, WFS et API '
            'pour un périmètre tamponné autour d\'une emprise polygone.\n\n'
            'Cochez les groupes souhaités (Communs / Paysage / EIE) puis sélectionnez '
            'les couches individuelles dans chaque groupe.\n\n'
            'Les fichiers sont exportés en GeoPackage (.gpkg) dans le dossier choisi, '
            'en respectant l\'arborescence définie.\n\n'
            '─── Identifiants requis ───\n'
            'Certaines sources nécessitent des identifiants configurés dans les variables '
            'globales QGIS (Réglages → Options → Variables) :\n\n'
            '• atlasante_user / atlasante_password\n'
            '  → Accès Atlasanté (captages eau potable)\n'
            '  → Compte à demander sur https://www.atlasante.fr\n\n'
            '• data_tourisme\n'
            '  → Clé API DATAtourisme (POI touristiques et itinéraires)\n'
            '  → Clé à obtenir sur https://info.datatourisme.fr/utiliser-les-donnees\n\n'
            'Sans ces variables, la source concernée échouera avec un message explicite.\n'
            'Un avertissement s\'affiche également dans la barre de messages au démarrage '
            'du plugin si une variable est manquante.'
        )

    def createInstance(self):
        return AutoDataPrepAlgorithm()
