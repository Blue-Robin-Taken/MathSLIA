import json
import re
import time
from datetime import datetime
from urllib.parse import urlparse

from chessdotcom import ChessDotComClient, RateLimitHandler


# ========= CONFIG =========

# Rough target of how many distinct players to sample
TARGET_PLAYERS = 1000

# How many recent months of archives to pull per player
MAX_MONTHS_PER_PLAYER = 3

# Only consider these time classes
TIME_CLASS_FILTER = {"bullet", "blitz", "rapid"}  # set to None to accept all

# Some large countries to sample "normal" users from
COUNTRIES = ["US", "IN", "RU", "DE", "BR", "ES"]

# Output JSON path
OUTPUT_FILE = "chess_openings_games.json"

# Rating buckets (per game, based on that game’s rating)
LOW_MAX = 1399
MID_MAX = 1999
# >= MID_MAX+1 will be "high"


# ========= CLIENT SETUP =========

client = ChessDotComClient(
    user_agent=(
        "MyMathSL-IA/0.1"
        "(contact: julianjohnt@gmail.com)"  # TODO: put a real contact here
    ),
    rate_limit_handler=RateLimitHandler(tts=2.0, retries=3),
)


# ========= HELPERS =========

def rating_bucket(rating: int | None) -> str | None:
    if rating is None:
        return None
    if rating <= LOW_MAX:
        return "low"
    if rating <= MID_MAX:
        return "mid"
    return "high"


def extract_username_from_player_url(url: str) -> str:
    """
    country_players gives URLs like: https://api.chess.com/pub/player/<username>
    Grab the last path segment.
    """
    path = urlparse(url).path.rstrip("/")
    return path.split("/")[-1]


def parse_tag(pgn: str, tag_name: str) -> str | None:
    """
    Quick-and-dirty PGN tag parser: looks for lines like:
      [Opening "King's Pawn Game"]
    and returns the value without quotes.
    """
    pattern = rf'^\[{re.escape(tag_name)}\s+"([^"]+)"\]'
    m = re.search(pattern, pgn, flags=re.MULTILINE)
    return m.group(1) if m else None


def parse_opening_from_pgn(pgn: str) -> dict:
    """
    Pull ECO code, opening name, and variation from the PGN headers.
    """
    eco_code = parse_tag(pgn, "ECO")
    opening_name = parse_tag(pgn, "Opening")
    variation = parse_tag(pgn, "Variation")

    if opening_name and variation:
        full_name = f"{opening_name}: {variation}"
    else:
        full_name = opening_name or None

    return {
        "eco_code": eco_code,
        "opening_name": opening_name,
        "opening_full": full_name,
        "variation": variation,
    }


def eco_group_from_code(eco_code: str | None) -> str | None:
    """
    Very coarse grouping using ECO first letter.
    You can refine this later in your own processing.
    """
    if not eco_code:
        return None
    letter = eco_code[0].upper()
    if letter == "A":
        return "flank_and_irregular"
    if letter == "B":
        return "semi_open_e4"
    if letter == "C":
        return "open_games_and_french"
    if letter == "D":
        return "closed_queens_pawn_and_grunfeld"
    if letter == "E":
        return "indian_defences"
    return None


# ========= USERNAME COLLECTION =========

def collect_leaderboard_usernames() -> list[str]:
    """
    Grab high-level players from live_rapid, live_blitz, live_bullet
    leaderboards (top-50 each).
    """
    usernames: list[str] = []
    try:
        resp = client.get_leaderboards()
        lb = resp.leaderboards
    except Exception as e:
        print(f"Error fetching leaderboards: {e}")
        return []

    for attr in ("live_rapid", "live_blitz", "live_bullet"):
        entries = getattr(lb, attr, []) or []
        for entry in entries:
            if entry.username:
                usernames.append(entry.username)

    return usernames


def collect_country_usernames() -> list[str]:
    """
    Grab a bunch of usernames from several country lists.
    """
    usernames: list[str] = []

    for iso in COUNTRIES:
        print(f"Fetching country players for {iso}...")
        try:
            resp = client.get_country_players(iso)
            # resp.players is a list of URLs
            player_urls = resp.players or []
        except Exception as e:
            print(f"  Error fetching country players for {iso}: {e}")
            continue

        for url in player_urls:
            usernames.append(extract_username_from_player_url(url))

        time.sleep(0.5)

    return usernames


def collect_usernames(target: int) -> list[str]:
    """
    Combine leaderboards (high-level) and country players (mixed),
    then dedupe and truncate to target.
    """
    raw_usernames: list[str] = []

    print("Collecting usernames from leaderboards...")
    raw_usernames.extend(collect_leaderboard_usernames())

    print("Collecting usernames from country players...")
    raw_usernames.extend(collect_country_usernames())

    # Dedupe while preserving order
    seen = set()
    deduped: list[str] = []
    for u in raw_usernames:
        u_norm = u.strip()
        if not u_norm or u_norm in seen:
            continue
        seen.add(u_norm)
        deduped.append(u_norm)

    print(f"Collected {len(deduped)} unique usernames before truncation.")
    return deduped[:target]


# ========= GAME COLLECTION =========

def get_recent_archive_urls(username: str, max_months: int) -> list[tuple[int, int]]:
    """
    Use the monthly archives list, then return the last `max_months`
    as (year, month) tuples.
    """
    try:
        resp = client.get_player_game_archives(username)
        archives = resp.archives or []
    except Exception as e:
        print(f"    Error fetching archives for {username}: {e}")
        return []

    if not archives:
        return []

    # Keep last max_months URLs (most recent)
    urls = archives[-max_months:]

    year_months: list[tuple[int, int]] = []
    for url in urls:
        path = urlparse(url).path.rstrip("/")
        parts = path.split("/")
        try:
            year = int(parts[-2])
            month = int(parts[-1])
            year_months.append((year, month))
        except (ValueError, IndexError):
            continue

    return year_months


def collect_games_for_player(username: str) -> list[dict]:
    """
    Fetch some recent games for a single player and return
    a list of game records (one per game *for that player*).
    """
    records: list[dict] = []
    ym_list = get_recent_archive_urls(username, MAX_MONTHS_PER_PLAYER)
    if not ym_list:
        return records

    for year, month in ym_list:
        try:
            resp = client.get_player_games_by_month(username=username,
                                                    year=year,
                                                    month=month)
            games = resp.games or []
        except Exception as e:
            print(f"    Error fetching games {year}-{month:02d} for {username}: {e}")
            continue

        for g in games:
            # Filter by time class if requested
            if TIME_CLASS_FILTER is not None:
                if g.time_class is None or g.time_class.lower() not in TIME_CLASS_FILTER:
                    continue

            # Find which side is `username`
            game_user = None
            color = None
            rating = None

            if g.white and g.white.username and g.white.username.lower() == username.lower():
                game_user = g.white
                color = "white"
            elif g.black and g.black.username and g.black.username.lower() == username.lower():
                game_user = g.black
                color = "black"

            if not game_user:
                continue

            rating = game_user.rating
            if rating is None:
                continue

            opening_info = parse_opening_from_pgn(g.pgn or "")

            record = {
                "username": username,
                "color": color,
                "rating": rating,
                "rating_bucket": rating_bucket(rating),
                "time_class": (g.time_class or "").lower() if g.time_class else None,
                "rules": g.rules,
                "eco_code": opening_info["eco_code"],
                "opening_name": opening_info["opening_name"],
                "opening_full": opening_info["opening_full"],
                "opening_variation": opening_info["variation"],
                "eco_group": eco_group_from_code(opening_info["eco_code"]),
                "game_url": g.url,
                "end_time": g.end_time,
            }

            records.append(record)

    return records


# ========= MAIN =========

def main():
    start = time.time()
    print(f"Target players: {TARGET_PLAYERS}")

    usernames = collect_usernames(TARGET_PLAYERS)
    print(f"Using {len(usernames)} usernames.")

    all_game_records: list[dict] = []
    players_with_games = 0

    for idx, username in enumerate(usernames, start=1):
        print(f"[{idx}/{len(usernames)}] {username}...")
        games = collect_games_for_player(username)
        if games:
            players_with_games += 1
            all_game_records.extend(games)
            print(f"    -> {len(games)} games recorded.")
        else:
            print("    -> no usable games found.")

    elapsed = time.time() - start

    # Simple meta section
    meta = {
        "generated_at_utc": datetime.utcnow().isoformat() + "Z",
        "target_players": TARGET_PLAYERS,
        "players_attempted": len(usernames),
        "players_with_games": players_with_games,
        "total_games": len(all_game_records),
        "max_months_per_player": MAX_MONTHS_PER_PLAYER,
        "time_class_filter": sorted(TIME_CLASS_FILTER) if TIME_CLASS_FILTER else None,
        "rating_buckets": {
            "low_max": LOW_MAX,
            "mid_max": MID_MAX,
        },
        "countries_sampled": COUNTRIES,
        "elapsed_seconds": elapsed,
    }

    output = {
        "meta": meta,
        "games": all_game_records,
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, sort_keys=False)

    print()
    print(f"Done. Wrote {len(all_game_records)} game records "
          f"from {players_with_games} players to {OUTPUT_FILE}.")
    print(f"Elapsed: {elapsed:.1f}s")


if __name__ == "__main__":
    main()
