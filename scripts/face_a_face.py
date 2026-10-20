"""Écrit docs/face-a-face.html : WR de chaque faction contre chaque autre depuis le dernier dataslate.

Usage : python3 scripts/face_a_face.py
Mêmes chiffres que l'outil d'appariement (scripts/donnees_appariement.py, config/dataslate.json).
"""
import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from donnees_appariement import RACINE, agreger  # noqa: E402

MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"]


def main():
    lh = agreger()
    equipe = json.loads((RACINE / "config/team.json").read_text())
    donnees = {
        "dataslate": lh["dataslate"],
        "weekends_detail": lh["weekends_detail"],
        "factions": lh["factions"],
        "mu": lh["mu"],
        "aja": [{"nom": a["nom"], "couleur": a["couleur"], "couleur_sombre": a["couleur_sombre"]} for a in equipe["armees"]],
    }
    auj = dt.date.today()
    html = (RACINE / "templates/face-a-face.html").read_text()
    html = html.replace("@@DONNEES@@", json.dumps(donnees, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/"))
    html = html.replace("@@MAJ@@", f"{auj.day} {MOIS[auj.month - 1]} {auj.year}")
    (RACINE / "docs/face-a-face.html").write_text(html)
    n = sum(len(v) for v in lh["mu"].values())
    print(f"docs/face-a-face.html : {len(lh['factions'])} factions, {n} face-à-face, "
          f"{lh['weekends_detail']} relevé(s) depuis le {lh['dataslate']}")


if __name__ == "__main__":
    main()
