# -*- coding: utf-8 -*-
"""
Découpe des transects perpendiculaires par les limites de parcelles.

Supporte deux sources :
  1. Couche de parcelles locale (polygones ou lignes) chargée dans QGIS.
     Pas d'accès internet, fonctionne avec n'importe quelle couche de découpage.
  2. WFS cadastre IGN Géoplateforme (si aucune couche locale n'est fournie).

Cet outil peut être rejoué indépendamment sur des transects déjà générés
(cas où le clip a échoué lors de la génération, ou changement de source parcellaire).
"""

import math

from qgis.core import (
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingParameterVectorLayer,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterFeatureSink,
    QgsFeature,
    QgsGeometry,
    QgsPointXY,
    QgsWkbTypes,
    QgsFields,
    QgsField,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsProject,
    QgsRectangle,
    QgsFeatureRequest,
)
from qgis.PyQt.QtCore import QCoreApplication, QVariant

from .lidar_road_profile import _seg_ray_t, _fetch_parcel_crossings

_CRS_2154 = QgsCoordinateReferenceSystem('EPSG:2154')


# ── intersection locale ──────────────────────────────────────────────────────

def _crossings_from_layer(parcel_layer, p1x, p1y, ux, uy, seg_len,
                           xmin, ymin, xmax, ymax, transform_context=None):
    """
    Calcule les t ∈ [0, seg_len] où les contours d'une couche QGIS locale
    (polygones ou lignes) croisent le transect P1 + t·(ux,uy).

    Gère automatiquement le changement de SCR :
    - Le bbox (xmin…ymax) et les coordonnées P1/u sont en EPSG:2154.
    - Si la couche source est dans un autre SCR, on transforme le bbox pour
      le filtre spatial et on reprojette chaque géométrie en EPSG:2154 avant
      de calculer l'intersection.
    """
    layer_crs  = parcel_layer.sourceCrs()
    need_xform = (layer_crs != _CRS_2154)

    # Transformeurs (créés une seule fois, réutilisés sur toutes les entités)
    if need_xform:
        tc = transform_context or QgsProject.instance().transformContext()
        # Pour le filtre spatial : EPSG:2154 → SCR de la couche
        to_layer  = QgsCoordinateTransform(_CRS_2154, layer_crs, tc)
        # Pour l'intersection : SCR de la couche → EPSG:2154
        to_2154   = QgsCoordinateTransform(layer_crs, _CRS_2154, tc)

        # Transformer le bbox en SCR de la couche
        bbox_geom = QgsGeometry.fromRect(QgsRectangle(xmin, ymin, xmax, ymax))
        bbox_geom.transform(to_layer)
        filter_bbox = bbox_geom.boundingBox()
    else:
        to_2154     = None
        filter_bbox = QgsRectangle(xmin, ymin, xmax, ymax)

    request = QgsFeatureRequest().setFilterRect(filter_bbox)
    ts      = []

    for feat in parcel_layer.getFeatures(request):
        geom = feat.geometry()
        if geom is None or geom.isEmpty():
            continue

        # Reprojeter la géométrie en EPSG:2154 si nécessaire
        if to_2154 is not None:
            geom = QgsGeometry(geom)   # copie pour ne pas modifier l'original
            geom.transform(to_2154)

        gtype = QgsWkbTypes.geometryType(geom.wkbType())

        if gtype == QgsWkbTypes.PolygonGeometry:
            polys = geom.asMultiPolygon() if geom.isMultipart() else [geom.asPolygon()]
            for poly in polys:
                for ring in poly:
                    for j in range(len(ring) - 1):
                        t = _seg_ray_t(
                            p1x, p1y, ux, uy,
                            ring[j].x(), ring[j].y(),
                            ring[j + 1].x(), ring[j + 1].y(),
                        )
                        if t is not None and 0.0 <= t <= seg_len:
                            ts.append(t)

        elif gtype == QgsWkbTypes.LineGeometry:
            lines = geom.asMultiPolyline() if geom.isMultipart() else [geom.asPolyline()]
            for line in lines:
                for j in range(len(line) - 1):
                    t = _seg_ray_t(
                        p1x, p1y, ux, uy,
                        line[j].x(), line[j].y(),
                        line[j + 1].x(), line[j + 1].y(),
                    )
                    if t is not None and 0.0 <= t <= seg_len:
                        ts.append(t)

    return sorted(ts)


# ── algorithme ────────────────────────────────────────────────────────────────

class ClipTransectsByParcelsAlgorithm(QgsProcessingAlgorithm):

    TRANSECTS = 'TRANSECTS'
    PARCELS   = 'PARCELS'
    USE_WFS   = 'USE_WFS'
    OUTPUT    = 'OUTPUT'

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterVectorLayer(
            self.TRANSECTS,
            self.tr('Transects à clipper'),
            [QgsProcessing.TypeVectorLine],
        ))

        parcels_param = QgsProcessingParameterVectorLayer(
            self.PARCELS,
            self.tr(
                'Couche de parcelles locale (optionnel)\n'
                'Polygones ou lignes — remplace le WFS si fournie'
            ),
            [QgsProcessing.TypeVectorPolygon, QgsProcessing.TypeVectorLine],
            optional=True,
        )
        self.addParameter(parcels_param)

        self.addParameter(QgsProcessingParameterBoolean(
            self.USE_WFS,
            self.tr(
                'Utiliser le WFS cadastre IGN si aucune couche locale\n'
                '(connexion internet requise)'
            ),
            defaultValue=True,
        ))

        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUTPUT,
            self.tr('Transects clippés'),
        ))

    # ─────────────────────────────────────────────────────────────────────────

    def processAlgorithm(self, parameters, context, feedback):
        trans_layer  = self.parameterAsVectorLayer(parameters, self.TRANSECTS, context)
        parcel_layer = self.parameterAsVectorLayer(parameters, self.PARCELS,   context)
        use_wfs      = self.parameterAsBool(parameters,        self.USE_WFS,   context)

        crs_2154  = QgsCoordinateReferenceSystem('EPSG:2154')
        use_local = parcel_layer is not None

        if use_local:
            # ── Détection WFS QGIS (restrictToRequestBBOX) ──────────────────
            # Une couche WFS avec restrictToRequestBBOX='1' ne charge que les
            # entités visibles à l'écran. Elle ne peut pas servir de source
            # "locale" fiable : les transects hors vue cartographique ne
            # trouveront aucune parcelle. On bascule vers les requêtes HTTP.
            if parcel_layer.dataProvider().name() == 'WFS':
                feedback.pushWarning(
                    f'⚠ La couche "{parcel_layer.name()}" est une couche WFS QGIS '
                    f'(chargement dynamique restrictToRequestBBOX). '
                    f'Seules les entités visibles à l\'écran seraient disponibles, '
                    f'ce qui causerait des croisements manquants.\n'
                    f'→ Basculement automatique vers requêtes HTTP directes (WFS IGN).\n'
                    f'Conseil : pour utiliser une couche locale sans ce problème, '
                    f'téléchargez le cadastre en local sur data.gouv.fr '
                    f'(format GeoPackage ou Shapefile).'
                )
                use_local = False
                use_wfs   = True
            else:
                layer_crs  = parcel_layer.sourceCrs()
                need_xform = (layer_crs != crs_2154)
                feedback.pushInfo(
                    f'Source : couche locale "{parcel_layer.name()}" '
                    f'({parcel_layer.featureCount()} entités) — '
                    f'SCR : {layer_crs.authid()}'
                    + (' → reprojection automatique vers EPSG:2154'
                       if need_xform else ' ✓ déjà en EPSG:2154')
                )

        if not use_local:
            if use_wfs:
                feedback.pushInfo('Source : WFS cadastre IGN HTTP (Géoplateforme)')
            else:
                feedback.pushInfo(
                    'Aucune source de parcelles active — '
                    'les transects seront copiés tels quels avec parcel_found=0'
                )

        # ── construction des champs de sortie ────────────────────────────────
        # Reprendre tous les champs de la couche d'entrée sauf largeur_parcelle
        # et parcel_found (qu'on ajoute/écrase systématiquement en fin de liste).
        in_fields  = trans_layer.fields()
        _skip      = {'largeur_parcelle', 'parcel_found'}
        kept_idx   = [k for k in range(in_fields.count())
                      if in_fields.field(k).name() not in _skip]

        out_fields = QgsFields()
        for k in kept_idx:
            out_fields.append(in_fields.field(k))
        out_fields.append(QgsField('largeur_parcelle', QVariant.Double))
        out_fields.append(QgsField('parcel_found',     QVariant.Int))

        (sink, dest_id) = self.parameterAsSink(
            parameters, self.OUTPUT, context,
            out_fields, QgsWkbTypes.LineString, crs_2154,
        )

        # ── traitement par transect ───────────────────────────────────────────
        features   = list(trans_layer.getFeatures())
        total      = len(features)
        n_clipped  = 0
        n_fallback = 0

        for i, feat in enumerate(features):
            if feedback.isCanceled():
                break
            feedback.setProgress(int(i / total * 100))

            geom = feat.geometry()
            if geom is None or geom.isEmpty():
                continue

            line = geom.asPolyline()
            if len(line) < 2:
                continue

            p1, p2 = line[0], line[-1]
            dx  = p2.x() - p1.x()
            dy  = p2.y() - p1.y()
            seg = math.sqrt(dx * dx + dy * dy)
            if seg == 0:
                continue
            ux, uy = dx / seg, dy / seg

            buf  = max(5.0, seg * 0.10)
            xmin = min(p1.x(), p2.x()) - buf
            ymin = min(p1.y(), p2.y()) - buf
            xmax = max(p1.x(), p2.x()) + buf
            ymax = max(p1.y(), p2.y()) + buf

            # ── recherche des croisements ─────────────────────────────────────
            crossings = []
            if use_local:
                crossings = _crossings_from_layer(
                    parcel_layer, p1.x(), p1.y(), ux, uy, seg,
                    xmin, ymin, xmax, ymax,
                    transform_context=context.transformContext(),
                )
            elif use_wfs:
                crossings = _fetch_parcel_crossings(
                    p1.x(), p1.y(), ux, uy, seg,
                    xmin, ymin, xmax, ymax,
                    feedback=feedback,
                )

            # ── clip de la géométrie ──────────────────────────────────────────
            out_p1           = p1
            out_p2           = p2
            largeur_parcelle = float(-1.0)
            parcel_found     = int(0)

            if len(crossings) >= 2:
                # ✓ Les deux côtés sont délimités → clip fiable
                t_left  = crossings[0]
                t_right = crossings[-1]
                out_p1  = QgsPointXY(p1.x() + ux * t_left,  p1.y() + uy * t_left)
                out_p2  = QgsPointXY(p1.x() + ux * t_right, p1.y() + uy * t_right)
                largeur_parcelle = float(round(t_right - t_left, 3))
                parcel_found     = int(1)
                n_clipped       += 1
                feedback.pushInfo(
                    f'  Transect {feat.id()} ✓ {largeur_parcelle:.2f} m '
                    f'({len(crossings)} croisement(s))'
                )
            else:
                # 0 ou 1 croisement = clip impossible (1 seul côté ne suffit pas)
                # On conserve la géométrie brute et on indique le nombre de croisements
                # pour aider le diagnostic.
                n_fallback += 1
                if len(crossings) == 1:
                    feedback.pushInfo(
                        f'  Transect {feat.id()} ✗ 1 croisement à t={crossings[0]:.2f} m '
                        f'— 2e limite introuvable (zone non cadastrée ?)'
                    )
                else:
                    feedback.pushInfo(
                        f'  Transect {feat.id()} ✗ 0 croisement '
                        f'[{xmin:.0f},{ymin:.0f},{xmax:.0f},{ymax:.0f}]'
                    )

            # ── écriture ─────────────────────────────────────────────────────
            out_feat = QgsFeature(out_fields)
            out_feat.setGeometry(QgsGeometry.fromPolylineXY([out_p1, out_p2]))
            attrs = [feat.attribute(k) for k in kept_idx]
            attrs.append(largeur_parcelle)
            attrs.append(parcel_found)
            out_feat.setAttributes(attrs)
            sink.addFeature(out_feat)

        feedback.pushInfo(
            f'\nBilan : {n_clipped} ✓ clippé(s) (2+ croisements), '
            f'{n_fallback} ✗ non clippé(s) (0 ou 1 croisement)\n'
            f'Les transects non clippés conservent leur géométrie d\'origine '
            f'(parcel_found=0). Causes possibles :\n'
            f'  • Zone non cadastrée (domaine public routier sans parcelle)\n'
            f'  • Transect trop court pour atteindre les deux limites\n'
            f'  • Tuiles cadastrales non encore téléchargées dans la zone'
        )

        return {self.OUTPUT: dest_id}

    # ── metadata ──────────────────────────────────────────────────────────────

    def name(self):         return 'clip_transects_parcels'
    def displayName(self):  return self.tr('Découper transects par parcelles')
    def group(self):        return self.tr('LiDAR')
    def groupId(self):      return 'lidar'

    def shortHelpString(self):
        return self.tr(
            'Découpe des transects sur les limites de parcelles pour obtenir\n'
            'la largeur parcelle à parcelle réelle.\n\n'
            'Deux sources supportées :\n\n'
            '① Couche locale (polygones ou lignes)\n'
            '  Exemple : cadastre téléchargé, emprise routière, limite foncière…\n'
            '  Pas de connexion internet requise.\n'
            '  Compatible avec n\'importe quelle couche de découpage.\n\n'
            '② WFS cadastre IGN (Géoplateforme)\n'
            '  Utilisé si aucune couche locale n\'est fournie et "WFS IGN" = Oui.\n'
            '  Connexion internet requise.\n\n'
            'Champs ajoutés / mis à jour :\n'
            '  largeur_parcelle : largeur du transect clippé (m), −1 si non clippé\n'
            '  parcel_found     : 1 = clippé, 0 = géométrie d\'origine conservée\n\n'
            'Tous les autres attributs de la couche d\'entrée sont conservés.\n'
            'Cet outil peut être rejoué à tout moment sur des transects existants.'
        )

    def createInstance(self):
        return ClipTransectsByParcelsAlgorithm()

    def tr(self, s):
        return QCoreApplication.translate('ClipTransectsByParcelsAlgorithm', s)
