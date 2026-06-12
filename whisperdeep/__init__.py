"""Whisperdeep — a roguelike with a living dungeon master.

This package contains the playable core of the game.

Sprint 1 (Foundation & Grid World) established the project scaffold:
- A `whisperdeep` Python package runnable as `python -m whisperdeep`.
- A clean tile/floor/entity/game/render module split.
- Tiles with kind+glyph+walkable, a bounds-checked Floor grid, an Entity/
  Player layer with the '@' glyph, an ASCII frame renderer, 8-directional
  movement with wall and out-of-bounds collision, a turn counter, and a
  --headless / --seed CLI suitable for snapshot tests.

Sprint 2 (Dungeon Generation v1) layered on:
- A seedable rooms-and-corridors generator with doors and stairs.
- A multi-floor World driven by a single master seed.
"""

__version__ = "0.2.0"
