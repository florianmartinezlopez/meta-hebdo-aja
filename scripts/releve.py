"""Relevé hebdomadaire Listhammer : /stats et les 28 pages factions.

Respecte robots.txt (pas d'/api/, /players/, /events/, /list/), une requête toutes les 2 s au moins,
User-Agent identifiable. Écrit data/<AAAA-Wss>/ et affiche le dossier créé.
Sort en erreur (code 1) si la structure du site a changé : rien n'est alors écrit.
"""
import csv
import datetime as dt
import json
import pathlib
import re
import sys
import time
import urllib.request
import urllib.robotparser

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from nuxt import charger_payload, texte_visible, trouver  # noqa: E402

RACINE = pathlib.Path(__file__).resolve().parent.parent
SITE = "https://listhammer.info"
UA = "MetaHebdoAJA/1.0 (+https://github.com/florianmartinezlopez/meta-hebdo-aja)"
PAUSE = 2.5
MOIS_EN = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}
DISPOSITIONS = {"Take and Hold", "Purge the Foe", "Priority Assets", "Reconnaissance", "Disruption"}

_dernier = 0.0


def lire(chemin):
    global _dernier
    attente = PAUSE - (time.time() - _dernier)
    if attente > 0:
        time.sleep(attente)
    for essai in range(3):
        try:
            req = urllib.request.Request(SITE + chemin, headers={"User-Agent": UA, "Accept": "text/html"})
            with urllib.request.urlopen(req, timeout=60) as r:
                _dernier = time.time()
                return r.read().decode("utf-8")
        except Exception as e:  # réseau capricieux : on retente gentiment
            _dernier = time.time()
            if essai == 2:
                raise RuntimeError(f"lecture de {chemin} impossible : {e}") from e
            time.sleep(10 * (essai + 1))


def verifier_robots(chemins):
    rp = urllib.robotparser.RobotFileParser()
    rp.parse(lire("/robots.txt").splitlines())
    for c in chemins:
        if not rp.can_fetch(UA, SITE + c):
            raise RuntimeError(f"robots.txt interdit désormais {c} : relevé arrêté")


def fenetre(html, aujourdhui):
    """« Meta Breakdown 15 Oct - 20 Oct 2026 » -> (début, fin)."""
    t = texte_visible(html)
    m = re.search(r"Meta Breakdown\s+(\d{1,2}) (\w{3})\w* - (\d{1,2}) (\w{3})\w* (\d{4})", t)
    if m and m.group(2) in MOIS_EN and m.group(4) in MOIS_EN:
        an = int(m.group(5))
        fin = dt.date(an, MOIS_EN[m.group(4)], int(m.group(3)))
        debut = dt.date(an if MOIS_EN[m.group(2)] <= MOIS_EN[m.group(4)] else an - 1,
                        MOIS_EN[m.group(2)], int(m.group(1)))
        return debut, fin, True
    samedi = aujourdhui - dt.timedelta(days=(aujourdhui.weekday() - 5) % 7)
    return samedi - dt.timedelta(days=2), samedi + dt.timedelta(days=2), False


def main():
    factions = json.loads((RACINE / "config/factions.json").read_text())
    verifier_robots(["/stats"] + [f"/factions/{s}" for s in factions])
    maintenant = dt.datetime.now(dt.timezone.utc)

    html = lire("/stats")
    p = charger_payload(html)
    bloc_f = trouver(p, "result", "recentEvents")
    bloc_d = trouver(p, "overall", "matchups")
    debut, fin, fenetre_lue = fenetre(html, maintenant.date())
    samedi = next(debut + dt.timedelta(days=i) for i in range(7) if (debut + dt.timedelta(days=i)).weekday() == 5)
    an, sem, _ = samedi.isocalendar()
    semaine = f"{an}-W{sem:02d}"

    res = bloc_f["result"]
    if len(res) < 20 or not all({"faction", "winRate", "total", "players"} <= set(r) for r in res):
        raise RuntimeError(f"tableau des factions inattendu ({len(res)} lignes)")
    if {d["disposition"] for d in bloc_d["overall"]} != DISPOSITIONS:
        raise RuntimeError("liste des forces de disposition inattendue")
    m = re.search(r"(\d+) events? (?:are|is) still being played", texte_visible(html))
    evts = bloc_f["recentEvents"]
    for r in res:  # « Space Marines (Astartes) » -> « Space Marines »
        r["faction"] = re.sub(r"\s*\(.*?\)", "", r["faction"]).strip()
    inconnues = {r["faction"] for r in res} - set(factions.values())
    if inconnues:
        print(f"  attention, factions inconnues de config/factions.json : {inconnues}", file=sys.stderr)

    stats = {
        "semaine": semaine,
        "releve_le": maintenant.isoformat(timespec="minutes"),
        "fenetre": {"debut": debut.isoformat(), "fin": fin.isoformat(), "lue_sur_le_site": fenetre_lue},
        "tournois": evts,
        "tournois_en_cours": int(m.group(1)) if m else sum(1 for e in evts if not e.get("ended")),
        "factions": res,
        "dispositions": bloc_d["overall"],
        "matrice": bloc_d["matchups"],
    }

    pages = {}
    listes = []
    for slug, nom in factions.items():
        hp = charger_payload(lire(f"/factions/{slug}"))
        fa = trouver(hp, "detachmentCombinations", "dispositions")
        rl = trouver(hp, "result", "totalCount")
        lst = []
        for l in rl["result"]:
            if l.get("isRtt"):
                continue
            lst.append({k: l.get(k) for k in (
                "playerName", "playerUid", "eventName", "eventUid", "numberOfPlayers", "numberOfRounds",
                "wins", "draws", "losses", "detachment", "disposition", "startDate")})
        pages[slug] = {
            "nom": nom, "slug": slug,
            "periode": fa.get("headline"), "joueurs": fa.get("players"),
            "invaincus": fa.get("undefeated"), "x1": fa.get("xMinus1"),
            "victoires_tournoi": fa.get("eventWins"), "sur_representation": fa.get("overrep"),
            "dispositions": fa.get("dispositions") or {},
            "combinaisons": fa.get("detachmentCombinations") or [],
            "adversaires": fa.get("matchups") or [],
            "listes_recentes": lst, "listes_total_site": rl.get("totalCount"),
        }
        for l in lst:
            if l["startDate"] and debut.isoformat() <= l["startDate"] <= fin.isoformat():
                listes.append({"faction": nom, **l})
        print(f"  {nom} : {len(fa.get('detachmentCombinations') or [])} combinaisons, {len(lst)} listes récentes",
              file=sys.stderr)

    dossier = RACINE / "data" / semaine
    (dossier / "factions").mkdir(parents=True, exist_ok=True)
    (dossier / "stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=1))
    for slug, d in pages.items():
        (dossier / "factions" / f"{slug}.json").write_text(json.dumps(d, ensure_ascii=False, indent=1))
    with open(dossier / "lists.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(listes[0].keys()) if listes else ["faction"])
        w.writeheader()
        w.writerows(listes)
    print(semaine)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ÉCHEC DU RELEVÉ : {e}", file=sys.stderr)
        sys.exit(1)
