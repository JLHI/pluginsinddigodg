# -*- coding: utf-8 -*-
"""
Classifier les points LiDAR de transects en segments fonctionnels.

Sorties (toutes optionnelles — laisser vide = désactivée) :
   Points classifiés        — copie avec champ « segment »
   Polygones de segments    — un polygone par classe par transect
   Synthèse par ligne       — une MultiLineString par id_ligne + largeurs moyennes
   Profil de largeur        — un point par transect pour grapher l'évolution
"""

import math

from qgis.core import (
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingParameterVectorLayer,
    QgsProcessingParameterNumber,
    QgsProcessingParameterFeatureSink,
    QgsFeature,
    QgsGeometry,
    QgsPoint,
    QgsPointXY,
    QgsMultiLineString,
    QgsLineString,
    QgsWkbTypes,
    QgsFields,
    QgsField,
    QgsCoordinateReferenceSystem,
)
from qgis.PyQt.QtCore import QCoreApplication, QVariant

from .lidar_road_profile import _strip_polygon

LABELS = ('chaussee', 'caniveau', 'trottoir', 'muret', 'vegetation')


# ── Segmentation helpers ───────────────────────────────────────────────────────

def _z_ref(pts):
    """5e percentile des altitudes des points sol (cls=2 ou dernier retour)."""
    import numpy as np
    sol = [p['z'] for p in pts
           if p['classif'] == 2 or (p['nret'] > 0 and p['ret'] == p['nret'])]
    return float(np.percentile(sol if sol else [p['z'] for p in pts], 5))


def _label(z, classif, zref, tc, tt, tm):
    if classif in (5, 6):
        return 'vegetation'
    dz = z - zref
    if dz < tc:  return 'chaussee'
    if dz < tt:  return 'caniveau'
    if dz < tm:  return 'trottoir'
    return 'muret'


def _build_segments(labeled_pts, bin_size):
    """
    labeled_pts : list of (d, z, label)
    Retourne list of {label, d_start, d_end, width, z_mean}.
    """
    if not labeled_pts:
        return []

    s = sorted(labeled_pts, key=lambda x: x[0])
    d0, d1 = s[0][0], s[-1][0]
    if d1 - d0 < bin_size:
        return []

    nb = max(2, int(math.ceil((d1 - d0) / bin_size)) + 1)
    bins = [[] for _ in range(nb)]
    for d, z, lbl in s:
        bi = min(nb - 1, int((d - d0) / bin_size))
        bins[bi].append((z, lbl))

    # Dominant label + z moyen par bin non vide
    seq = []
    for i, bpts in enumerate(bins):
        if not bpts:
            continue
        cnt = {}
        for _, l in bpts:
            cnt[l] = cnt.get(l, 0) + 1
        lbl = max(cnt, key=cnt.get)
        zm = sum(z for z, _ in bpts) / len(bpts)
        seq.append((i, lbl, zm))

    if not seq:
        return []

    # Fusion des bins consécutifs de même label
    segs = []
    run_start, run_lbl, run_zs = seq[0][0], seq[0][1], [seq[0][2]]

    def _flush(end_bi):
        segs.append({
            'label':   run_lbl,
            'd_start': d0 + run_start * bin_size,
            'd_end':   d0 + (end_bi + 1) * bin_size,
            'width':   (end_bi - run_start + 1) * bin_size,
            'z_mean':  sum(run_zs) / len(run_zs),
        })

    for k in range(1, len(seq)):
        bi, lbl, zm = seq[k]
        if lbl == run_lbl:
            run_zs.append(zm)
        else:
            _flush(seq[k - 1][0])
            run_start, run_lbl, run_zs = bi, lbl, [zm]
    _flush(seq[-1][0])

    return segs


def _widths_from_segs(segs):
    w = {lbl: 0.0 for lbl in LABELS}
    for seg in segs:
        if seg['label'] in w:
            w[seg['label']] += seg['width']
    return w


# ── Algorithme QGIS ───────────────────────────────────────────────────────────

class LidarClassifyTransectsAlgorithm(QgsProcessingAlgorithm):

    POINTS       = 'POINTS'
    TRANSECTS    = 'TRANSECTS'
    BIN_SIZE     = 'BIN_SIZE'
    THRESH_CANI  = 'THRESH_CANI'
    THRESH_TROTT = 'THRESH_TROTT'
    THRESH_MURET = 'THRESH_MURET'

    OUT_POINTS   = 'OUT_POINTS'
    OUT_POLYGONS = 'OUT_POLYGONS'
    OUT_LINES    = 'OUT_LINES'
    OUT_PROFILE  = 'OUT_PROFILE'

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterVectorLayer(
            self.POINTS, self.tr('Points LiDAR (id_transect, d_along, z, classification)'),
            [QgsProcessing.TypeVectorPoint]))
        self.addParameter(QgsProcessingParameterVectorLayer(
            self.TRANSECTS, self.tr('Transects perpendiculaires (id_transect, id_ligne, distance)'),
            [QgsProcessing.TypeVectorLine]))

        self.addParameter(QgsProcessingParameterNumber(
            self.BIN_SIZE, self.tr('Résolution de segmentation (m)'),
            QgsProcessingParameterNumber.Double,
            defaultValue=0.25, minValue=0.05, maxValue=1.0))
        self.addParameter(QgsProcessingParameterNumber(
            self.THRESH_CANI,
            self.tr('Seuil chaussée → caniveau (m au-dessus du plancher)'),
            QgsProcessingParameterNumber.Double,
            defaultValue=0.50, minValue=0.05, maxValue=1.0))
        self.addParameter(QgsProcessingParameterNumber(
            self.THRESH_TROTT,
            self.tr('Seuil caniveau → trottoir (m)'),
            QgsProcessingParameterNumber.Double,
            defaultValue=1.20, minValue=0.10, maxValue=2.0))
        self.addParameter(QgsProcessingParameterNumber(
            self.THRESH_MURET,
            self.tr('Seuil trottoir → muret/obstacle (m)'),
            QgsProcessingParameterNumber.Double,
            defaultValue=2.00, minValue=0.20, maxValue=5.0))

        # Sorties optionnelles — laisser vide = désactivée
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUT_POINTS,
            self.tr('Points classifiés'),
            optional=True, createByDefault=False))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUT_POLYGONS,
            self.tr('Polygones de segments (transects classifiés)'),
            optional=True, createByDefault=True))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUT_LINES,
            self.tr('Synthèse par ligne (MultiLineString + largeurs)'),
            optional=True, createByDefault=True))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUT_PROFILE,
            self.tr('Profil de largeur (un point par transect)'),
            optional=True, createByDefault=False))

    # ── traitement ─────────────────────────────────────────────────────────────

    def processAlgorithm(self, parameters, context, feedback):

        pts_layer   = self.parameterAsVectorLayer(parameters, self.POINTS,    context)
        trans_layer = self.parameterAsVectorLayer(parameters, self.TRANSECTS, context)
        bin_size    = self.parameterAsDouble(parameters, self.BIN_SIZE,    context)
        tc          = self.parameterAsDouble(parameters, self.THRESH_CANI,  context)
        tt          = self.parameterAsDouble(parameters, self.THRESH_TROTT, context)
        tm          = self.parameterAsDouble(parameters, self.THRESH_MURET, context)

        crs_2154 = QgsCoordinateReferenceSystem('EPSG:2154')

        # ── index transects ───────────────────────────────────────────────────
        trans_field_names = [trans_layer.fields().field(k).name()
                             for k in range(trans_layer.fields().count())]
        has_id_ligne = 'id_ligne' in trans_field_names
        has_distance = 'distance' in trans_field_names

        trans_info = {}
        for feat in trans_layer.getFeatures():
            line = feat.geometry().asPolyline()
            if len(line) < 2:
                continue
            p1, p2 = line[0], line[-1]
            dx, dy = p2.x() - p1.x(), p2.y() - p1.y()
            seg_len = math.sqrt(dx * dx + dy * dy)
            ux = dx / seg_len if seg_len > 0 else 0.0
            uy = dy / seg_len if seg_len > 0 else 0.0
            trans_info[feat.id()] = {
                'geom':     feat.geometry(),
                'p1x':      p1.x(),
                'p1y':      p1.y(),
                'ux':       ux,
                'uy':       uy,
                'id_ligne': int(feat['id_ligne']) if has_id_ligne else feat.id(),
                'distance': float(feat['distance']) if has_distance else 0.0,
            }

        # ── regroupement points par transect ──────────────────────────────────
        pts_by_tid = {}
        for feat in pts_layer.getFeatures():
            tid = int(feat['id_transect'])
            pts_by_tid.setdefault(tid, []).append({
                'fid':    feat.id(),
                'd':      float(feat['d_along']),
                'z':      float(feat['z']),
                'classif': int(feat['classification']),
                'ret':    int(feat['return_num']),
                'nret':   int(feat['num_returns']),
                'geom':   feat.geometry(),
            })

        # ── sinks ─────────────────────────────────────────────────────────────

        # Points
        pts_out_fields = QgsFields()
        for i in range(pts_layer.fields().count()):
            pts_out_fields.append(pts_layer.fields().field(i))
        pts_out_fields.append(QgsField('segment', QVariant.String))
        sink_pts, dest_pts = self.parameterAsSink(
            parameters, self.OUT_POINTS, context,
            pts_out_fields, QgsWkbTypes.PointZ, crs_2154)

        # Polygones
        poly_fields = QgsFields()
        for nm, vt in [
            ('id_transect', QVariant.Int),
            ('id_ligne',    QVariant.Int),
            ('distance',    QVariant.Double),
            ('segment',     QVariant.String),
            ('d_debut',     QVariant.Double),
            ('d_fin',       QVariant.Double),
            ('largeur',     QVariant.Double),
            ('z_moy',       QVariant.Double),
        ]:
            poly_fields.append(QgsField(nm, vt))
        sink_poly, dest_poly = self.parameterAsSink(
            parameters, self.OUT_POLYGONS, context,
            poly_fields, QgsWkbTypes.Polygon, crs_2154)

        # Synthèse par ligne
        line_fields = QgsFields()
        line_fields.append(QgsField('id_ligne',     QVariant.Int))
        line_fields.append(QgsField('nb_transects', QVariant.Int))
        for lbl in LABELS:
            line_fields.append(QgsField(f'larg_{lbl}', QVariant.Double))
        sink_lines, dest_lines = self.parameterAsSink(
            parameters, self.OUT_LINES, context,
            line_fields, QgsWkbTypes.MultiLineString, crs_2154)

        # Profil
        prof_fields = QgsFields()
        for nm, vt in [
            ('id_transect', QVariant.Int),
            ('id_ligne',    QVariant.Int),
            ('distance',    QVariant.Double),
        ]:
            prof_fields.append(QgsField(nm, vt))
        for lbl in LABELS:
            prof_fields.append(QgsField(f'larg_{lbl}', QVariant.Double))
        sink_prof, dest_prof = self.parameterAsSink(
            parameters, self.OUT_PROFILE, context,
            prof_fields, QgsWkbTypes.Point, crs_2154)

        # ── traitement par transect ───────────────────────────────────────────
        fid_to_label = {}   # pour Points
        by_ligne = {}       # pour Synthèse

        total = len(pts_by_tid)
        for step, (tid, raw_pts) in enumerate(sorted(pts_by_tid.items())):
            if feedback.isCanceled():
                break
            feedback.setProgress(int(step / total * 100))

            tinfo = trans_info.get(tid)
            if tinfo is None:
                feedback.pushWarning(f'Transect {tid} absent de la couche transects — ignoré')
                continue

            zref = _z_ref(raw_pts)
            labeled = []
            for p in raw_pts:
                lbl = _label(p['z'], p['classif'], zref, tc, tt, tm)
                fid_to_label[p['fid']] = lbl
                labeled.append((p['d'], p['z'], lbl))

            segs   = _build_segments(labeled, bin_size)
            widths = _widths_from_segs(segs)

            id_ligne = tinfo['id_ligne']
            distance = tinfo['distance']

            # ② Polygones ─────────────────────────────────────────────────────
            if sink_poly:
                for seg in segs:
                    pf = QgsFeature(poly_fields)
                    pf.setGeometry(_strip_polygon(
                        tinfo['p1x'], tinfo['p1y'],
                        tinfo['ux'],  tinfo['uy'],
                        seg['d_start'], seg['d_end'],
                        half_w=0.4,
                    ))
                    pf.setAttributes([
                        int(tid),
                        int(id_ligne),
                        float(distance),
                        seg['label'],
                        float(round(seg['d_start'], 3)),
                        float(round(seg['d_end'],   3)),
                        float(round(seg['width'],   3)),
                        float(round(seg['z_mean'],  3)),
                    ])
                    sink_poly.addFeature(pf)

            #  Profil ────────────────────────────────────────────────────────
            if sink_prof:
                # Point = milieu du segment chaussée (ou centre des points)
                ch_segs = [s for s in segs if s['label'] == 'chaussee']
                if ch_segs:
                    dc = (ch_segs[0]['d_start'] + ch_segs[-1]['d_end']) / 2.0
                else:
                    dc = sum(p['d'] for p in raw_pts) / len(raw_pts)
                cx = tinfo['p1x'] + tinfo['ux'] * dc
                cy = tinfo['p1y'] + tinfo['uy'] * dc
                pf = QgsFeature(prof_fields)
                pf.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(cx, cy)))
                attrs = [int(tid), int(id_ligne), float(round(distance, 3))]
                attrs += [float(round(widths[lbl], 3)) for lbl in LABELS]
                pf.setAttributes(attrs)
                sink_prof.addFeature(pf)

            # Accumulation pour Synthèse ─────────────────────────────────────────────
            if sink_lines:
                entry = by_ligne.setdefault(id_ligne, {
                    'count': 0,
                    'widths': {lbl: 0.0 for lbl in LABELS},
                    'geoms':  [],
                })
                entry['count'] += 1
                for lbl in LABELS:
                    entry['widths'][lbl] += widths[lbl]
                entry['geoms'].append(tinfo['geom'])

        #  Points classifiés ─────────────────────────────────────────────────
        if sink_pts:
            for feat in pts_layer.getFeatures():
                lbl = fid_to_label.get(feat.id(), '')
                nf = QgsFeature(pts_out_fields)
                nf.setGeometry(feat.geometry())
                nf.setAttributes(list(feat.attributes()) + [lbl])
                sink_pts.addFeature(nf)

        #  Synthèse par ligne ────────────────────────────────────────────────
        if sink_lines:
            for id_ligne, entry in sorted(by_ligne.items()):
                n = entry['count']
                # MultiLineString des transects
                mls = QgsMultiLineString()
                for g in entry['geoms']:
                    pts = g.asPolyline()
                    mls.addGeometry(QgsLineString([QgsPoint(p.x(), p.y()) for p in pts]))

                lf = QgsFeature(line_fields)
                lf.setGeometry(QgsGeometry(mls))
                attrs = [int(id_ligne), int(n)]
                attrs += [float(round(entry['widths'][lbl] / n, 3)) for lbl in LABELS]
                lf.setAttributes(attrs)
                sink_lines.addFeature(lf)

        out = {}
        if dest_pts:   out[self.OUT_POINTS]   = dest_pts
        if dest_poly:  out[self.OUT_POLYGONS]  = dest_poly
        if dest_lines: out[self.OUT_LINES]     = dest_lines
        if dest_prof:  out[self.OUT_PROFILE]   = dest_prof
        return out

    # ── métadonnées ───────────────────────────────────────────────────────────

    def name(self):        return 'lidar_classify_transects'
    def displayName(self): return self.tr('Classifier les transects LiDAR')
    def group(self):       return self.tr('LiDAR')
    def groupId(self):     return 'lidar'

    def shortHelpString(self):
        return self.tr(
            'Classifie les points LiDAR de chaque transect en segments fonctionnels\n'
            '(chaussée, caniveau, trottoir, muret, végétation) à partir du profil z.\n\n'
            'Entrées :\n'
            '- Points LiDAR avec champs id_transect, d_along, z, classification\n'
            '- Transects avec champs id_transect, id_ligne, distance\n\n'
            'Sorties (laisser vide = désactivée) :\n'
            ' Points classifiés — copie avec champ « segment »\n'
            ' Polygones de segments — un bandeau par classe par transect\n'
            '   (utiliser la symbologie catégorisée sur « segment »)\n'
            ' Synthèse par ligne — une MultiLineString par id_ligne\n'
            '   avec largeurs moyennes (larg_chaussee, larg_trottoir…)\n'
            ' Profil de largeur — un point par transect positionné sur la\n'
            '   chaussée, avec largeurs → graphable en fonction de « distance »\n\n'
            'Seuils (en mètres au-dessus du plancher z de la chaussée) :\n'
            '  chaussée < seuil_caniveau < caniveau < seuil_trottoir\n'
            '  < trottoir < seuil_muret < muret/obstacle\n'
            '  végétation = classification ASPRS 5 ou 6\n\n'
            'Les seuils dépendent du site — ajuster si la classification\n'
            'ne correspond pas visuellement au profil.'
        )

    def createInstance(self):
        return LidarClassifyTransectsAlgorithm()

    def tr(self, s):
        return QCoreApplication.translate('LidarClassifyTransectsAlgorithm', s)
