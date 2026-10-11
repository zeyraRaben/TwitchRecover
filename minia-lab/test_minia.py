#!/usr/bin/env python3
"""Test d'une miniature : génère une planche de contrôle à partir d'une image.

  1. Original et noir et blanc : le contraste tient-il sans la couleur ?
  2. Saillance : où l'œil va en premier (approximation automatique). Le cadre
     doit tomber sur l'élément qui porte l'émotion.
  3. Taille réelle : 96 px (test du PDF), 168 px (suggestions), 360 px (mobile),
     avec la durée incrustée en bas à droite comme sur YouTube.
  4. Dans le fil : la miniature au milieu de miniatures concurrentes
     (celles de sortie/miniatures, issues de veille.py). Ressort-elle ?

Usage : python3 test_minia.py ma_minia.png [--sortie sortie/tests]
"""
import argparse
import random
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps

ICI = Path(__file__).resolve().parent
FOND = (15, 15, 15)
GRIS = (170, 170, 170)


def police(taille, gras=False):
    nom = "DejaVuSans-Bold.ttf" if gras else "DejaVuSans.ttf"
    try:
        return ImageFont.truetype(f"/usr/share/fonts/truetype/dejavu/{nom}", taille)
    except OSError:
        return ImageFont.load_default(size=taille)


def en_16_9(im, largeur):
    return ImageOps.fit(im.convert("RGB"), (largeur, round(largeur * 9 / 16)), Image.LANCZOS)


def avec_duree(im, texte="18:42"):
    """Ajoute le badge de durée de YouTube, qui masque le coin bas droit."""
    im = im.copy()
    d = ImageDraw.Draw(im)
    f = police(max(8, im.width // 22), gras=True)
    l, h = d.textbbox((0, 0), texte, font=f)[2:]
    marge = max(2, im.width // 60)
    x1, y1 = im.width - marge, im.height - marge
    d.rounded_rectangle((x1 - l - 2 * marge, y1 - h - marge, x1, y1), radius=marge, fill=(0, 0, 0))
    d.text((x1 - l - marge, y1 - h - marge // 2 - 1), texte, font=f, fill=(255, 255, 255))
    return im


def saillance(im):
    """Carte de saillance (résidu spectral) superposée + cadre sur la zone dominante."""
    bgr = cv2.cvtColor(np.array(im), cv2.COLOR_RGB2BGR)
    ok, carte = cv2.saliency.StaticSaliencySpectralResidual_create().computeSaliency(bgr)
    carte = cv2.GaussianBlur((carte * 255).astype("uint8"), (0, 0), im.width / 60)
    carte = cv2.normalize(carte, None, 0, 255, cv2.NORM_MINMAX)
    couleurs = cv2.applyColorMap(carte, cv2.COLORMAP_JET)
    melange = cv2.addWeighted(bgr, 0.45, couleurs, 0.55, 0)
    _, masque = cv2.threshold(carte, np.percentile(carte, 92), 255, cv2.THRESH_BINARY)
    n, _, stats, _ = cv2.connectedComponentsWithStats(masque)
    if n > 1:
        x, y, w, h, _ = stats[1:][np.argmax(stats[1:, cv2.CC_STAT_AREA])]
        cv2.rectangle(melange, (x, y), (x + w, y + h), (255, 255, 255), 3)
    return Image.fromarray(cv2.cvtColor(melange, cv2.COLOR_BGR2RGB))


def titre(d, xy, texte, sous=None):
    d.text(xy, texte, font=police(20, gras=True), fill=(241, 241, 241))
    if sous:
        d.text((xy[0], xy[1] + 26), sous, font=police(14), fill=GRIS)


def planche(chemin, concurrents):
    im = Image.open(chemin)
    L, M = 620, 20
    grand = en_16_9(im, L)
    H = grand.height
    largeur_tuile = (2 * L + M - 3 * 14) // 4
    hauteur_tuile = round(largeur_tuile * 9 / 16)
    hauteur = 90 + (H + 70) * 2 + 56 + 2 * hauteur_tuile + 20 + 30
    feuille = Image.new("RGB", (2 * L + 3 * M, hauteur), FOND)
    d = ImageDraw.Draw(feuille)
    d.text((M, 24), f"Test miniature · {Path(chemin).name}", font=police(28, gras=True), fill=(45, 212, 191))

    y = 90
    titre(d, (M, y), "Original")
    titre(d, (2 * M + L, y), "Noir et blanc", "Si l'élément clé disparaît ici, il ne tient que par la couleur.")
    feuille.paste(grand, (M, y + 56))
    feuille.paste(ImageOps.grayscale(grand).convert("RGB"), (2 * M + L, y + 56))

    y += H + 70
    titre(d, (M, y), "Où l'œil va en premier", "Approximation automatique. Le cadre blanc = zone dominante.")
    feuille.paste(saillance(grand), (M, y + 56))
    titre(d, (2 * M + L, y), "Taille réelle", "96 px (test du PDF) · 168 px (suggestions) · 360 px (mobile)")
    x0, y0 = 2 * M + L, y + 56
    feuille.paste(avec_duree(en_16_9(im, 96)), (x0, y0 + 94 - 54))
    feuille.paste(avec_duree(en_16_9(im, 168)), (x0 + 96 + 14, y0))
    feuille.paste(avec_duree(en_16_9(im, 360)), (x0, y0 + 94 + 14))

    y += H + 70
    titre(d, (M, y), "Dans le fil", "Ta miniature est quelque part dans cette grille. La retrouves-tu en une seconde ?")
    tuiles = random.sample(concurrents, min(7, len(concurrents)))
    position = random.randrange(len(tuiles) + 1)
    tuiles.insert(position, chemin)
    for i, t in enumerate(tuiles):
        with Image.open(t) as source:
            tuile = avec_duree(en_16_9(source, largeur_tuile))
        feuille.paste(tuile, (M + (i % 4) * (largeur_tuile + 14), y + 56 + (i // 4) * (hauteur_tuile + 20)))
    return feuille, position + 1


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("images", nargs="+")
    p.add_argument("--concurrents", default=ICI / "sortie" / "miniatures")
    p.add_argument("--sortie", default=ICI / "sortie" / "tests")
    args = p.parse_args()

    sortie = Path(args.sortie)
    sortie.mkdir(parents=True, exist_ok=True)
    for chemin in args.images:
        concurrents = [str(c) for c in Path(args.concurrents).glob("*.jpg") if c.resolve() != Path(chemin).resolve()]
        feuille, position = planche(chemin, concurrents)
        cible = sortie / f"{Path(chemin).stem}_test.png"
        feuille.save(cible)
        print(f"→ {cible} (dans le fil : position {position})")


if __name__ == "__main__":
    main()
