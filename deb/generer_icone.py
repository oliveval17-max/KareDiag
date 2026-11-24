#!/usr/bin/env python3
"""Génère les icônes PNG de KareDiag pour le paquet Debian (.deb).

Deux moteurs :
 - pur Python (stdlib : zlib/struct uniquement) : rendu rasterisé
   indépendant de Qt — **par défaut**, déterministe, sans dépendance ;
 - Qt (QImage + QPainter, plateforme hors-écran) : portage direct de
   icone_karediag() de karediag.py — option `--moteur qt`.

Usage :
    python3 generer_icone.py --dossier <racine-hicolor>
Écrit <racine>/<taille>x<taille>/apps/karediag.png pour 128, 64 et 48.
"""
import argparse
import os
import struct
import sys
import zlib

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

TAILLES = (128, 64, 48)
SUR = 4


_APPLICATION = None


def application_qt():
    """Instance QApplication unique (hors-écran) : indispensable avant
    tout emploi de polices (QFont/drawText) sur une QImage, sous peine
    d'avertissement Qt voire de plantage (segfault). La référence est
    conservée au niveau du module : si Python la ramassait, Qt détruirait
    l'application au vol du dessin."""
    global _APPLICATION
    if _APPLICATION is None:
        from PyQt5.QtWidgets import QApplication

        _APPLICATION = QApplication.instance() or QApplication(
            ["generer_icone"])
    return _APPLICATION


def dessiner_qt(taille):
    """Portage fidèle de icone_karediag() sur une QImage hors-écran."""
    from PyQt5.QtGui import (QColor, QFont, QPainter, QPainterPath, QPen,
                             QImage)
    from PyQt5.QtCore import Qt

    def g(valeur):
        return int(round(valeur * (taille / 128)))

    img = QImage(taille, taille, QImage.Format_ARGB32)
    img.fill(0)
    peintre = QPainter(img)
    peintre.setRenderHint(QPainter.Antialiasing)

    fond = QPainterPath()
    fond.addRoundedRect(g(4), g(4), g(120), g(120), g(24), g(24))
    peintre.fillPath(fond, QColor("#181a1f"))
    peintre.setPen(QPen(QColor("#3e4451"), g(2)))
    peintre.drawPath(fond)

    ecran = QPainterPath()
    ecran.addRoundedRect(g(28), g(42), g(72), g(48), g(8), g(8))
    peintre.fillPath(ecran, QColor("#21252b"))
    peintre.setPen(QPen(QColor("#00bcd4"), g(3)))
    peintre.drawPath(ecran)

    peintre.setPen(Qt.NoPen)
    peintre.setBrush(QColor(0x00, 0xbc, 0xd4, 64))
    peintre.drawRoundedRect(g(36), g(72), g(56), g(10), g(5), g(5))

    peintre.setBrush(QColor("#3e4451"))
    peintre.drawRoundedRect(g(36), g(50), g(40), g(4), g(2), g(2))
    peintre.drawRoundedRect(g(36), g(60), g(28), g(4), g(2), g(2))

    police = QFont("Arial")
    police.setPixelSize(g(30))
    police.setBold(True)
    peintre.setFont(police)
    peintre.setPen(QPen(QColor("#00bcd4")))
    peintre.drawText(0, 0, g(116), g(72),
                     Qt.AlignHCenter | Qt.AlignBottom, "K")

    peintre.setPen(Qt.NoPen)
    peintre.setBrush(QColor("#98c379"))
    peintre.drawEllipse(g(83), g(72), g(10), g(10))

    peintre.end()
    return img


def dessin_pur(taille):
    """Rendu rasterisé de la même géométrie, sans PyQt5 (stdlib seule).

    Renvoie (largeur, hauteur, pixels) avec pixels = liste de lignes
    d'octets RGBA.
    """
    s = taille * SUR
    e = s / 128.0
    canevas = [[[0.0, 0.0, 0.0, 0.0] for _ in range(s)] for _ in range(s)]

    def peindre_point(x, y, r, v, b, a):
        if 0 <= x < s and 0 <= y < s:
            cible = canevas[y][x]
            ancien = cible[3]
            nouveau = a + ancien * (1.0 - a)
            if nouveau > 0:
                cible[0] = (r * a + cible[0] * ancien * (1.0 - a)) / nouveau
                cible[1] = (v * a + cible[1] * ancien * (1.0 - a)) / nouveau
                cible[2] = (b * a + cible[2] * ancien * (1.0 - a)) / nouveau
                cible[3] = nouveau

    def regions(x0, y0, x1, y1, test, couleur):
        x0 = max(0, int(x0) - 2)
        y0 = max(0, int(y0) - 2)
        x1 = min(s, int(x1) + 3)
        y1 = min(s, int(y1) + 3)
        r, v, b, a = couleur
        for yy in range(y0, y1):
            for xx in range(x0, x1):
                if test(xx, yy):
                    peindre_point(xx, yy, r, v, b, a)

    def dans_rect_arrondi(x, y, rx, ry, w, h, rr):
        if not (rx <= x < rx + w and ry <= y < ry + h):
            return False
        qx = max((rx + rr) - x, x - (rx + w - rr), 0.0)
        qy = max((ry + rr) - y, y - (ry + h - rr), 0.0)
        return qx * qx + qy * qy <= rr * rr

    def rect_arrondi(rx, ry, w, h, rr, couleur):
        regions(rx, ry, rx + w, ry + h,
                lambda x, y: dans_rect_arrondi(x, y, rx, ry, w, h, rr),
                couleur)

    def contour_rect_arrondi(rx, ry, w, h, rr, ep, couleur):
        demi = ep / 2.0
        ext = min(rr + demi, (w + ep) / 2.0, (h + ep) / 2.0)
        int_ = max(rr - demi, 0.0)
        regions(rx - demi, ry - demi, rx + w + demi, ry + h + demi,
                lambda x, y: (
                    dans_rect_arrondi(x, y, rx - demi, ry - demi,
                                      w + ep, h + ep, ext)
                    and not dans_rect_arrondi(x, y, rx + demi, ry + demi,
                                              w - ep, h - ep, int_)
                ), couleur)

    def segment(x1, y1, x2, y2, ep, couleur):
        demi = ep / 2.0
        vx, vy = x2 - x1, y2 - y1
        den = vx * vx + vy * vy

        def test(x, y):
            if den > 0:
                t = ((x - x1) * vx + (y - y1) * vy) / den
                t = min(max(t, 0.0), 1.0)
            else:
                t = 0.0
            dx = x - (x1 + t * vx)
            dy = y - (y1 + t * vy)
            return dx * dx + dy * dy <= demi * demi

        regions(min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2),
                test, couleur)

    def cercle(cx, cy, r, couleur):
        segment(cx, cy, cx, cy, 2.0 * r, couleur)

    cyan = (0x00, 0xbc, 0xd4, 1.0)
    gris = (0x3e, 0x44, 0x51, 1.0)

    rect_arrondi(4 * e, 4 * e, 120 * e, 120 * e, 24 * e,
                 (0x18, 0x1a, 0x1f, 1.0))
    contour_rect_arrondi(4 * e, 4 * e, 120 * e, 120 * e, 24 * e, 2 * e, gris)
    rect_arrondi(28 * e, 42 * e, 72 * e, 48 * e, 8 * e,
                 (0x21, 0x25, 0x2b, 1.0))
    contour_rect_arrondi(28 * e, 42 * e, 72 * e, 48 * e, 8 * e, 3 * e, cyan)
    rect_arrondi(36 * e, 72 * e, 56 * e, 10 * e, 5 * e,
                 (0x00, 0xbc, 0xd4, 64 / 255.0))

    segment(50 * e, 50 * e, 50 * e, 72 * e, 5.5 * e, cyan)
    segment(50.5 * e, 62 * e, 66 * e, 50.5 * e, 5.0 * e, cyan)
    segment(52.0 * e, 61 * e, 66.5 * e, 72 * e, 5.0 * e, cyan)

    cercle(88 * e, 77 * e, 5 * e, (0x98, 0xc3, 0x79, 1.0))

    rect_arrondi(36 * e, 50 * e, 40 * e, 4 * e, 2 * e, gris)
    rect_arrondi(36 * e, 60 * e, 28 * e, 4 * e, 2 * e, gris)

    lignes = []
    demi = SUR // 2
    for yy in range(0, s, SUR):
        ligne = bytearray()
        for xx in range(0, s, SUR):
            r = v = b = a = 0.0
            compte = 0
            for dy in range(-demi, SUR - demi):
                for dx in range(-demi, SUR - demi):
                    sy, sx = yy + dy, xx + dx
                    if 0 <= sy < s and 0 <= sx < s:
                        pixel = canevas[sy][sx]
                        r += pixel[0]
                        v += pixel[1]
                        b += pixel[2]
                        a += pixel[3]
                        compte += 1
            n = max(compte, 1)
            ligne += bytes((
                min(255, int(r / n + 0.5)),
                min(255, int(v / n + 0.5)),
                min(255, int(b / n + 0.5)),
                min(255, int((a / n) * 255.0 + 0.5)),
            ))
        lignes.append(bytes(ligne))
    return taille, taille, lignes


def ecrire_png(chemin, largeur, hauteur, lignes):
    def bloc(nom, donnees):
        return (struct.pack(">I", len(donnees)) + nom + donnees
                + struct.pack(">I", zlib.crc32(nom + donnees) & 0xFFFFFFFF))

    entete = struct.pack(">IIBBBBB", largeur, hauteur, 8, 6, 0, 0, 0)
    brut = b"".join(b"\x00" + ligne for ligne in lignes)
    with open(chemin, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n")
        f.write(bloc(b"IHDR", entete))
        f.write(bloc(b"IDAT", zlib.compress(brut, 9)))
        f.write(bloc(b"IEND", b""))


def generer_jeu(dossier, moteur="pur"):
    """Moteur « pur » par défaut : déterministe, sans PyQt5, déjà validé
    visuellement. --moteur qt opt-in pour le rendu Qt des polices."""
    qt_disponible = False
    if moteur == "qt":
        try:
            application_qt()
            from PyQt5.QtGui import QImage  # charge réellement la liaison Qt
            qt_disponible = True
        except Exception:
            qt_disponible = False

    for taille in TAILLES:
        dossier_taille = os.path.join(
            dossier, f"{taille}x{taille}", "apps")
        os.makedirs(dossier_taille, exist_ok=True)
        chemin = os.path.join(dossier_taille, "karediag.png")
        if qt_disponible:
            try:
                dessiner_qt(taille).save(chemin, "PNG")
            except Exception:
                qt_disponible = False
        if not qt_disponible:
            largeur, hauteur, lignes = dessin_pur(taille)
            ecrire_png(chemin, largeur, hauteur, lignes)
    return "Qt hors-écran" if qt_disponible else "pur Python (sans PyQt5)"


def main():
    analyse = argparse.ArgumentParser(
        description="Génère les icônes PNG KareDiag (128/64/48).")
    analyse.add_argument("--dossier", required=True,
                         help="racine du thème hicolor de destination")
    analyse.add_argument("--moteur", choices=("pur", "qt"), default="pur",
                         help="moteur de rendu (pur par défaut)")
    arguments = analyse.parse_args()
    moteur = generer_jeu(arguments.dossier, arguments.moteur)
    print(f"Icônes générées (moteur : {moteur}) dans {arguments.dossier}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
