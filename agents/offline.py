"""Template answers for `OfflineClient`.

They read the exact payload the real model would get, so offline output is
always grounded in the same evidence. English and Spanish are covered;
other languages fall back to English.
"""

from __future__ import annotations

import re
from typing import Any

THEMES = {
    "goal": "finishing",
    "big_chance": "finishing",
    "key_save": "individual_brilliance",
    "momentum_shift": "momentum",
    "pressing_spell": "pressure",
    "control": "control",
    "chaos": "chaos",
    "line_breaker": "individual_brilliance",
    "speed_tag": "individual_brilliance",
    "milestone": "individual_brilliance",
    "card": "discipline",
}

GAME_STATE = {
    "en": {
        "opener": "opens the scoring",
        "equaliser": "levels it",
        "go_ahead": "puts them back in front",
        "extends_lead": "extends the lead",
        "pulls_one_back": "pulls one back",
    },
    "es": {
        "opener": "abre el marcador",
        "equaliser": "empata el partido",
        "go_ahead": "los vuelve a poner adelante",
        "extends_lead": "amplía la ventaja",
        "pulls_one_back": "descuenta",
    },
}


def _pct(v: float | None) -> str:
    return f"{round((v or 0) * 100)}%"


def _explain(p: dict[str, Any]) -> dict[str, Any]:
    m = p["moment"]
    why = m.get("why", {})
    who = m.get("player_name") or p.get("team_name", m["team_id"])
    team = p.get("team_name", m["team_id"])
    kind = m["type"]
    ev: list[dict[str, Any]] = []
    if kind == "goal":
        gs = GAME_STATE["en"].get(why.get("game_state"), "scores")
        headline = f"{who} {gs} for {team}"
        if why.get("against_the_odds"):
            body = f"A shot worth only {why['xg']} xG, a chance that goes in less than one time in ten."
        else:
            body = f"A {why.get('xg')} xG chance struck at {why.get('shot_speed_kmh')} km/h."
        body += f" {team} have now built {why.get('team_xg_so_far')} xG in total."
        ev = [{"label": "xG", "value": why.get("xg")}, {"label": "Shot speed km/h", "value": why.get("shot_speed_kmh")}]
    elif kind == "momentum_shift":
        headline = f"{team} take over the game"
        body = (
            f"{_pct(why.get('field_tilt_last_5'))} of final-third passes in the last five minutes belong to {team}, "
            f"up from {_pct(why.get('field_tilt_before'))}. The territory has flipped."
        )
        ev = [{"label": "Field tilt", "value": _pct(why.get("field_tilt_last_5"))}, {"label": "xG last 5 min", "value": why.get("xg_last_5")}]
    elif kind == "pressing_spell":
        headline = f"{team} turn up the press"
        body = f"{why.get('pressures_last_5')} pressures in five minutes forced {why.get('turnovers_won_last_5')} turnovers."
        ppda = why.get("ppda")
        if ppda is not None and ppda < 8:
            body += f" A PPDA of {ppda} means the opponent barely gets passes off before being closed down."
        elif ppda is not None:
            body += f" Their PPDA of {ppda} shows this is a burst, not their usual approach."
        ev = [{"label": "Pressures (5 min)", "value": why.get("pressures_last_5")}, {"label": "PPDA", "value": why.get("ppda")}]
    elif kind == "control":
        headline = f"{team} put the game to sleep"
        body = f"{why.get('consecutive_passes')} straight completed passes. With {_pct(why.get('possession_share'))} of the ball, they dictate the rhythm."
        ev = [{"label": "Pass chain", "value": why.get("consecutive_passes")}, {"label": "Possession", "value": _pct(why.get("possession_share"))}]
    elif kind == "chaos":
        headline = "The match has lost its shape"
        body = f"The ball is changing hands {why.get('possession_changes_per_min')} times a minute. Nobody is in control, and that favours the team that reacts fastest."
        ev = [{"label": "Turnovers per min", "value": why.get("possession_changes_per_min")}]
    elif kind in ("big_chance", "key_save"):
        xg = why.get("xg", why.get("xg_faced"))
        headline = f"Huge chance for {team}" if kind == "big_chance" else f"Big save from {who}"
        body = f"That chance was worth {xg} xG, roughly a {_pct(xg)} scoring opportunity."
        ev = [{"label": "xG", "value": xg}]
    elif kind == "line_breaker":
        headline = f"{who} splits the lines"
        body = (
            f"A pass rated {why.get('difficulty')} on difficulty, completed with only a "
            f"{_pct(why.get('success_probability'))} chance of success, finds {why.get('receiver_name') or 'a teammate'}."
        )
        ev = [{"label": "Difficulty", "value": why.get("difficulty")}, {"label": "Success chance", "value": _pct(why.get("success_probability"))}]
    elif kind == "speed_tag":
        unit = "shot" if why.get("metric") == "shot_speed_kmh" else "sprint"
        headline = f"{who} hits {why.get('value')} km/h"
        body = f"A {unit} above the {why.get('threshold')} km/h threshold."
        ev = [{"label": "Speed km/h", "value": why.get("value")}]
    elif kind == "milestone":
        headline = f"Milestone for {who}"
        body = f"{why.get('milestone', '').replace('_', ' ')} today."
        ev = [{"label": "Milestone", "value": why.get("milestone")}]
    else:
        headline = f"{(why.get('card') or 'Card').title()} card for {who}"
        body = "A booking that changes how they can defend for the rest of the match."
        ev = [{"label": "Card", "value": why.get("card")}]
    return {"headline": headline, "explanation": body, "evidence": ev, "tactical_theme": THEMES.get(kind, "momentum")}


def _first_sentence(text: str) -> str:
    head = re.split(r"(?<=[.!?])\s+", text.strip(), maxsplit=1)[0]
    return head if head.endswith((".", "!", "?")) else head + "."


def _personalize(p: dict[str, Any]) -> dict[str, Any]:
    ins, prof, m = p["insight"], p["profile"], p["moment"]
    lang = prof.get("language", "en")
    mode = prof.get("mode", "casual")
    title = ins["headline"]
    if lang == "es":
        title = _SPANISH_TITLES.get(m["type"], ins["headline"]).format(who=m.get("player_name") or p.get("team_name", m["team_id"]), team=p.get("team_name", m["team_id"]))
        text = _spanish(m, p.get("team_name", m["team_id"]), mode)
    elif mode == "analyst":
        text = ins["explanation"]
    elif mode == "kids":
        text = _first_sentence(ins["explanation"]).rstrip(".") + "!"
    else:
        text = _first_sentence(ins["explanation"])
    if prof.get("favorite_player") and m.get("player_id") == prof["favorite_player"]:
        text = "⭐ " + text
    return {"title": title, "text": text, "language": lang if lang in ("en", "es") else "en"}


_SPANISH_TITLES = {
    "goal": "¡Gol de {who}!",
    "big_chance": "Ocasión clarísima de {team}",
    "key_save": "Paradón de {who}",
    "momentum_shift": "{team} toma el control",
    "pressing_spell": "{team} presiona arriba",
    "control": "{team} duerme el partido",
    "chaos": "Partido roto",
    "line_breaker": "{who} rompe líneas",
    "speed_tag": "{who} a toda velocidad",
    "milestone": "Hito para {who}",
    "card": "Tarjeta para {who}",
}


def _spanish(m: dict[str, Any], team: str, mode: str) -> str:
    why = m.get("why", {})
    who = m.get("player_name") or team
    kind = m["type"]
    if kind == "goal":
        gs = GAME_STATE["es"].get(why.get("game_state"), "anota")
        t = f"{who} {gs} para {team}."
        return t + (f" Un remate de {why.get('xg')} xG a {why.get('shot_speed_kmh')} km/h." if mode == "analyst" else "")
    if kind == "momentum_shift":
        return f"{team} se adueña del partido: {_pct(why.get('field_tilt_last_5'))} de los pases en el último tercio en cinco minutos."
    if kind == "pressing_spell":
        return f"{team} aprieta arriba: {why.get('pressures_last_5')} presiones y {why.get('turnovers_won_last_5')} recuperaciones en cinco minutos."
    if kind == "control":
        return f"{team} duerme el partido con {why.get('consecutive_passes')} pases seguidos."
    if kind == "chaos":
        return f"Partido roto: el balón cambia de dueño {why.get('possession_changes_per_min')} veces por minuto."
    if kind in ("big_chance", "key_save"):
        xg = why.get("xg", why.get("xg_faced"))
        return f"¡Ocasionón para {team}! Valía {round(xg or 0, 2)} xG." if kind == "big_chance" else f"¡Atajadón de {who}! Evitó una ocasión de {xg} xG."
    if kind == "line_breaker":
        return f"{who} rompe líneas con un pase de dificultad {why.get('difficulty')}."
    if kind == "speed_tag":
        return f"{who} alcanza {why.get('value')} km/h."
    if kind == "milestone":
        return f"Hito para {who}: {why.get('milestone', '').replace('_', ' ')}."
    return f"Tarjeta {('roja' if why.get('card') == 'red' else 'amarilla')} para {who}."


def _narrate(p: dict[str, Any]) -> dict[str, Any]:
    ins, m = p["insight"], p["moment"]
    return {"line": f"{m['minute']}' {ins['headline']}."}


def _recap(p: dict[str, Any]) -> dict[str, Any]:
    s = p["snapshot"]
    h, a = s["home_id"], s["away_id"]
    th, ta = s["teams"][h], s["teams"][a]
    phase = "Half-time" if p.get("phase") == "half_time" else "Full-time"
    title = f"{phase}: {th['name']} {th['goals']}-{ta['goals']} {ta['name']}"
    xg_leader = th if th["xg"] >= ta["xg"] else ta
    summary = (
        f"{th['name']} had {_pct(th['possession'])} of the ball and {th['xg']} xG against {ta['xg']} for {ta['name']}. "
        f"{xg_leader['name']} created the better chances."
    )
    key = [k["headline"] for k in p.get("key_moments", [])][:5]
    potm = p.get("player_of_the_match") or {}
    return {"title": title, "summary": summary, "key_moments": key, "player_of_the_match": potm.get("name")}


def respond(payload: dict[str, Any]) -> dict[str, Any]:
    task = payload.get("task")
    if task == "explain":
        return _explain(payload)
    if task == "personalize":
        return _personalize(payload)
    if task == "narrate":
        return _narrate(payload)
    if task == "recap":
        return _recap(payload)
    raise ValueError(f"offline client has no template for task {task!r}")
