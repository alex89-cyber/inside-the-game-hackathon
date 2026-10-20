"""Fictional clubs and rosters.

Every club and player here is invented so the project never uses real
Premier League names, crests or data.
"""

from __future__ import annotations

from .models import Player, Tactics, Team


def _squad(prefix: str, names: list[tuple[str, int, str, float, float, float, float]]) -> tuple[Player, ...]:
    return tuple(
        Player(
            id=f"{prefix}-{number}",
            name=name,
            number=number,
            position=position,
            pace=pace,
            passing=passing,
            finishing=finishing,
            tackling=tackling,
        )
        for name, number, position, pace, passing, finishing, tackling in names
    )


# name, number, position, pace km/h, passing, finishing, tackling
NORTHBRIDGE = Team(
    id="NBR",
    name="Northbridge Rovers",
    short_name="Rovers",
    colors=("#C8102E", "#FFFFFF"),
    formation="4-3-3",
    tactics=Tactics(press_intensity=0.8, tempo=0.75, directness=0.35, width=0.7),
    players=_squad(
        "NBR",
        [
            ("Tomas Kral", 1, "GK", 27.0, 0.62, 0.05, 0.20),
            ("Ade Okafor", 2, "DF", 33.5, 0.70, 0.20, 0.72),
            ("Luca Brandt", 4, "DF", 31.0, 0.74, 0.25, 0.85),
            ("Samir Haddad", 5, "DF", 30.5, 0.71, 0.22, 0.83),
            ("Owen Pryce", 3, "DF", 34.2, 0.73, 0.24, 0.70),
            ("Mateo Ruiz", 6, "MF", 30.8, 0.86, 0.40, 0.76),
            ("Kenji Arata", 8, "MF", 32.1, 0.89, 0.55, 0.58),
            ("Felix Moreau", 10, "MF", 32.8, 0.91, 0.70, 0.45),
            ("Jonah Asante", 7, "FW", 35.6, 0.78, 0.74, 0.30),
            ("Rafael Duarte", 9, "FW", 33.9, 0.72, 0.88, 0.28),
            ("Elias Varga", 11, "FW", 36.1, 0.76, 0.76, 0.27),
        ],
    ),
)

ASHFORD = Team(
    id="ASH",
    name="Ashford Athletic",
    short_name="Athletic",
    colors=("#1D428A", "#FFD100"),
    formation="4-2-3-1",
    tactics=Tactics(press_intensity=0.45, tempo=0.55, directness=0.65, width=0.55),
    players=_squad(
        "ASH",
        [
            ("Henrik Dahl", 1, "GK", 26.5, 0.58, 0.05, 0.22),
            ("Marcus Bell", 2, "DF", 33.0, 0.66, 0.18, 0.74),
            ("Viktor Novak", 5, "DF", 30.2, 0.68, 0.30, 0.88),
            ("Idris Mensah", 6, "DF", 31.4, 0.69, 0.21, 0.84),
            ("Diego Salas", 3, "DF", 33.8, 0.70, 0.23, 0.71),
            ("Callum Reid", 4, "MF", 30.0, 0.80, 0.38, 0.82),
            ("Yusuf Demir", 8, "MF", 31.2, 0.84, 0.48, 0.70),
            ("Noah Lindqvist", 7, "MF", 34.9, 0.79, 0.66, 0.35),
            ("Andre Silva", 10, "MF", 32.5, 0.90, 0.72, 0.40),
            ("Leo Fontaine", 11, "MF", 35.2, 0.77, 0.69, 0.33),
            ("Bruno Costa", 9, "FW", 33.1, 0.70, 0.90, 0.30),
        ],
    ),
)

KESTREL = Team(
    id="KES",
    name="Kestrel City",
    short_name="Kestrel",
    colors=("#6CABDD", "#1C2C5B"),
    formation="4-3-3",
    tactics=Tactics(press_intensity=0.7, tempo=0.85, directness=0.25, width=0.8),
    players=_squad(
        "KES",
        [
            ("Pavel Hruby", 1, "GK", 26.8, 0.75, 0.05, 0.20),
            ("Theo Lambert", 2, "DF", 34.0, 0.78, 0.25, 0.70),
            ("Kofi Boateng", 4, "DF", 32.0, 0.80, 0.28, 0.86),
            ("Erik Holm", 5, "DF", 30.9, 0.79, 0.24, 0.84),
            ("Nico Ferreira", 3, "DF", 34.6, 0.80, 0.30, 0.68),
            ("Arjun Mehta", 6, "MF", 30.5, 0.92, 0.42, 0.78),
            ("Lucas Werner", 8, "MF", 31.8, 0.93, 0.60, 0.55),
            ("Sami Laine", 10, "MF", 32.4, 0.94, 0.75, 0.42),
            ("Ivo Petrov", 7, "FW", 35.9, 0.82, 0.78, 0.28),
            ("Malik Diallo", 9, "FW", 34.2, 0.75, 0.91, 0.26),
            ("Ruben Ortega", 11, "FW", 36.4, 0.81, 0.79, 0.25),
        ],
    ),
)

HARBOURSIDE = Team(
    id="HBS",
    name="Harbourside United",
    short_name="United",
    colors=("#00A650", "#000000"),
    formation="5-3-2",
    tactics=Tactics(press_intensity=0.35, tempo=0.45, directness=0.75, width=0.45),
    players=_squad(
        "HBS",
        [
            ("Gareth Lloyd", 1, "GK", 26.0, 0.55, 0.05, 0.25),
            ("Aaron Kim", 2, "DF", 33.2, 0.64, 0.18, 0.72),
            ("Stefan Ionescu", 4, "DF", 29.8, 0.63, 0.26, 0.87),
            ("Jamal Wright", 5, "DF", 30.6, 0.65, 0.29, 0.89),
            ("Piotr Zielinski", 6, "DF", 30.1, 0.66, 0.22, 0.85),
            ("Liam Doyle", 3, "DF", 33.7, 0.67, 0.20, 0.73),
            ("Omar Farouk", 8, "MF", 31.0, 0.78, 0.45, 0.77),
            ("Daniel Weiss", 10, "MF", 31.6, 0.83, 0.62, 0.52),
            ("Ricardo Neves", 7, "MF", 32.9, 0.76, 0.58, 0.60),
            ("Tobias Engel", 9, "FW", 32.4, 0.68, 0.86, 0.32),
            ("Kwame Owusu", 11, "FW", 35.5, 0.71, 0.80, 0.30),
        ],
    ),
)

TEAMS: dict[str, Team] = {t.id: t for t in (NORTHBRIDGE, ASHFORD, KESTREL, HARBOURSIDE)}
