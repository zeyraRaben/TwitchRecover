#!/usr/bin/env python3
"""Veille miniatures.

Pour chaque chaîne de chaines.txt : liste les dernières vidéos longues (onglet
/videos, donc sans les Shorts), calcule pour chacune un score = vues / médiane
de la chaîne, puis garde les vidéos qui surperforment ET celles qui
sous-performent (pour ne pas tirer de règles uniquement des succès).
Télécharge leurs miniatures et génère une planche HTML + les données en JSON.

Usage : python3 veille.py [--videos 50] [--ignorer-recentes 3] [--sortie sortie]
"""
import argparse
import base64
import html
import io
import json
import statistics
import subprocess
import sys
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ICI = Path(__file__).resolve().parent


def lire_chaines(fichier):
    lignes = Path(fichier).read_text(encoding="utf-8").splitlines()
    return [l.strip() for l in lignes if l.strip() and not l.strip().startswith("#")]


def videos_via_rss(channel_id):
    """Secours si yt-dlp ne remonte pas les vues : 15 dernières vidéos (Shorts exclus)."""
    url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
    ns = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015",
          "media": "http://search.yahoo.com/mrss/"}
    racine = ET.fromstring(urllib.request.urlopen(url, timeout=30).read())
    videos = []
    for e in racine.findall("a:entry", ns):
        if "/shorts/" in (e.find("a:link", ns).get("href") or ""):
            continue
        stats = e.find("media:group/media:community/media:statistics", ns)
        videos.append({"id": e.find("yt:videoId", ns).text, "titre": e.find("a:title", ns).text,
                       "vues": int(stats.get("views")) if stats is not None else None})
    return videos


def lister_videos(handle, n):
    url = f"https://www.youtube.com/{handle}/videos"
    res = subprocess.run(["yt-dlp", "--flat-playlist", "-J", "--playlist-end", str(n),
                          "--extractor-args", "youtube:lang=fr", url],
                         capture_output=True, text=True)
    if res.returncode != 0:
        derniere = (res.stderr.strip().splitlines() or ["yt-dlp a échoué"])[-1]
        raise RuntimeError(derniere)
    data = json.loads(res.stdout)
    nom = data.get("channel") or data.get("uploader") or handle
    videos = [{"id": e["id"], "titre": e.get("title"), "vues": e.get("view_count")}
              for e in data.get("entries") or [] if e.get("id")]
    if sum(1 for v in videos if v["vues"]) < len(videos) / 2 and data.get("channel_id"):
        videos = videos_via_rss(data["channel_id"])
    abonnes = data.get("channel_follower_count")
    if abonnes is None:
        # En français, yt-dlp ne lit pas toujours le nombre d'abonnés : on le redemande sans la langue.
        res = subprocess.run(["yt-dlp", "--flat-playlist", "-J", "--playlist-end", "1", url],
                             capture_output=True, text=True)
        if res.returncode == 0:
            abonnes = json.loads(res.stdout).get("channel_follower_count")
    return nom, abonnes, [v for v in videos if v["vues"]]


def telecharger_miniature(video_id, dossier):
    cible = dossier / f"{video_id}.jpg"
    if cible.exists():
        return cible
    for taille in ("maxresdefault", "hqdefault"):
        try:
            contenu = urllib.request.urlopen(f"https://i.ytimg.com/vi/{video_id}/{taille}.jpg", timeout=30).read()
            cible.write_bytes(contenu)
            return cible
        except Exception:
            continue
    return None


def analyser(handle, nom, abonnes, videos, ignorer_recentes, seuil, nb_flops):
    # L'onglet /videos est trié du plus récent au plus ancien : les toutes
    # dernières n'ont pas encore eu le temps de faire leurs vues. Une petite
    # chaîne (peu de vidéos) est gardée en entier plutôt qu'écartée.
    fenetre = videos[ignorer_recentes:] if len(videos) - ignorer_recentes >= 5 else videos
    if len(fenetre) < 4:
        return None
    mediane = statistics.median(v["vues"] for v in fenetre)
    for v in fenetre:
        v["score"] = round(v["vues"] / mediane, 2)
        v["x_abonnes"] = round(v["vues"] / abonnes, 1) if abonnes else None
    tries = sorted(fenetre, key=lambda v: v["score"], reverse=True)
    return {"handle": handle, "nom": nom, "abonnes": abonnes, "mediane": int(mediane), "nb_videos": len(fenetre),
            "surperforment": [v for v in tries if v["score"] >= seuil],
            "sous_performent": tries[-nb_flops:][::-1]}


def nombre(n):
    return f"{n:,}".replace(",", "\u202f")


def image_inline(chemin, largeur=480):
    """Miniature réduite et intégrée au HTML, pour que la planche tienne en un seul fichier."""
    from PIL import Image
    with Image.open(chemin) as im:
        im = im.convert("RGB")
        im.thumbnail((largeur, largeur))
        tampon = io.BytesIO()
        im.save(tampon, "JPEG", quality=80)
    return "data:image/jpeg;base64," + base64.b64encode(tampon.getvalue()).decode()


def carte(v):
    lien = f"https://www.youtube.com/watch?v={v['id']}"
    image = v.get("miniature")
    img = f'<img src="{image_inline(image)}" alt="">' if image else '<div class="vide">pas de miniature</div>'
    chaine = f'{html.escape(v["chaine"])} · ' if v.get("chaine") else ""
    abonnes = f' · {v["x_abonnes"]}× les abonnés' if v.get("x_abonnes") else ""
    score = f'<b>×{v["score"]}</b> · ' if v.get("score") is not None else ""
    return (f'<a class="carte" href="{lien}" target="_blank">{img}'
            f'<div class="titre">{html.escape(v["titre"] or "")}</div>'
            f'<div class="stats">{chaine}{score}{nombre(v["vues"])} vues{abonnes}</div></a>')


def page(titre, intro, blocs):
    return f"""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(titre)}</title>
<style>
body{{margin:0;padding:24px 16px;background:#0f0f0f;color:#f1f1f1;font:14px/1.4 system-ui,sans-serif}}
h1{{margin:0 0 4px}} h2{{margin:40px 0 8px;border-bottom:1px solid #333;padding-bottom:6px}}
h2 span{{font-size:13px;font-weight:400;color:#aaa}} h3{{color:#2dd4bf;font-size:13px;text-transform:uppercase}}
h3.flop{{color:#f87171}}
.grille{{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:16px}}
.carte{{color:inherit;text-decoration:none}} .carte img,.vide{{width:100%;aspect-ratio:16/9;object-fit:cover;border-radius:8px;background:#222}}
.titre{{margin-top:6px;font-weight:600}} .stats{{color:#aaa;font-size:12px}} .stats b{{color:#f1f1f1}}
</style></head><body><h1>{html.escape(titre)}</h1>
<p style="color:#aaa">{html.escape(intro)}</p>
{"".join(blocs)}</body></html>"""


def planche(resultats):
    top = sorted((dict(v, chaine=r["nom"]) for r in resultats for v in r["surperforment"]),
                 key=lambda v: v["score"], reverse=True)[:24]
    blocs = ['<h2>Top toutes chaînes</h2><div class="grille">' + "".join(carte(v) for v in top) + "</div>"]
    for r in resultats:
        blocs.append(
            f'<h2>{html.escape(r["nom"])} <span>{nombre(r["abonnes"] or 0)} abonnés · médiane {nombre(r["mediane"])} vues · {r["nb_videos"]} vidéos</span></h2>'
            + '<h3>Surperforment</h3><div class="grille">' + "".join(carte(v) for v in r["surperforment"]) + "</div>"
            + '<h3 class="flop">Sous-performent</h3><div class="grille">' + "".join(carte(v) for v in r["sous_performent"]) + "</div>")
    return page("Veille miniatures", "Score = vues ÷ médiane de la chaîne. ×2 = deux fois plus de vues que d'habitude.", blocs)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--chaines", default=ICI / "chaines.txt")
    p.add_argument("--videos", type=int, default=50, help="vidéos analysées par chaîne")
    p.add_argument("--ignorer-recentes", type=int, default=3, help="vidéos trop récentes ignorées")
    p.add_argument("--seuil", type=float, default=2.0, help="score minimum pour 'surperforme'")
    p.add_argument("--flops", type=int, default=3, help="vidéos qui sous-performent gardées par chaîne")
    p.add_argument("--sortie", default=ICI / "sortie")
    args = p.parse_args()

    sortie = Path(args.sortie)
    miniatures = sortie / "miniatures"
    miniatures.mkdir(parents=True, exist_ok=True)
    resultats = []
    for handle in lire_chaines(args.chaines):
        try:
            nom, abonnes, videos = lister_videos(handle, args.videos)
        except Exception as e:
            print(f"✗ {handle} : {e}", file=sys.stderr)
            continue
        r = analyser(handle, nom, abonnes, videos, args.ignorer_recentes, args.seuil, args.flops)
        if not r:
            print(f"✗ {handle} : pas assez de vidéos avec des vues", file=sys.stderr)
            continue
        for v in r["surperforment"] + r["sous_performent"]:
            chemin = telecharger_miniature(v["id"], miniatures)
            v["miniature"] = str(chemin) if chemin else None
        resultats.append(r)
        print(f"✓ {nom} : médiane {r['mediane']} vues, {len(r['surperforment'])} au-dessus de ×{args.seuil}")

    if not resultats:
        sys.exit("Aucune chaîne analysée : YouTube est-il accessible depuis cette machine ?")
    (sortie / "donnees.json").write_text(json.dumps(resultats, ensure_ascii=False, indent=1), encoding="utf-8")
    (sortie / "planche.html").write_text(planche(resultats), encoding="utf-8")
    print(f"→ {sortie / 'planche.html'}")


if __name__ == "__main__":
    main()
