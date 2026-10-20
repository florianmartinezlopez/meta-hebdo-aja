"""Calculs et génération de la page à partir de data/<semaine>/.

Usage : python scripts/construire.py 2026-W42 [--url https://...]
Écrit docs/index.html, docs/archives/<semaine>.html, docs/archives/index.html,
data/<semaine>/resume.json et data/<semaine>/discord.txt.
Tous les chiffres viennent des fichiers du relevé ; les phrases sont des gabarits remplis par ces chiffres.
"""
import argparse
import csv
import datetime as dt
import html
import json
import pathlib
import re
import sys
from collections import Counter, defaultdict
from zoneinfo import ZoneInfo

RACINE = pathlib.Path(__file__).resolve().parent.parent
LH = "https://listhammer.info"
URL_DEFAUT = "https://florianmartinezlopez.github.io/meta-hebdo-aja/"

FD = {  # clé courte, nom, variable CSS
    "Take and Hold": ("th", "var(--d-th)"),
    "Purge the Foe": ("ptf", "var(--d-ptf)"),
    "Priority Assets": ("pa", "var(--d-pa)"),
    "Reconnaissance": ("rec", "var(--d-rec)"),
    "Disruption": ("dis", "var(--d-dis)"),
}
FD_ORDRE = ["Reconnaissance", "Purge the Foe", "Take and Hold", "Priority Assets", "Disruption"]
MOIS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]
JOURS = ["lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim."]
MIN_PARTIES_CLASSEMENT = 100
MIN_PARTIES_WR = 10          # Listhammer n'affiche pas de win rate en dessous
MIN_PARTIES_COMBO_TOP = 20   # tableau « meilleures combinaisons »
MIN_JOUEURS_LISTES = 30     # listes, tops et archétypes : GT de 30 joueurs et plus
MIN_PARTIES_MATCHUP = 10    # matchups affichés dans les cartes d'armée
NBSP, NNBSP = " ", " "
LETTRES = {2: "deux", 3: "trois", 4: "quatre", 5: "cinq", 6: "six", 7: "sept", 8: "huit"}

e = html.escape


# ---------- formats ----------
def fr(v, dec=1):
    return f"{v:.{dec}f}".replace(".", ",")


def pct(v):
    return "n.d." if v is None else f"{fr(v)}{NBSP}%"


def nb(n):
    return f"{n:,}".replace(",", NNBSP)


def wr_of(d):
    """Win rate d'un objet Listhammer, None sous le seuil d'affichage."""
    if not d or (d.get("total") or 0) < MIN_PARTIES_WR or d.get("winRate") in (None, ""):
        return None
    return float(d["winRate"])


def combo(s):
    return " + ".join(sorted(p.strip() for p in (s or "").split("|") if p.strip()))


def bilan(l):
    w, lo, d = int(l["wins"]), int(l["losses"]), int(l.get("draws") or 0)
    return f"{w}-{lo}" + (f"-{d}" if d else "")


def cle_tri(l):
    return (-int(l["wins"]), int(l["losses"]), -int(l.get("numberOfPlayers") or 0))


def nom_tournoi(n):
    return re.sub(r"\s+", " ", (n or "").replace(" - ", ", ")).strip()


# ---------- fragments HTML ----------
def fd_tag(dispo):
    if dispo not in FD:
        return ""
    return f'<span class="fd" style="background:{FD[dispo][1]}">{e(dispo)}</span>'


def wr_bar(v, couleur=None):
    if v is None:
        return '<span class="na">n.d.</span>'
    lo, hi = 25, 75  # échelle centrée : le trait du milieu (CSS left:50%) tombe sur 50 %
    x = max(lo, min(hi, v))
    mid, pos = (50 - lo) / (hi - lo) * 100, (x - lo) / (hi - lo) * 100
    left, w = min(mid, pos), max(abs(pos - mid), 1)
    c = couleur or ("var(--good)" if v >= 50 else "var(--bad)")
    return (f'<span class="wrbar"><span class="num">{pct(v)}</span><span class="track">'
            f'<span class="fill" style="left:{left:.1f}%;width:{w:.1f}%;background:{c}"></span></span></span>')


def delta(v, avant, court=False):
    """Écart en points avec la semaine précédente ; rien si l'une des deux valeurs manque."""
    if v is None or avant is None:
        return ""
    d = v - avant
    if abs(d) < 0.05:
        return '<span class="dl eq">=</span>' if court else '<span class="dl eq">= stable</span>'
    signe, cls = ("▲ +", "up") if d > 0 else ("▼ −", "down")
    return f'<span class="dl {cls}">{signe}{fr(abs(d))}{"" if court else NBSP + "pt" + ("s" if abs(d) >= 2 else "")}</span>'


def wr_num(v):
    if v is None:
        return '<span class="na">n.d.</span>'
    return f'<span class="num" style="color:{"var(--good)" if v >= 50 else "var(--bad)"}">{pct(v)}</span>'


def joueur(l):
    nom = e(l["playerName"] or "Joueur")
    if l.get("playerUid"):
        return (f'<a href="{LH}/players/{e(l["playerUid"])}" target="_blank" rel="noopener" '
                f'title="Voir la liste sur Listhammer">{nom}{NBSP}↗</a>')
    return nom


def ligne_liste(l, faction=None, montrer_combo=True, montrer_fd=True, gras=False):
    x0 = int(l["losses"]) == 0
    qui = joueur(l)
    if faction:
        style = ' style="font-weight:600;color:var(--ink)"' if gras else ""
        qui += f' <span class="muted" style="font-weight:400">· <span{style}>{e(faction)}</span></span>'
    quoi = (fd_tag(l["disposition"]) if montrer_fd else "")
    quoi += (e(combo(l["detachment"])) + " · " if montrer_combo else "")
    quoi += f'{e(nom_tournoi(l["eventName"]))} ({l["numberOfPlayers"]})'
    return (f'<div class="li"><span class="rec {"x0" if x0 else ""}">{bilan(l)}</span>'
            f'<span class="who">{qui}</span><span class="what">{quoi}</span></div>')


def bloc_matchups(a, prep_set):
    def ligne(m):
        nom = e(m["adv"]) + (' <span class="tagprep">À préparer</span>' if m["adv"] in prep_set else "")
        return (f'<tr><td>{nom}<span class="cell-sub">{m["total"]} parties</span></td>'
                f'<td class="r">{wr_bar(m["wr"])}</td></tr>')

    if not a["durs"]:
        return f'<p class="empty">Aucun adversaire affronté sur {MIN_PARTIES_MATCHUP} parties ou plus ce week-end.</p>'
    durs = [m for m in a["durs"] if m["wr"] < 50]
    faciles = [m for m in a["faciles"] if m["wr"] >= 50]
    out = '<div class="mu">'
    out += ('<div><div class="mu-t bad">Matchups difficiles</div><table><tbody>'
            + ("".join(ligne(m) for m in durs) or '<tr><td class="empty">Aucun sous 50 %.</td></tr>')
            + '</tbody></table></div>')
    out += ('<div><div class="mu-t good">Matchups favorables</div><table><tbody>'
            + ("".join(ligne(m) for m in faciles) or '<tr><td class="empty">Aucun au-dessus de 50 %.</td></tr>')
            + '</tbody></table></div></div>')
    tout = "".join(
        f'<tr><td>{e(m["adv"])}{" <span class=tagprep>À préparer</span>" if m["adv"] in prep_set else ""}</td>'
        f'<td class="r num">{m["total"]}</td>'
        f'<td class="r num hide-m">{"n.d." if m["ecart"] is None or m["total"] < MIN_PARTIES_WR else ("+" if m["ecart"] >= 0 else "−") + fr(abs(m["ecart"]), 0)}</td>'
        f'<td class="r">{wr_bar(m["wr"])}</td></tr>' for m in a["matchups"])
    out += (f'<details class="mu-all"><summary>Tous les adversaires ({len(a["matchups"])})</summary>'
            '<div class="tscroll"><table><thead><tr><th>Adversaire</th><th class="r">Parties</th>'
            '<th class="r hide-m">Écart pts</th><th class="r">Win rate</th></tr></thead><tbody>'
            f'{tout}</tbody></table></div></details>')
    return out


# ---------- chargement ----------
def gros_tournoi(l):
    return int(l.get("numberOfPlayers") or 0) >= MIN_JOUEURS_LISTES


def charger(semaine):
    d = RACINE / "data" / semaine
    stats = json.loads((d / "stats.json").read_text())
    for r in stats["factions"]:  # « Space Marines (Astartes) » -> « Space Marines »
        r["faction"] = re.sub(r"\s*\(.*?\)", "", r["faction"]).strip()
    factions = {}
    for f in sorted((d / "factions").glob("*.json")):
        x = json.loads(f.read_text())
        factions[x["nom"]] = x
    with open(d / "lists.csv") as f:
        listes = [l for l in csv.DictReader(f) if gros_tournoi(l)]
    return stats, factions, listes


def semaine_precedente(semaine):
    """Résumé de la dernière semaine relevée avant celle-ci (pour les évolutions), ou None."""
    avant = sorted(d for d in (RACINE / "data").iterdir()
                   if d.is_dir() and d.name < semaine and (d / "resume.json").exists())
    if not avant:
        return None
    r = json.loads((avant[-1] / "resume.json").read_text())
    return {"semaine": r["semaine"], "aja": r.get("aja", {}),
            "factions": {f: wr for f, wr, *_ in r.get("classement", [])} | r.get("factions", {}),
            "dispositions": r.get("dispositions", {}), "combos": r.get("combos", {})}


def historique(semaine, stats, factions):
    """Listes X-0 / X-1 des 3 semaines précédant la fenêtre : relevés stockés + listes encore visibles sur le site."""
    debut = dt.date.fromisoformat(stats["fenetre"]["debut"])
    borne = (debut - dt.timedelta(days=21)).isoformat()
    vues, out, semaines_stockees = set(), [], []
    for d in sorted((RACINE / "data").iterdir()):
        if not d.is_dir() or d.name >= semaine or not (d / "lists.csv").exists():
            continue
        with open(d / "lists.csv") as f:
            rows = [r for r in csv.DictReader(f)
                    if borne <= (r.get("startDate") or "") < debut.isoformat() and gros_tournoi(r)]
        if rows:
            semaines_stockees.append(d.name)
        for r in rows:
            k = (r.get("playerUid"), r.get("eventUid"))
            if k not in vues:
                vues.add(k)
                out.append(r)
    tronquees = []
    for nom, fa in factions.items():
        lst = fa["listes_recentes"]
        if len(lst) >= 25 and min((l["startDate"] or "9") for l in lst) > borne:
            tronquees.append(nom)
        for l in lst:
            if borne <= (l["startDate"] or "") < debut.isoformat() and gros_tournoi(l):
                k = (l.get("playerUid"), l.get("eventUid"))
                if k not in vues:
                    vues.add(k)
                    out.append({"faction": nom, **l})
    return out, semaines_stockees, sorted(tronquees)


# ---------- analyse ----------
def analyser(semaine, stats, factions, listes, team):
    noms_team = [a["nom"] for a in team["armees"]]
    court = {a["nom"]: a["court"] for a in team["armees"]}
    stat_f = {r["faction"]: r for r in stats["factions"]}
    for r in stats["factions"]:
        r["wr"] = float(r["winRate"]) if r.get("total") else None
        r["over"] = float(r.get("overrep") or 0)

    listes = sorted(listes, key=cle_tri)
    par_faction = defaultdict(list)
    for l in listes:
        par_faction[l["faction"]].append(l)

    # Dispositions
    tot_joueurs = sum(d["players"] for d in stats["dispositions"]) or 1
    disp = {d["disposition"]: d for d in stats["dispositions"]}
    fdstats = []
    for n in FD_ORDRE:
        d = disp.get(n)
        if not d:
            continue
        ls = [l for l in listes if l["disposition"] == n]
        joue = sorted(((f, fa["dispositions"].get(n, 0)) for f, fa in factions.items()), key=lambda x: -x[1])
        mat = [m for m in stats["matrice"] if m["disposition"] == n]
        fdstats.append({
            "nom": n, "wr": float(d["winRate"]), "parties": d["total"], "joueurs": d["players"],
            "field": d["players"] / tot_joueurs * 100, "listes": ls,
            "x0": sum(1 for l in ls if int(l["losses"]) == 0),
            "qui": [x for x in joue if x[1] > 0][:6],
            "matrice": sorted(mat, key=lambda m: FD_ORDRE.index(m["opponentDisposition"])
                              if m["opponentDisposition"] in FD_ORDRE else 9),
        })
    fd_tri = sorted(fdstats, key=lambda x: -x["wr"])

    # Armées AJA
    armees = []
    for a in team["armees"]:
        fa, st = factions.get(a["nom"]), stat_f.get(a["nom"])
        if not fa or not st:
            continue
        combos = sorted(fa["combinaisons"], key=lambda c: -c["players"])
        dets = [(combo(c["detachment"]), c["fieldPercent"], wr_of(c), c["total"]) for c in combos[:5]]
        disp_a = sorted(((k, v) for k, v in fa["dispositions"].items() if v), key=lambda x: -x[1])
        mu = []
        for m in fa.get("adversaires", []):
            adv = re.sub(r"\s*\(.*?\)", "", m["opponentFaction"]).strip()
            if adv != a["nom"]:
                mu.append({"adv": adv, "wr": wr_of(m), "total": m["total"],
                           "ecart": m.get("avgDifferential") if m.get("differentialGames") else None})
        fiables = sorted((m for m in mu if m["total"] >= MIN_PARTIES_MATCHUP and m["wr"] is not None),
                         key=lambda m: m["wr"])
        tops_a = par_faction[a["nom"]]
        armees.append({**a, "st": st, "dets": dets, "disp": disp_a, "listes": tops_a[:3],
                       "x0": sum(1 for l in tops_a if int(l["losses"]) == 0),
                       "x1": sum(1 for l in tops_a if int(l["losses"]) == 1),
                       "durs": fiables[:4], "faciles": fiables[::-1][:4],
                       "matchups": sorted(mu, key=lambda m: -m["total"]),
                       "texte": phrase_armee(a, st, combos, disp_a, par_faction[a["nom"]])})

    # Classement
    classement = sorted((r for r in stats["factions"] if r["total"] >= MIN_PARTIES_CLASSEMENT),
                        key=lambda r: -r["wr"])
    exclues = sorted(r["faction"] for r in stats["factions"] if r["total"] < MIN_PARTIES_CLASSEMENT)
    tops_combos = []
    for f, fa in factions.items():
        for c in fa["combinaisons"]:
            if c["total"] >= MIN_PARTIES_COMBO_TOP:
                tops_combos.append((f, combo(c["detachment"]), c["fieldPercent"], float(c["winRate"]), c["total"]))
    tops_combos.sort(key=lambda x: -x[3])
    tops_combos = tops_combos[:10]

    # À préparer : chance de croiser la faction (part du field) × avance sur 50 %
    tot_field = sum(r["players"] for r in stats["factions"]) or 1
    prep = []
    for r in classement:
        fa = factions.get(r["faction"])
        if not fa or r["wr"] <= 50:
            continue
        part = r["players"] / tot_field * 100
        dfav = max(fa["dispositions"].items(), key=lambda x: x[1])[0] if fa["dispositions"] else None
        cfav = max(fa["combinaisons"], key=lambda c: c["players"]) if fa["combinaisons"] else None
        prep.append({"faction": r["faction"], "part": part, "wr": r["wr"], "joueurs": r["players"],
                     "menace": part * (r["wr"] - 50), "dispo": dfav,
                     "combo": combo(cfav["detachment"]) if cfav else "", "listes": par_faction[r["faction"]][:3]})
    prep = sorted(prep, key=lambda x: -x["menace"])[:6]

    # Archétypes
    hist, semaines_stockees, tronquees = historique(semaine, stats, factions)
    archetypes = detecter_archetypes(listes, hist, factions, noms_team)

    # Synthèse
    prec = semaine_precedente(semaine)
    brief = synthese(armees, fd_tri, classement, archetypes, prep, court, prec)

    # À noter
    notes = []
    if stats["tournois_en_cours"]:
        notes.append(f"Au moment du relevé, {stats['tournois_en_cours']} tournoi"
                     f"{'s' if stats['tournois_en_cours'] > 1 else ''} sur {len(stats['tournois'])} "
                     f"n'étai{'ent' if stats['tournois_en_cours'] > 1 else 't'} pas terminé"
                     f"{'s' if stats['tournois_en_cours'] > 1 else ''} : les win rates bougeront encore.")
    if exclues:
        notes.append(f"Classement limité aux factions avec au moins {MIN_PARTIES_CLASSEMENT} parties : "
                     f"{', '.join(exclues)} en {'sont exclues' if len(exclues) > 1 else 'est exclue'}.")
    if len(semaines_stockees) < 3:
        txt = ("Historique du projet encore court" + (f" ({', '.join(semaines_stockees)})" if semaines_stockees
                                                       else " (première semaine relevée)"))
        txt += " : la détection des archétypes s'appuie aussi sur les listes des semaines précédentes encore visibles sur Listhammer."
        if tronquees:
            txt += (f" Pour {', '.join(tronquees)}, le site n'affiche pas trois semaines complètes de listes : "
                    "la comparaison y est partielle.")
        notes.append(txt)
    notes.append("Le win rate par faction et par force de disposition n'est pas publié par Listhammer, et les pages "
                 "tournoi (appariements) sont interdites à la lecture automatique : ce croisement n'est donc pas affiché.")
    notes.append("Les listes affichées sont les X-0 / X-1 que Listhammer met en avant sur chaque page faction, "
                 f"limitées aux tournois de {MIN_JOUEURS_LISTES} joueurs et plus ({len(listes)} listes ce week-end). "
                 "Les win rates, matchups et colonnes X-0 / X-1 du classement viennent de Listhammer et comptent "
                 "tous les GT (16 joueurs et plus).")
    if prec:
        notes.append(f"Les évolutions (▲ ▼) comparent avec la semaine {int(prec['semaine'].split('W')[1])} "
                     f"({prec['semaine']}), dernière semaine relevée.")
    else:
        notes.append("Première semaine relevée : les évolutions d'une semaine sur l'autre apparaîtront au prochain récap.")
    if not stats["fenetre"].get("lue_sur_le_site"):
        notes.append("Les dates de la fenêtre n'ont pas pu être lues sur le site : elles sont estimées.")

    return {"armees": armees, "fdstats": fdstats, "fd_tri": fd_tri, "classement": classement,
            "exclues": exclues, "tops_combos": tops_combos, "prep": prep, "prec": prec, "archetypes": archetypes,
            "brief": brief, "notes": notes, "listes": listes, "court": court, "noms_team": noms_team}


def phrase_armee(a, st, combos, disp, listes):
    ph = []
    joueurs_total = sum(c["players"] for c in combos) or 1
    if combos:
        c1 = combos[0]
        w1 = wr_of(c1)
        part = c1["fieldPercent"]
        lib = "reste le choix majoritaire" if part >= 40 else "est la combinaison la plus jouée"
        ph.append(f"{combo(c1['detachment'])} {lib} ({fr(part, 0)}{NBSP}% des joueurs"
                  + (f", {pct(w1)} de victoires)." if w1 is not None else ", win rate non affiché).") )
        meilleurs = [c for c in combos[1:] if wr_of(c) is not None and c["total"] >= 15 and (w1 is None or wr_of(c) >= w1 + 5)]
        if meilleurs:
            cb = max(meilleurs, key=wr_of)
            ph.append(f"{combo(cb['detachment'])} fait mieux : {pct(wr_of(cb))} sur {cb['total']} parties.")
    if disp:
        k, v = disp[0]
        share = v / (sum(x for _, x in disp) or 1) * 100
        if share >= 45:
            ph.append(f"{k} domine les choix de disposition ({fr(share, 0)}{NBSP}% des joueurs).")
    if listes:
        l = listes[0]
        ph.append(f"Meilleur résultat : {bilan(l)} en {combo(l['detachment'])} ({l['disposition']}) "
                  f"à {nom_tournoi(l['eventName'])}.")
    else:
        ph.append("Aucune liste X-0 / X-1 relevée ce week-end.")
    return " ".join(ph[:3])


def detecter_archetypes(listes, hist, factions, noms_team):
    def cle(l):
        return (l["faction"], combo(l["detachment"]), l["disposition"])

    now, prev = defaultdict(list), defaultdict(list)
    for l in listes:
        now[cle(l)].append(l)
    for l in hist:
        prev[cle(l)].append(l)

    def infos_combo(f, c):
        for x in factions.get(f, {}).get("combinaisons", []):
            if combo(x["detachment"]) == c:
                return x
        return None

    def suite_recul(f, c):
        ic = infos_combo(f, c)
        if not ic:
            return f" La combinaison n'apparaît plus dans les détachements {f} du week-end."
        return (f" Elle reste jouée par {fr(ic['fieldPercent'], 0)}{NBSP}% des joueurs {f} ce week-end"
                + (f", à {pct(wr_of(ic))} de victoires." if wr_of(ic) is not None else "."))

    cartes = []
    for k, ls in now.items():
        n, p = len(ls), len(prev.get(k, []))
        if not (p < n and p / 3 <= n / 2):
            continue
        f, c, dispo = k
        ls = sorted(ls, key=cle_tri)
        x0 = sum(1 for l in ls if int(l["losses"]) == 0)
        if n >= 2:
            txt = (f"{n} listes X-0 / X-1 ce week-end" + (f", dont {x0} invaincue{'s' if x0 > 1 else ''}" if x0 else "")
                   + f", contre {p if p else 'aucune'} sur les trois semaines précédentes.")
        else:
            l = ls[0]
            txt = (f"Une seule liste dans les tops ({bilan(l)} à {nom_tournoi(l['eventName'])}, "
                   f"{l['numberOfPlayers']} joueurs), absente des trois semaines précédentes : à confirmer.")
        ic = infos_combo(f, c)
        wr_c = wr_of(ic)
        if wr_c is not None:
            txt += (f" Sur le week-end, la combinaison réunit {fr(ic['fieldPercent'], 0)}{NBSP}% des joueurs {f} "
                    f"pour {pct(wr_c)} de victoires.")
        # Un « signal fort » demande plusieurs tops ET une combinaison qui gagne globalement
        fort = n >= 2 and (wr_c is None or wr_c >= 50)
        if n >= 2 and not fort:
            txt += " De bons résultats isolés, mais la combinaison perd plus qu'elle ne gagne : à confirmer."
        cartes.append({"sig": "strong" if fort else "watch", "faction": f, "team": f in noms_team,
                       "arch": f"{c}, {dispo}", "combo": c, "dispo": dispo, "texte": txt, "listes": ls[:3],
                       "n": n, "score": (int(ls[0]["wins"]), -int(ls[0]["losses"]), int(ls[0]["numberOfPlayers"] or 0))})
    reculs = []
    for k, ls in prev.items():
        if len(ls) >= 3 and k not in now:
            f, c, dispo = k
            ls = sorted(ls, key=cle_tri)
            reculs.append({"sig": "down", "faction": f, "team": f in noms_team, "arch": f"{c}, {dispo}",
                           "combo": c, "dispo": dispo, "listes": ls[:3], "n": len(ls), "score": (0, 0, 0),
                           "texte": f"{len(ls)} listes X-0 / X-1 sur les trois semaines précédentes, "
                                    f"aucune ce week-end." + suite_recul(f, c)})

    def rang(x):
        return (-x["n"], tuple(-v for v in x["score"]))

    forts = sorted([x for x in cartes if x["sig"] == "strong"], key=lambda x: (not x["team"], *rang(x)))
    veille = sorted([x for x in cartes if x["sig"] == "watch"], key=lambda x: (not x["team"], *rang(x)))
    reculs = sorted(reculs, key=lambda x: (not x["team"], -x["n"]))
    choix = forts[:4]
    choix += veille[:max(0, 5 - len(choix))]
    choix += reculs[:max(1 if reculs else 0, 4 - len(choix))][:max(0, 6 - len(choix))]
    return choix[:6]


def liste_fr(xs):
    return xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " et " + xs[-1]


def emergents(archetypes, court, n):
    """Archétypes en hausse regroupés par faction et combinaison (une même combinaison peut monter
    dans plusieurs dispositions) : « AdMech en X (Take and Hold, Purge the Foe) »."""
    groupes = {}
    for x in archetypes:
        if x["sig"] != "down":
            groupes.setdefault((x["faction"], x["combo"]), []).append(x["dispo"])
    return [f"{court.get(f, f)} en {c} ({', '.join(d)})" for (f, c), d in list(groupes.items())[:n]]


def synthese(armees, fd_tri, classement, archetypes, prep, court, prec):
    """Chaque encart est une liste de puces."""
    hauts = [court[a["nom"]] for a in armees if a["st"]["wr"] is not None and a["st"]["wr"] >= 52]
    milieu = [court[a["nom"]] for a in armees if a["st"]["wr"] is not None and 50 <= a["st"]["wr"] < 52]
    bas = [court[a["nom"]] for a in armees if a["st"]["wr"] is not None and a["st"]["wr"] < 50]
    aja = []
    if hauts:
        aja.append(f"{liste_fr(hauts)} au-dessus de 52{NBSP}%")
    if milieu:
        aja.append(f"{liste_fr(milieu)} à l'équilibre")
    if bas:
        aja.append(f"{liste_fr(bas)} sous 50{NBSP}%")
    if prec:
        evol = [(court[a["nom"]], a["st"]["wr"] - prec["aja"][a["nom"]]) for a in armees
                if a["st"]["wr"] is not None and prec["aja"].get(a["nom"]) is not None]
        if evol:
            nom, d = max(evol, key=lambda x: abs(x[1]))
            if abs(d) >= 1:
                aja.append(f"Plus forte évolution : {nom} ({'+' if d > 0 else '−'}{fr(abs(d))}{NBSP}pts "
                           f"depuis la semaine {int(prec['semaine'].split('W')[1])})")

    pr = [f"{x['faction']} : {pct(x['wr'])}, {fr(x['part'], 0)}{NBSP}% du field" for x in prep[:3]] \
        or [f"Aucune faction au-dessus de 50{NBSP}% ce week-end"]

    b, w = fd_tri[0], fd_tri[-1]
    dispo = [f"{b['nom']} mène à {pct(b['wr'])} sur {nb(b['parties'])} parties",
             f"{w['nom']} ferme la marche à {pct(w['wr'])}"]

    meta = []
    if len(classement) >= 2:
        a1, a2 = classement[0], classement[1]
        meta.append(f"{a1['faction']} ({pct(a1['wr'])}) et {a2['faction']} ({pct(a2['wr'])}) en tête du classement")
        inv = max(classement, key=lambda r: r.get("undefeated") or 0)
        if (inv.get("undefeated") or 0) >= 2:
            meta.append(f"{inv['faction']} compte {inv['undefeated']} listes invaincues")
    em = emergents(archetypes, court, 3) or ["Pas d'archétype nouveau qui se détache ce week-end"]
    couleur_aja = armees[0]["couleur_var"] if armees else "var(--accent)"
    return [("AJA", couleur_aja, aja), ("À préparer", "var(--bad)", pr), ("Disposition", FD[b["nom"]][1], dispo), ("Meta", "var(--accent)", meta),
                     ("Émergent", "var(--good)", em)]


# ---------- rendu ----------
def rendre(semaine, stats, an, team, url, archives):
    tz = ZoneInfo("Europe/Paris")
    deb = dt.date.fromisoformat(stats["fenetre"]["debut"])
    fin = dt.date.fromisoformat(stats["fenetre"]["fin"])
    rel = dt.datetime.fromisoformat(stats["releve_le"]).astimezone(tz)
    num = int(semaine.split("W")[1])
    dates = (f"{deb.day} au {fin.day} {MOIS[fin.month - 1]} {fin.year}" if deb.month == fin.month
             else f"{deb.day} {MOIS[deb.month - 1]} au {fin.day} {MOIS[fin.month - 1]} {fin.year}")
    releve = f"{JOURS[rel.weekday()]} {rel.day} {MOIS[rel.month - 1]}, {rel.hour}h{rel.minute:02d}".replace("h00", "h")
    n_t = len(stats["tournois"])
    n_j = sum(t.get("players") or 0 for t in stats["tournois"])
    team_set = set(an["noms_team"])
    prep_set = {x["faction"] for x in an["prep"]}
    prec = an["prec"]
    H = []

    H.append(f"""<header class="top">
  <div class="stamp">
    <span class="eyebrow">Semaine {num} · <b>{dates}</b></span>
    <span class="eyebrow">Relevé le <b>{releve}</b></span>
  </div>
  <h1>Meta Hebdo 40K</h1>
  <p class="muted" style="max-width:66ch">Le point du lundi pour l'AJA : performances de nos {LETTRES.get(len(an['armees']), len(an['armees']))} armées, des forces de disposition et des factions, archétypes émergents.</p>
  <div class="coverage">
    <span class="chip">{n_t} tournois</span>
    <span class="chip">{nb(n_j)} joueurs</span>
    <span class="chip">GT 16+ joueurs, 5+ rondes</span>
    <span class="chip">Listes : GT {MIN_JOUEURS_LISTES}+ joueurs</span>
    {f'<span class="chip warn">{stats["tournois_en_cours"]} tournoi{"s" if stats["tournois_en_cours"] > 1 else ""} encore en cours</span>' if stats["tournois_en_cours"] else '<span class="chip">Tous les tournois terminés</span>'}
  </div>
</header>
<div id="navsentinel" aria-hidden="true"></div>
<nav class="sec" id="nav" aria-label="Sections">
  <div class="bar">
    <button type="button" id="burger" aria-expanded="false" aria-controls="navlinks" aria-label="Ouvrir le menu">
      <svg width="20" height="20" viewBox="0 0 20 20" aria-hidden="true"><path d="M3 5h14M3 10h14M3 15h14" stroke="currentColor" stroke-width="2" stroke-linecap="round" fill="none"/></svg>
    </button>
    <span class="cur" id="cur">Synthèse</span>
    <span class="eyebrow wk">S{num}</span>
  </div>
  <div class="links" id="navlinks">
    <a href="#bref">Synthèse</a><a href="#armees">Nos armées</a><a href="#prep">À préparer</a><a href="#fd">Forces de disposition</a><a href="#perf">Factions</a><a href="#emerge">Archétypes</a>
  </div>
</nav>""")

    # 01 Synthèse
    H.append('<section id="bref"><div class="sec-head"><span class="eyebrow">01 · Synthèse</span>'
             '<h2>Synthèse de la semaine</h2></div><div class="brief">')
    for k, c, pts in an["brief"]:
        H.append(f'<div class="take"><span class="k" style="color:{c}">{e(k)}</span><ul>'
                 + "".join(f"<li>{e(t)}</li>" for t in pts) + "</ul></div>")
    H.append("</div></section>")

    # 02 Nos armées
    H.append('<section id="armees"><div class="sec-head"><span class="eyebrow">02 · Nos armées</span>'
             '<h2>Détachements et forces de disposition</h2><p>Pour chaque armée : win rate du week-end, détachements '
             'joués (part des joueurs et win rate), répartition des forces de disposition, et les meilleures listes. '
             'Le site n\'affiche pas de win rate de détachement sous 10 parties : ces lignes sont marquées n.d. '
             f'Matchups : win rate contre chaque armée adverse, seulement au-delà de {MIN_PARTIES_MATCHUP} parties '
             'pour les difficiles et favorables.</p></div>'
             '<div class="armies">')
    for a in an["armees"]:
        st = a["st"]
        tot = sum(v for _, v in a["disp"]) or 1
        bar = "".join(f'<span style="width:{v / tot * 100:.1f}%;background:{FD[k][1]}" title="{e(k)} : {v} joueurs">'
                      f'{str(round(v / tot * 100)) + "%" if v / tot * 100 >= 9 else ""}</span>'
                      for k, v in a["disp"] if k in FD)
        leg = "".join(f'<span><i style="background:{FD[k][1]}"></i>{e(k)} {v}</span>' for k, v in a["disp"] if k in FD)
        det = "".join(f'<tr><td class="det">{e(n)}</td><td class="r num">{fr(f)}{NBSP}%</td><td class="r">{wr_bar(w)}</td></tr>'
                      for n, f, w, _ in a["dets"])
        ls = "".join(ligne_liste(l) for l in a["listes"]) or '<p class="empty">Aucune liste X-0 / X-1 ce week-end.</p>'
        H.append(f"""<article class="army" style="--fc:{a['couleur_var']}">
  <div class="army-h"><h3><a href="{LH}/factions/{a['slug']}" target="_blank" rel="noopener">{e(a['nom'])}</a></h3>
    <div class="kpis">
      <div class="kpi"><span class="v" style="color:{'var(--good)' if (st['wr'] or 0) >= 50 else 'var(--bad)'}">{pct(st['wr'])}</span><span class="l">Win rate {delta(st['wr'], prec['aja'].get(a['nom']) if prec else None, court=True)}</span></div>
      <div class="kpi"><span class="v">{nb(st['total'])}</span><span class="l">Parties</span></div>
      <div class="kpi"><span class="v">{st['players']}</span><span class="l">Joueurs</span></div>
      <div class="kpi"><span class="v">{a['x0']} / {a['x1']}</span><span class="l">X-0 / X-1</span></div>
    </div></div>
  <p class="read">{e(a['texte'])}</p>
  <div class="army-body"><div class="col">
  <div><div class="sub">Détachements</div><div class="tscroll"><table><thead><tr><th>Combinaison</th><th class="r">Part</th><th class="r">Win rate</th></tr></thead><tbody>{det}</tbody></table></div></div>
  <div><div class="sub">Forces de disposition ({sum(v for _, v in a['disp'])} joueurs)</div><div class="fdbar">{bar}</div><div class="legend">{leg}</div></div>
  <div><div class="sub">Meilleures listes du week-end</div><div class="lists">{ls}</div></div>
  </div><div class="col">
  <div><div class="sub">Contre les autres armées</div>{bloc_matchups(a, prep_set)}</div>
  </div></div>
</article>""")
    H.append("</div></section>")

    # 03 À préparer
    H.append('<section id="prep"><div class="sec-head"><span class="eyebrow">03 · À préparer</span>'
             '<h2>Les adversaires à préparer</h2><p>Les factions qu\'on a le plus de chances de croiser parmi celles qui '
             'gagnent : classement par part du field multipliée par l\'avance sur 50 %. Une faction très jouée à 54 % '
             'pèse plus qu\'une faction rare à 57 %. Avec leur disposition et leur détachement favoris, à tester en '
             'priorité à l\'entraînement. Déplie chaque faction pour voir ses meilleures listes du week-end.</p></div>'
             '<div class="tscroll"><table><thead><tr><th>Faction et favoris</th>'
             '<th class="r">Field</th><th class="r">Win rate</th></tr></thead><tbody>')
    for x in an["prep"]:
        H.append(f'<tr class="{"rowteam" if x["faction"] in team_set else ""}"><td><strong>{e(x["faction"])}</strong>'
                 f'{"<span class=teamtag>AJA</span>" if x["faction"] in team_set else ""}'
                 f'<span class="cell-sub">{fd_tag(x["dispo"])}{e(x["combo"])}</span></td>'
                 f'<td class="r num">{fr(x["part"])}{NBSP}%<span class="cell-sub">{x["joueurs"]} j.</span></td>'
                 f'<td class="r">{wr_bar(x["wr"])}{delta(x["wr"], prec["factions"].get(x["faction"]) if prec else None)}</td></tr>')
        ls = "".join(ligne_liste(l) for l in x["listes"])
        H.append(f'<tr class="prep-ls"><td colspan="3"><details><summary>Top {len(x["listes"])} des listes '
                 f'{e(x["faction"])}</summary><div class="lists">{ls}</div></details></td></tr>' if ls else
                 f'<tr class="prep-ls"><td colspan="3"><span class="empty">Aucune liste X-0 / X-1 en GT '
                 f'{MIN_JOUEURS_LISTES}+ ce week-end.</span></td></tr>')
    if not an["prep"]:
        H.append('<tr><td colspan="3" class="empty">Aucune faction au-dessus de 50 % ce week-end.</td></tr>')
    H.append("</tbody></table></div></section>")

    # 04 Dispositions
    H.append('<section id="fd"><div class="sec-head"><span class="eyebrow">04 · Forces de disposition</span>'
             '<h2>Performances par force de disposition</h2><p>Win rate global de chaque disposition, les armées qui '
             'la jouent le plus (nombre de joueurs, 28 factions), les meilleurs résultats du week-end toutes factions '
             'confondues, et son win rate contre chacune des autres dispositions. Les armées AJA sont en gras.</p></div>'
             '<div class="fd-grid">')
    for d in an["fdstats"]:
        mx = d["qui"][0][1] if d["qui"] else 1
        qui = "".join(f'<div class="wp"><span class="{"team" if f in team_set else ""}">{e(f)}</span>'
                      f'<span class="b" style="width:{n / mx * 100:.0f}%"></span><span class="num r">{n}</span></div>'
                      for f, n in d["qui"])
        best = "".join(ligne_liste(l, faction=l["faction"], montrer_fd=False, gras=l["faction"] in team_set)
                       for l in d["listes"][:6]) or '<p class="empty">Aucune liste X-0 / X-1 ce week-end.</p>'
        mat = "".join(f'<tr><td>{fd_tag(m["opponentDisposition"])}</td><td class="r">{wr_num(wr_of(m))}</td>'
                      f'<td class="r num">{m["total"]}</td></tr>' for m in d["matrice"])
        nl = len(d["listes"])
        H.append(f"""<article class="fdcard" style="--dc:{FD[d['nom']][1]}">
  <div class="fdcard-h"><h3>{e(d['nom'])}</h3><span class="wr" style="color:{'var(--good)' if d['wr'] >= 50 else 'var(--bad)'}">{pct(d['wr'])}</span></div>
  {f'<p style="margin-top:-8px">{delta(d["wr"], prec["dispositions"].get(d["nom"]))}</p>' if prec and prec["dispositions"].get(d["nom"]) is not None else ''}
  <p class="muted" style="font-size:.82rem">{nb(d['parties'])} parties · {fr(d['field'])}{NBSP}% du field · {nl} liste{'s' if nl > 1 else ''} X-0 / X-1 dont {d['x0']} invaincue{'s' if d['x0'] > 1 else ''}</p>
  <div><div class="sub">Qui la joue (joueurs)</div><div class="who-plays">{qui}</div></div>
  <div><div class="sub">Meilleurs résultats{f' (6 sur {nl})' if nl > 6 else ''}</div><div class="lists">{best}</div></div>
  {f'<div><div class="sub">Contre les autres dispositions</div><table class="matrix"><thead><tr><th>Adversaire</th><th class="r">Win rate</th><th class="r">Parties</th></tr></thead><tbody>{mat}</tbody></table></div>' if mat else ''}
</article>""")
    H.append("</div></section>")

    # 04 Factions
    H.append(f'<section id="perf"><div class="sec-head"><span class="eyebrow">05 · Factions</span>'
             f'<h2>Classement des factions</h2><p>Les {len(an["classement"])} factions avec au moins '
             f'{MIN_PARTIES_CLASSEMENT} parties ce week-end, triées par win rate. Le trait central marque 50{NBSP}%. '
             'La sur-représentation compare la part dans les tops à la part dans le field.</p></div>'
             '<div class="tscroll"><table><thead><tr><th>Faction</th><th class="r">Win rate</th><th class="r">Parties</th>'
             '<th class="r hide-m">Joueurs</th><th class="r hide-m">X-0</th><th class="r hide-m">X-1</th>'
             '<th class="r hide-m">Victoires</th><th class="r">Sur-repr.</th></tr></thead><tbody>')
    slugs = {fa_nom: fa["slug"] for fa_nom, fa in an["_factions"].items()}
    for r in an["classement"]:
        t = r["faction"] in team_set
        ov = r["over"]
        H.append(f'<tr class="{"rowteam" if t else ""}"><td><a href="{LH}/factions/{slugs.get(r["faction"], "")}" '
                 f'target="_blank" rel="noopener">{e(r["faction"])}</a>{"<span class=teamtag>AJA</span>" if t else ""}</td>'
                 f'<td class="r">{wr_bar(r["wr"])}{delta(r["wr"], prec["factions"].get(r["faction"]) if prec else None)}</td>'
                 f'<td class="r num">{nb(r["total"])}</td>'
                 f'<td class="r num hide-m">{r["players"]}</td><td class="r num hide-m">{r["undefeated"]}</td>'
                 f'<td class="r num hide-m">{r["xMinus1"]}</td><td class="r num hide-m">{r["eventWins"]}</td>'
                 f'<td class="r num" style="color:{"var(--good)" if ov >= 1.2 else "var(--bad)" if ov < 0.8 else "inherit"}">'
                 f'{fr(ov, 2)}x</td></tr>')
    H.append(f'</tbody></table></div><h3 style="margin-top:10px">Meilleures combinaisons de détachements</h3>'
             f'<p class="muted" style="font-size:.85rem">Combinaisons jouées sur au moins {MIN_PARTIES_COMBO_TOP} parties ce week-end, triées par win rate.</p>'
             '<div class="tscroll"><table><thead><tr><th>Combinaison</th><th class="r">Part</th><th class="r">Win rate</th></tr></thead><tbody>')
    for f, c, part, w, g in an["tops_combos"]:
        H.append(f'<tr class="{"rowteam" if f in team_set else ""}"><td><strong>{e(f)}</strong>'
                 f'<span class="cell-sub">{e(c)} · {g} parties</span></td><td class="r num">{fr(part)}{NBSP}%</td>'
                 f'<td class="r">{wr_bar(w)}{delta(w, prec["combos"].get(f + " | " + c) if prec else None)}</td></tr>')
    H.append("</tbody></table></div></section>")

    # 05 Archétypes
    H.append('<section id="emerge"><div class="sec-head"><span class="eyebrow">06 · Archétypes</span>'
             '<h2>Archétypes émergents</h2><p>Comparaison des listes X-0 / X-1 de ce week-end avec celles des trois '
             'semaines précédentes (faction, combinaison de détachements et disposition). « Signal fort » quand plusieurs '
             'résultats vont dans le même sens, « à surveiller » sur un résultat isolé, « en recul » pour un archétype '
             'installé qui disparaît des tops.</p></div><div class="emerg">')
    lib = {"strong": "Signal fort", "watch": "À surveiller", "down": "En recul"}
    for x in an["archetypes"]:
        ls = "".join(ligne_liste(l, montrer_combo=False) for l in x["listes"])
        titre = ("Listes des semaines précédentes" if x["sig"] == "down"
                 else "Meilleures listes" if len(x["listes"]) > 1 else "La liste")
        H.append(f'<article class="em"><span class="sig {x["sig"]}">{lib[x["sig"]]}</span>'
                 f'<span class="eyebrow">{e(x["faction"])}{"<span class=teamtag>AJA</span>" if x["team"] else ""}</span>'
                 f'<span class="arch">{e(x["arch"])}</span><p>{e(x["texte"])}</p>'
                 f'<div><div class="sub">{titre}</div><div class="lists">{ls}</div></div></article>')
    if not an["archetypes"]:
        H.append('<p class="empty">Aucun archétype nouveau ou en recul ne se détache cette semaine.</p>')
    H.append("</div></section>")

    H.append('<section><div class="note"><strong>À noter</strong><ul>'
             + "".join(f"<li>{e(n)}</li>" for n in an["notes"]) + "</ul></div></section>")
    arch_lien = "archives/" if not archives else ""
    H.append(f'<footer><span>Source : <a href="{LH}/stats" target="_blank" rel="noopener">listhammer.info</a> '
             '(stats « This Weekend », hors RTT, hors miroirs, 11e édition uniquement).</span>'
             f'<span>Meta Hebdo 40K de l\'AJA · semaine {num} · <a href="{arch_lien or "./"}">Semaines précédentes</a></span>'
             '</footer>')

    clair = "\n".join(f"  --f-{a['slug']}:{a['couleur']};" for a in team["armees"])
    sombre = "\n".join(f"  --f-{a['slug']}:{a['couleur_sombre']};" for a in team["armees"])
    gabarit = (RACINE / "templates/page.html").read_text()
    desc = f"Meta Hebdo 40K de l'AJA, semaine {num} : {n_t} tournois, {nb(n_j)} joueurs."
    return (gabarit.replace("@@COULEURS_CLAIR@@", clair).replace("@@COULEURS_SOMBRE@@", sombre)
            .replace("@@DESCRIPTION@@", e(desc)).replace("@@CONTENU@@", "\n".join(H)))


def page_archives(semaines):
    lignes = "".join(f'<li><a href="{s}.html">Semaine {int(s.split("W")[1])} ({s[:4]})</a></li>' for s in semaines)
    return f"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Archives Meta Hebdo</title>
<style>:root{{--bg:#eef0f3;--ink:#15181e;--muted:#5b6370}}
@media (prefers-color-scheme: dark){{:root{{--bg:#111419;--ink:#e8ebf0;--muted:#98a1ae;color-scheme:dark}}}}
body{{margin:0;background:var(--bg);color:var(--ink);font-family:system-ui,-apple-system,sans-serif;line-height:1.6}}
main{{max-width:640px;margin:0 auto;padding:24px 16px}} a{{color:inherit}} li{{margin:6px 0}}</style></head>
<body><main><h1>Meta Hebdo 40K : archives</h1><p><a href="../">Semaine en cours</a></p><ul>{lignes}</ul></main></body></html>
"""


def message_discord(semaine, stats, an, url):
    num = int(semaine.split("W")[1])
    n_j = sum(t.get("players") or 0 for t in stats["tournois"])
    court = an["court"]
    prec = an["prec"]

    def evol(a):
        v, avant = a["st"]["wr"], (prec["aja"].get(a["nom"]) if prec else None)
        if v is None or avant is None or abs(v - avant) < 0.05:
            return ""
        return f" ({'▲ +' if v > avant else '▼ −'}{fr(abs(v - avant))})"

    aja = " · ".join(f"{court[a['nom']]} {pct(a['st']['wr'])}{evol(a)}"
                     for a in sorted(an["armees"], key=lambda a: -(a["st"]["wr"] or 0)))
    b, w = an["fd_tri"][0], an["fd_tri"][-1]
    em = emergents(an["archetypes"], court, 2)
    lignes = [
        f"Meta Hebdo 40K, semaine {num} ({len(stats['tournois'])} tournois, {nb(n_j)} joueurs)",
        f"AJA : {aja}",
        f"Disposition du moment : {b['nom']} {pct(b['wr'])}, {w['nom']} {pct(w['wr'])}",
    ]
    if an["prep"]:
        lignes.append("À préparer : " + ", ".join(f"{x['faction']} {pct(x['wr'])} ({fr(x['part'], 0)} % du field)"
                                                  for x in an["prep"][:3]))
    if em:
        lignes.append("Émergent : " + ", ".join(em))
    lignes.append(f"Le détail : {url}")
    return "\n".join(lignes).replace(NNBSP, " ").replace(NBSP, " ")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("semaine")
    ap.add_argument("--url", default=URL_DEFAUT)
    args = ap.parse_args()
    team = json.loads((RACINE / "config/team.json").read_text())
    for a in team["armees"]:
        a["couleur_var"] = f"var(--f-{a['slug']})"
    stats, factions, listes = charger(args.semaine)
    if len(factions) < 20:
        raise RuntimeError(f"seulement {len(factions)} factions relevées")
    an = analyser(args.semaine, stats, factions, listes, team)
    an["_factions"] = factions

    docs = RACINE / "docs"
    (docs / "archives").mkdir(parents=True, exist_ok=True)
    (docs / "index.html").write_text(rendre(args.semaine, stats, an, team, args.url, archives=False))
    (docs / "archives" / f"{args.semaine}.html").write_text(
        rendre(args.semaine, stats, an, team, args.url, archives=True))
    semaines = sorted((p.stem for p in (docs / "archives").glob("20*-W*.html")), reverse=True)
    (docs / "archives" / "index.html").write_text(page_archives(semaines))
    if not (docs / ".nojekyll").exists():
        (docs / ".nojekyll").write_text("")

    msg = message_discord(args.semaine, stats, an, args.url)
    d = RACINE / "data" / args.semaine
    (d / "discord.txt").write_text(msg + "\n")
    (d / "resume.json").write_text(json.dumps({
        "semaine": args.semaine,
        "aja": {a["nom"]: a["st"]["wr"] for a in an["armees"]},
        "dispositions": {x["nom"]: x["wr"] for x in an["fdstats"]},
        "classement": [(r["faction"], r["wr"], r["total"]) for r in an["classement"]],
        "factions": {r["faction"]: r["wr"] for r in stats["factions"]},
        "combos": {f"{f} | {combo(c['detachment'])}": wr_of(c) for f, fa in factions.items()
                   for c in fa["combinaisons"] if wr_of(c) is not None},
        "prep": [(x["faction"], round(x["part"], 2), x["wr"]) for x in an["prep"]],
        "archetypes": [{k: x[k] for k in ("sig", "faction", "arch", "n")} for x in an["archetypes"]],
        "brief": {k: pts for k, _, pts in an["brief"]},
    }, ensure_ascii=False, indent=1))
    print(msg)


if __name__ == "__main__":
    try:
        main()
    except Exception as ex:
        print(f"ÉCHEC DE LA GÉNÉRATION : {ex}", file=sys.stderr)
        raise
