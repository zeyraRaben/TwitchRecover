#!/usr/bin/env python3
"""Découverte de petites chaînes qui ont percé (le profil « Fog »).

Lance les recherches de requetes.txt sur YouTube, garde les vidéos longues qui
ont fait beaucoup de vues, puis ne retient que les chaînes qui ont peu
d'abonnés : leur vidéo a percé grâce au sujet, au titre et à la miniature,
pas grâce à leur notoriété. Génère une planche HTML + les données en JSON.

Usage : python3 decouverte.py [--resultats 60] [--max-abonnes 150000] [--min-ratio 5]
"""
import argparse
import json
import subprocess
import sys
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from veille import ICI, carte, lire_chaines, page, telecharger_miniature


def yt_dlp_json(url, n, francais):
    langue = ["--extractor-args", "youtube:lang=fr"] if francais else []
    res = subprocess.run(["yt-dlp", "--flat-playlist", "-J", "--playlist-end", str(n), *langue, url],
                         capture_output=True, text=True)
    if res.returncode != 0:
        print(f"✗ {url} : {(res.stderr.strip().splitlines() or ['échec'])[-1]}", file=sys.stderr)
        return {}
    return json.loads(res.stdout)


def chercher(requete, n):
    # En français, yt-dlp lit mal les vues des résultats de recherche (« 1,2 M de vues » → 1) ;
    # en anglais, YouTube traduit les titres. On prend donc les vues en anglais et les titres en français.
    url = "https://www.youtube.com/results?search_query=" + urllib.parse.quote(requete)
    entrees = yt_dlp_json(url, n, francais=False).get("entries") or []
    titres = {e["id"]: e.get("title") for e in yt_dlp_json(url, n, francais=True).get("entries") or []}
    for e in entrees:
        e["title"] = titres.get(e["id"]) or e.get("title")
    return entrees


def abonnes(channel_id):
    res = subprocess.run(["yt-dlp", "--flat-playlist", "-J", "--playlist-end", "1",
                          f"https://www.youtube.com/channel/{channel_id}/videos"], capture_output=True, text=True)
    return json.loads(res.stdout).get("channel_follower_count") if res.returncode == 0 else None


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--requetes", default=ICI / "requetes.txt")
    p.add_argument("--resultats", type=int, default=60, help="résultats lus par recherche")
    p.add_argument("--min-vues", type=int, default=150_000)
    p.add_argument("--min-duree", type=int, default=480, help="secondes (exclut les Shorts et formats courts)")
    p.add_argument("--max-abonnes", type=int, default=150_000)
    p.add_argument("--min-ratio", type=float, default=5, help="vues ÷ abonnés minimum")
    p.add_argument("--sortie", default=ICI / "sortie")
    args = p.parse_args()

    requetes = lire_chaines(args.requetes)
    with ThreadPoolExecutor(4) as pool:
        resultats = list(pool.map(lambda r: chercher(r, args.resultats), requetes))

    # Meilleure vidéo longue de chaque chaîne trouvée.
    meilleures = {}
    for requete, entrees in zip(requetes, resultats):
        for e in entrees:
            cid = e.get("channel_id")
            if not cid or (e.get("view_count") or 0) < args.min_vues or (e.get("duration") or 0) < args.min_duree:
                continue
            if cid not in meilleures or e["view_count"] > meilleures[cid]["vues"]:
                meilleures[cid] = {"id": e["id"], "titre": e.get("title"), "vues": e["view_count"],
                                   "chaine": e.get("channel") or e.get("uploader") or cid,
                                   "channel_id": cid, "requete": requete}
    print(f"{sum(map(len, resultats))} résultats, {len(meilleures)} chaînes avec une vidéo longue ≥ {args.min_vues} vues")

    with ThreadPoolExecutor(8) as pool:
        for v, n in zip(meilleures.values(), pool.map(abonnes, meilleures)):
            v["abonnes"] = n
    trouvees = [v for v in meilleures.values()
                if v["abonnes"] and v["abonnes"] <= args.max_abonnes and v["vues"] / v["abonnes"] >= args.min_ratio]
    for v in trouvees:
        v["x_abonnes"] = round(v["vues"] / v["abonnes"], 1)
    trouvees.sort(key=lambda v: v["x_abonnes"], reverse=True)

    sortie = Path(args.sortie)
    miniatures = sortie / "miniatures"
    miniatures.mkdir(parents=True, exist_ok=True)
    for v in trouvees:
        chemin = telecharger_miniature(v["id"], miniatures)
        v["miniature"] = str(chemin) if chemin else None
        print(f"✓ {v['chaine']} ({v['abonnes']} abonnés) : {v['vues']} vues, ×{v['x_abonnes']} | {v['titre']}")

    (sortie / "decouverte.json").write_text(json.dumps(trouvees, ensure_ascii=False, indent=1), encoding="utf-8")
    intro = (f"Chaînes de moins de {args.max_abonnes:,} abonnés dont une vidéo a fait au moins "
             f"{args.min_ratio:g} fois leur nombre d'abonnés.").replace(",", " ")
    bloc = '<div class="grille">' + "".join(carte(v) for v in trouvees) + "</div>"
    (sortie / "decouverte.html").write_text(page("Petites chaînes qui ont percé", intro, [bloc]), encoding="utf-8")
    print(f"→ {len(trouvees)} chaînes · {sortie / 'decouverte.html'}")


if __name__ == "__main__":
    main()
