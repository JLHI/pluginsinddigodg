# -*- coding: utf-8 -*-
"""
/***************************************************************************
 CompressionImages
                                 A QGIS plugin
 Compression / redimensionnement par lot d'images (JPEG, PNG) via Pillow.
                              -------------------
        copyright            : (C) 2026 by JLHI
        email                : jl.humbert@inddigo.com
 ***************************************************************************/

 Pillow (PIL) n'est PAS embarqué dans le plugin : il est déjà fourni par
 QGIS dans toutes les installations. L'import est fait dans processAlgorithm
 avec un message clair si jamais il était absent.
"""

__author__ = 'JLHI'
__date__ = '2026-06-25'
__copyright__ = '(C) 2026 by JLHI'

import os
import shutil
import threading
import concurrent.futures

from qgis.PyQt.QtCore import QCoreApplication
from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingParameterFile,
    QgsProcessingParameterFolderDestination,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterNumber,
    QgsProcessingParameterEnum,
    QgsProcessingParameterDefinition,
)


class CompressionImagesAlgorithm(QgsProcessingAlgorithm):

    # --- Identifiants des paramètres -------------------------------------
    INPUT_FOLDER = 'INPUT_FOLDER'
    OUTPUT_FOLDER = 'OUTPUT_FOLDER'
    RECURSIVE = 'RECURSIVE'
    FORMATS = 'FORMATS'
    SIZE_LIMIT_KB = 'SIZE_LIMIT_KB'
    QUALITY = 'QUALITY'
    OPTIMIZE = 'OPTIMIZE'
    PROGRESSIVE = 'PROGRESSIVE'
    SUBSAMPLING = 'SUBSAMPLING'
    PNG_COMPRESS_LEVEL = 'PNG_COMPRESS_LEVEL'
    KEEP_EXIF = 'KEEP_EXIF'
    RESAMPLING = 'RESAMPLING'
    MAX_DIMENSION = 'MAX_DIMENSION'
    REDUCTION_STEP = 'REDUCTION_STEP'
    MIN_DIMENSION = 'MIN_DIMENSION'

    # Formats proposés (libellé -> extensions reconnues)
    _FORMATS = (
        ('JPEG / JPG', ('.jpg', '.jpeg')),
        ('PNG', ('.png',)),
    )
    # Libellés de sous-échantillonnage JPEG (-1 = laisser Pillow décider)
    _SUBSAMPLING = (
        ('Automatique', -1),
        ('4:4:4 (aucun, max qualité)', 0),
        ('4:2:2', 1),
        ('4:2:0 (max compression)', 2),
    )
    # Libellés de filtre de rééchantillonnage -> attribut Image.Resampling
    _RESAMPLING = (
        ('Lanczos (meilleure qualité)', 'LANCZOS'),
        ('Bicubique', 'BICUBIC'),
        ('Bilinéaire', 'BILINEAR'),
        ('Plus proche voisin (rapide)', 'NEAREST'),
    )

    # ---------------------------------------------------------------------
    # PARAMÈTRES
    # ---------------------------------------------------------------------
    def initAlgorithm(self, config=None):

        self.addParameter(QgsProcessingParameterFile(
            self.INPUT_FOLDER,
            self.tr('Dossier des images source'),
            behavior=QgsProcessingParameterFile.Folder,
        ))

        self.addParameter(QgsProcessingParameterFolderDestination(
            self.OUTPUT_FOLDER,
            self.tr('Dossier de sortie (laisser vide = écraser dans le dossier source)'),
            optional=True,
            createByDefault=False,
        ))

        self.addParameter(QgsProcessingParameterEnum(
            self.FORMATS,
            self.tr('Formats à traiter'),
            options=[label for label, _ in self._FORMATS],
            allowMultiple=True,
            defaultValue=[0, 1],
        ))

        self.addParameter(QgsProcessingParameterNumber(
            self.SIZE_LIMIT_KB,
            self.tr('Seuil de taille (Ko) : compresser au-delà, copier en deçà'),
            type=QgsProcessingParameterNumber.Integer,
            defaultValue=1000,
            minValue=1,
        ))

        self.addParameter(QgsProcessingParameterNumber(
            self.QUALITY,
            self.tr('Qualité JPEG (1-100)'),
            type=QgsProcessingParameterNumber.Integer,
            defaultValue=90,
            minValue=1,
            maxValue=100,
        ))

        self.addParameter(QgsProcessingParameterNumber(
            self.PNG_COMPRESS_LEVEL,
            self.tr('Niveau de compression PNG (0-9)'),
            type=QgsProcessingParameterNumber.Integer,
            defaultValue=6,
            minValue=0,
            maxValue=9,
        ))

        # --- Paramètres masqués (conservés, non affichés dans le formulaire)
        # Ces paramètres restent fonctionnels avec leur valeur par défaut et
        # sont toujours appliqués par le traitement. Ils sont seulement cachés
        # de l'interface utilisateur (FlagHidden) ; on peut les régler via le
        # mode « Exécuter comme script » ou en retirant le drapeau ci-dessous.
        hidden = [
            QgsProcessingParameterBoolean(
                self.RECURSIVE,
                self.tr('Parcourir aussi les sous-dossiers'),
                defaultValue=False,
            ),
            QgsProcessingParameterNumber(
                self.MAX_DIMENSION,
                self.tr('Dimension max du plus grand côté (px, 0 = désactivé)'),
                type=QgsProcessingParameterNumber.Integer,
                defaultValue=0,
                minValue=0,
            ),
            QgsProcessingParameterBoolean(
                self.OPTIMIZE,
                self.tr('Optimiser l\'encodage (optimize)'),
                defaultValue=True,
            ),
            QgsProcessingParameterBoolean(
                self.PROGRESSIVE,
                self.tr('JPEG progressif'),
                defaultValue=False,
            ),
            QgsProcessingParameterEnum(
                self.SUBSAMPLING,
                self.tr('Sous-échantillonnage chroma JPEG'),
                options=[label for label, _ in self._SUBSAMPLING],
                defaultValue=0,
            ),
            QgsProcessingParameterBoolean(
                self.KEEP_EXIF,
                self.tr('Conserver les métadonnées EXIF (JPEG)'),
                defaultValue=True,
            ),
            QgsProcessingParameterEnum(
                self.RESAMPLING,
                self.tr('Filtre de rééchantillonnage'),
                options=[label for label, _ in self._RESAMPLING],
                defaultValue=0,
            ),
            QgsProcessingParameterNumber(
                self.REDUCTION_STEP,
                self.tr('Réduction par itération (%) pour atteindre le seuil'),
                type=QgsProcessingParameterNumber.Integer,
                defaultValue=15,
                minValue=1,
                maxValue=90,
            ),
            QgsProcessingParameterNumber(
                self.MIN_DIMENSION,
                self.tr('Dimension minimale autorisée (px) — garde-fou'),
                type=QgsProcessingParameterNumber.Integer,
                defaultValue=200,
                minValue=1,
            ),
        ]
        for p in hidden:
            p.setFlags(p.flags() | QgsProcessingParameterDefinition.FlagHidden)
            self.addParameter(p)

    # ---------------------------------------------------------------------
    # TRAITEMENT
    # ---------------------------------------------------------------------
    def processAlgorithm(self, parameters, context, feedback):

        # Pillow est fourni par QGIS ; garde-fou si absent.
        try:
            from PIL import Image
        except ImportError:
            raise QgsProcessingException(self.tr(
                "La librairie Pillow (PIL) est introuvable dans cette installation "
                "de QGIS. Installez-la depuis l'invite OSGeo4W : « python -m pip "
                "install Pillow »."
            ))

        src_dir = self.parameterAsFile(parameters, self.INPUT_FOLDER, context)
        if not src_dir or not os.path.isdir(src_dir):
            raise QgsProcessingException(self.tr('Dossier source invalide.'))

        out_dir = self.parameterAsString(parameters, self.OUTPUT_FOLDER, context)
        if not out_dir:
            out_dir = src_dir
        os.makedirs(out_dir, exist_ok=True)
        in_place = os.path.normcase(os.path.abspath(out_dir)) == \
            os.path.normcase(os.path.abspath(src_dir))

        recursive = self.parameterAsBool(parameters, self.RECURSIVE, context)
        fmt_idx = self.parameterAsEnums(parameters, self.FORMATS, context)
        if not fmt_idx:
            raise QgsProcessingException(self.tr('Aucun format sélectionné.'))
        exts = tuple(e for i in fmt_idx for e in self._FORMATS[i][1])

        size_limit = self.parameterAsInt(parameters, self.SIZE_LIMIT_KB, context) * 1024
        quality = self.parameterAsInt(parameters, self.QUALITY, context)
        optimize = self.parameterAsBool(parameters, self.OPTIMIZE, context)
        progressive = self.parameterAsBool(parameters, self.PROGRESSIVE, context)
        subsampling = self._SUBSAMPLING[
            self.parameterAsEnum(parameters, self.SUBSAMPLING, context)][1]
        png_level = self.parameterAsInt(parameters, self.PNG_COMPRESS_LEVEL, context)
        keep_exif = self.parameterAsBool(parameters, self.KEEP_EXIF, context)
        resample = getattr(
            Image.Resampling,
            self._RESAMPLING[self.parameterAsEnum(parameters, self.RESAMPLING, context)][1])
        reduction = self.parameterAsInt(parameters, self.REDUCTION_STEP, context) / 100.0
        min_dim = self.parameterAsInt(parameters, self.MIN_DIMENSION, context)
        max_dim = self.parameterAsInt(parameters, self.MAX_DIMENSION, context)

        # Collecte des fichiers
        files = []
        if recursive:
            for root, _, names in os.walk(src_dir):
                for n in names:
                    if n.lower().endswith(exts):
                        files.append(os.path.join(root, n))
        else:
            for n in os.listdir(src_dir):
                full = os.path.join(src_dir, n)
                if os.path.isfile(full) and n.lower().endswith(exts):
                    files.append(full)

        if not files:
            feedback.pushInfo(self.tr('Aucune image correspondante trouvée.'))
            return {self.OUTPUT_FOLDER: out_dir, 'COMPRESSED': 0,
                    'COPIED': 0, 'SKIPPED': 0}

        total = len(files)
        n_compressed = n_copied = n_skipped = 0

        # Configuration immuable transmise à chaque worker. On y exclut
        # volontairement 'feedback' : c'est un objet Qt qui n'est pas
        # thread-safe et qui doit rester piloté depuis le thread principal.
        cfg = {
            'src_dir': src_dir, 'out_dir': out_dir, 'in_place': in_place,
            'size_limit': size_limit, 'quality': quality, 'optimize': optimize,
            'progressive': progressive, 'subsampling': subsampling,
            'png_level': png_level, 'keep_exif': keep_exif, 'resample': resample,
            'reduction': reduction, 'min_dim': min_dim, 'max_dim': max_dim,
        }

        # Le travail lourd de Pillow (décodage / resize / encodage) libère le
        # GIL : un pool de threads donne donc un parallélisme réel, sans les
        # contraintes du multiprocessing dans QGIS (spawn, ré-import, pickling).
        cancel = threading.Event()
        workers = max(1, min(total, os.cpu_count() or 4))
        feedback.pushInfo(self.tr(
            'Traitement de {} image(s) sur {} thread(s)…').format(total, workers))

        done = 0
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=workers)
        futures = [executor.submit(self._process_one, p, cfg, cancel)
                   for p in files]
        pending = set(futures)
        try:
            while pending:
                # On teste l'annulation à intervalle court (timeout), même si
                # aucun worker ne se termine : l'algo ne reste donc jamais bloqué
                # et les threads en cours sont prévenus au plus vite via 'cancel'.
                if feedback.isCanceled():
                    break
                complete, pending = concurrent.futures.wait(
                    pending, timeout=0.2,
                    return_when=concurrent.futures.FIRST_COMPLETED)
                for fut in complete:
                    res = fut.result()
                    status = res['status']
                    if status == 'compressed':
                        n_compressed += 1
                    elif status == 'copied':
                        n_copied += 1
                    elif status == 'skipped':
                        n_skipped += 1
                    # 'cancelled' : tâche ignorée avant traitement, non comptée

                    for msg in res['messages']:
                        feedback.pushInfo(msg)
                    if res['error']:
                        feedback.reportError(res['error'])

                    done += 1
                    feedback.setProgress(int(done * 100.0 / total))
        finally:
            # Arme l'annulation (stoppe les boucles internes des workers), puis
            # abandonne les tâches non démarrées et attend la fin des save()
            # déjà lancés — un appel Pillow save() en cours n'est pas
            # interruptible, mais leur nombre est borné au nombre de threads.
            cancel.set()
            executor.shutdown(wait=True, cancel_futures=True)

        if feedback.isCanceled():
            feedback.pushInfo(self.tr('Annulé par l\'utilisateur.'))
        feedback.pushInfo(self.tr(
            'Terminé. Compressées : {} | Copiées : {} | Ignorées : {}').format(
                n_compressed, n_copied, n_skipped))
        return {self.OUTPUT_FOLDER: out_dir, 'COMPRESSED': n_compressed,
                'COPIED': n_copied, 'SKIPPED': n_skipped}

    def _process_one(self, src_path, cfg, cancel):
        """Traite UNE image — exécuté dans un thread worker.

        N'accède jamais à 'feedback'. Renvoie un dict
        {status, messages, error} consommé par le thread principal.
        'cancel' est un threading.Event partagé pour l'annulation."""
        from PIL import Image

        result = {'status': 'skipped', 'messages': [], 'error': None}
        rel = os.path.relpath(src_path, cfg['src_dir'])

        if cancel.is_set():
            result['status'] = 'cancelled'
            return result

        try:
            dst_path = os.path.join(cfg['out_dir'], rel)
            os.makedirs(os.path.dirname(dst_path), exist_ok=True)

            size = os.path.getsize(src_path)
            need_resize_dim = False
            if cfg['max_dim'] > 0:
                with Image.open(src_path) as probe:
                    if max(probe.size) > cfg['max_dim']:
                        need_resize_dim = True

            # Sous le seuil et pas de bridage de dimension : copie directe
            if size <= cfg['size_limit'] and not need_resize_dim:
                if not (cfg['in_place'] and os.path.abspath(src_path) ==
                        os.path.abspath(dst_path)):
                    shutil.copy2(src_path, dst_path)
                result['status'] = 'copied'
                result['messages'].append(
                    self.tr('Copié sans compression : {}').format(rel))
                return result

            # Évite d'entamer un décodage + ré-encodage coûteux si l'annulation
            # est survenue pendant la lecture de la taille / le probe ci-dessus.
            if cancel.is_set():
                result['status'] = 'cancelled'
                return result

            ext = os.path.splitext(src_path)[1].lower()
            save_fmt = 'PNG' if ext == '.png' else 'JPEG'

            with Image.open(src_path) as img:
                img.load()
                exif = img.info.get('exif') if cfg['keep_exif'] else None

                # Bridage de la dimension maximale
                if cfg['max_dim'] > 0 and max(img.size) > cfg['max_dim']:
                    img = self._scale_to_max(img, cfg['max_dim'], cfg['resample'])

                save_kwargs = self._build_save_kwargs(
                    save_fmt, cfg['quality'], cfg['optimize'], cfg['progressive'],
                    cfg['subsampling'], cfg['png_level'], exif)
                if save_fmt == 'JPEG':
                    img = self._ensure_rgb(img)

                final_size, note = self._save_under_limit(
                    img, dst_path, save_fmt, save_kwargs, cfg['size_limit'],
                    cfg['reduction'], cfg['min_dim'], cfg['resample'], cancel)
                if note:
                    result['messages'].append(note)

            result['status'] = 'compressed'
            result['messages'].append(self.tr(
                'Compressé : {} ({} Ko -> {} Ko)').format(
                    rel, size // 1024, final_size // 1024))

        except Exception as e:
            result['status'] = 'skipped'
            result['error'] = self.tr('Ignoré (erreur) {} : {}').format(rel, e)

        return result

    # ---------------------------------------------------------------------
    # OUTILS INTERNES
    # ---------------------------------------------------------------------
    @staticmethod
    def _ensure_rgb(img):
        """JPEG ne supporte pas l'alpha / la palette : on convertit en RGB."""
        if img.mode in ('RGBA', 'LA', 'P'):
            return img.convert('RGB')
        if img.mode != 'RGB':
            return img.convert('RGB')
        return img

    @staticmethod
    def _scale_to_max(img, max_dim, resample):
        w, h = img.size
        ratio = max_dim / float(max(w, h))
        return img.resize((max(1, int(w * ratio)), max(1, int(h * ratio))), resample)

    @staticmethod
    def _build_save_kwargs(save_fmt, quality, optimize, progressive,
                           subsampling, png_level, exif):
        if save_fmt == 'PNG':
            kw = {'optimize': optimize, 'compress_level': png_level}
        else:  # JPEG
            kw = {'quality': quality, 'optimize': optimize,
                  'progressive': progressive}
            if subsampling != -1:
                kw['subsampling'] = subsampling
            if exif:
                kw['exif'] = exif
        return kw

    def _save_under_limit(self, img, dst_path, save_fmt, save_kwargs,
                          size_limit, reduction, min_dim, resample, cancel):
        """Sauvegarde, puis réduit itérativement les dimensions jusqu'à passer
        sous le seuil (via un fichier temporaire pour ne jamais corrompre la
        cible avant d'avoir une version valide).

        Renvoie un couple (taille_finale, note) ; 'note' est un éventuel
        message à remonter au thread principal, ou None. 'cancel' est le
        threading.Event partagé : la boucle s'interrompt dès qu'il est armé."""
        note = None
        tmp_path = dst_path + '.tmp'
        img.save(tmp_path, format=save_fmt, **save_kwargs)
        size = os.path.getsize(tmp_path)

        while size > size_limit:
            if cancel.is_set():
                break
            w, h = img.size
            new_w, new_h = int(w * (1 - reduction)), int(h * (1 - reduction))
            if min(new_w, new_h) < min_dim:
                note = self.tr('Dimension minimale atteinte, seuil non garanti.')
                break
            img = img.resize((new_w, new_h), resample)
            img.save(tmp_path, format=save_fmt, **save_kwargs)
            size = os.path.getsize(tmp_path)

        os.replace(tmp_path, dst_path)
        return size, note

    # ---------------------------------------------------------------------
    # MÉTADONNÉES
    # ---------------------------------------------------------------------
    def name(self):
        return 'compression_images'

    def displayName(self):
        return self.tr('Compresser des images')

    def group(self):
        return self.tr('Boite à outil')

    def groupId(self):
        return 'boite_outils'

    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):
        return CompressionImagesAlgorithm()

    def shortHelpString(self):
        return self.tr("""
        <p>Compresse et/ou redimensionne par lot les images d'un dossier
        (JPEG, PNG) à l'aide de la librairie Pillow fournie par QGIS.</p>
        <p>Les images sous le seuil de taille sont copiées sans modification. 
        Les images au-dessus du seuil sont ré-encodées puis, si nécessaire, réduites par paliers
        jusqu'à passer sous le seuil.</p>
        <h3>Paramètres</h3>
        <ul>
          <li><b>Dossier source</b> / <b>Dossier de sortie</b> : laisser la
          sortie vide écrase les images dans le dossier source.</li>
          <li><b>Formats à traiter</b> : JPEG/JPG et/ou PNG.</li>
          <li><b>Seuil de taille (Ko)</b> : limite au-delà de laquelle on
          compresse.</li>
          <li><b>Qualité JPEG</b> : 1-100.</li>
          <li><b>Niveau de compression PNG</b> : 0-9.</li>
        </ul>
        
        """)
