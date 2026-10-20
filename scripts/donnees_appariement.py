"""Injecte les chiffres Listhammer depuis le dernier dataslate dans outils/appariement.html.

Usage : python3 scripts/donnees_appariement.py
La date du dataslate est dans config/dataslate.json (à changer à chaque nouveau dataslate).

Remplace le bloc entre /*LH*/ et /*FIN-LH*/ par :
  factions : WR et parties de chaque faction, somme des semaines de la tendance Listhammer après le dataslate
  det      : WR et parties de chaque combinaison de détachements (noms triés, séparés par " | ")
  mu       : face-à-face faction contre faction (WR de la faction en clé, parties)
  disp     : WR global de chaque force de disposition (dernier relevé)
Les détachements et face-à-face ne sont publiés que pour le week-end : on additionne les relevés
hebdomadaires de data/ dont le week-end tombe après le dataslate.
WR = victoires / (victoires + défaites), comme Listhammer (nuls exclus).
"""
import json
import re
from collections import defaultdict
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
PAGE = RACINE / "outils/appariement.html"


def wr(v, t):
    return [round(100 * v / t, 1) if t else 0, t]


def agreger():
    """Chiffres Listhammer depuis le dernier dataslate (voir l'en-tête du module)."""
    dataslate = json.loads((RACINE / "config/dataslate.json").read_text())["date"]
    releves = []
    for dossier in sorted(p for p in (RACINE / "data").iterdir() if p.is_dir()):
        stats = json.loads((dossier / "stats.json").read_text())
        if stats["fenetre"]["fin"] > dataslate:
            releves.append(dossier)
    if not releves:
        raise SystemExit(f"aucun relevé après le dataslate du {dataslate}")
    dernier = releves[-1]

    factions, semaines = {}, set()
    det = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    mu = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    for dossier in releves:
        for f in sorted((dossier / "factions").glob("*.json")):
            d = json.loads(f.read_text())
            for c in d.get("combinaisons") or []:
                if c.get("detachment") and c["detachment"] != "Unknown":
                    k = " | ".join(sorted(c["detachment"].split(" | ")))
                    det[d["nom"]][k][0] += c["wins"]; det[d["nom"]][k][1] += c["wins"] + c["losses"]
            for m in d.get("adversaires") or []:
                if m.get("opponentFaction"):
                    mu[d["nom"]][m["opponentFaction"]][0] += m["wins"]
                    mu[d["nom"]][m["opponentFaction"]][1] += m["wins"] + m["losses"]
    # WR faction : la tendance du dernier relevé couvre tout l'historique, semaine par semaine
    for f in sorted((dernier / "factions").glob("*.json")):
        d = json.loads(f.read_text())
        tendance = [w for w in d.get("tendance") or [] if w["week"] > dataslate]
        if tendance:
            semaines.update(w["week"] for w in tendance)
            v = sum(w["wins"] for w in tendance); t = sum(w["wins"] + w["losses"] for w in tendance)
        else:  # relevé sans tendance : on retombe sur la somme des week-ends relevés
            v = sum(c[0] for c in mu[d["nom"]].values()); t = sum(c[1] for c in mu[d["nom"]].values())
        factions[d["nom"]] = wr(v, t)

    lh = {
        "dataslate": dataslate,
        "semaine": dernier.name,
        "weekends_faction": len(semaines),
        "weekends_detail": len(releves),
        "factions": factions,
        "det": {f: {k: wr(*x) for k, x in v.items()} for f, v in det.items()},
        "mu": {f: {k: wr(*x) for k, x in v.items()} for f, v in mu.items()},
        "disp": json.loads((dernier / "resume.json").read_text()).get("dispositions", {}),
        "releves": [p.name for p in releves],
    }
    return lh


def main():
    lh = agreger()
    html = PAGE.read_text()
    bloc = "/*LH*/" + json.dumps(lh, ensure_ascii=False, separators=(",", ":")) + "/*FIN-LH*/"
    html, n = re.subn(r"/\*LH\*/.*?/\*FIN-LH\*/", lambda _: bloc, html, flags=re.S)
    if n != 1:
        raise SystemExit("marqueurs /*LH*/ … /*FIN-LH*/ introuvables dans outils/appariement.html")
    PAGE.write_text(html)
    print(f"depuis le dataslate du {lh['dataslate']} : WR faction sur {lh['weekends_faction']} week-ends, "
          f"détachements et face-à-face sur {lh['weekends_detail']} relevé(s) ({', '.join(lh['releves'])})")


if __name__ == "__main__":
    main()
