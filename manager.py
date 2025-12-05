"""
Cricket Scoreboard Plugin for LEDMatrix

Displays live, recent, and upcoming Cricket games across multiple leagues including
The Ashes, Sheffield Shield and more.

Features:
- Multiple league support (Ashes, etc.)
- Live game tracking with match time and scores
- Recent game results
- Upcoming game schedules
- Favorite team prioritization
- Background data fetching

API Version: 1.0.0
"""

import logging
import os
import time
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
from pathlib import Path

import pytz
import requests
from PIL import Image, ImageDraw, ImageFont

from src.plugin_system.base_plugin import BasePlugin

logger = logging.getLogger(__name__)


class CricketScoreboardPlugin(BasePlugin):
    """
    Cricket scoreboard plugin for displaying games across multiple leagues.

    Supports various Cricket leagues with live, recent, and upcoming game modes.

    Configuration options:
        leagues: Enable/disable specific Cricket leagues
        display_modes: Enable live, recent, upcoming modes
        favorite_teams: Team names per league
        show_records: Display team records
        show_ranking: Display team rankings
        background_service: Data fetching configuration
    """

    # ESPN API endpoints for cricket leagues
    ESPN_API_URLS = {
        'theashes.2526': 'https://site.api.espn.com/apis/site/v2/sports/cricket/1455609/scoreboard',
        'sheffieldshield.2526': 'https://site.api.espn.com/apis/site/v2/sports/cricket/1495274/scoreboard',
        'wbbl.2526': 'https://site.api.espn.com/apis/site/v2/sports/cricket/1490537/scoreboard', #?dates=20251127',
        'bbl.2526': 'https://site.api.espn.com/apis/site/v2/sports/cricket/1490534/scoreboard'
    }

    # League display names
    LEAGUE_NAMES = {
        'theashes.2526': 'The Ashes 2025/26',
        'sheffieldshield.2526': 'Sheffield Shield 2025/26',
        'wbbl.2526': 'WBBL 2025/26',
        'bbl.2526': 'BBL 2025/26'
    }

    def __init__(self, plugin_id: str, config: Dict[str, Any],
                 display_manager, cache_manager, plugin_manager):
        """Initialize the cricket scoreboard plugin."""
        super().__init__(plugin_id, config, display_manager, cache_manager, plugin_manager)

        # Configuration - per-league structure
        self.leagues = config.get('leagues', {})

        # Global settings
        self.global_config = config
        self.display_duration = config.get('display_duration', 5)
        self.show_records = config.get('show_records', False)
        self.show_ranking = config.get('show_ranking', False)

        # Background service configuration (internal only)
        self.background_config = {
            'enabled': True,
            'request_timeout': 30,
            'max_retries': 3,
            'priority': 2
        }

        # State
        self.current_games = []
        self.current_league = None
        self.current_display_mode = None
        self.last_update = 0
        self.initialized = True
                     
        # Load fonts for rendering
        self.fonts = self._load_fonts()

        # Register fonts
        self._register_fonts()

        # Log enabled leagues and their settings
        enabled_leagues = []
        for league_key, league_config in self.leagues.items():
            if league_config.get('enabled', False):
                enabled_leagues.append(league_key)

        self.logger.info("Cricket scoreboard plugin initialized")
        self.logger.info(f"Enabled leagues: {enabled_leagues}")

    def _load_fonts(self):
        """Load fonts used by the scoreboard - matching original managers."""
        fonts = {}
        try:
            fonts['score'] = ImageFont.truetype("assets/fonts/PressStart2P-Regular.ttf", 8)
            fonts['time'] = ImageFont.truetype("assets/fonts/PressStart2P-Regular.ttf", 8)
            fonts['team'] = ImageFont.truetype("assets/fonts/PressStart2P-Regular.ttf", 8)
            fonts['status'] = ImageFont.truetype("assets/fonts/4x6-font.ttf", 6)
            #fonts['detail'] = ImageFont.truetype("assets/fonts/4x6-font.ttf", 6)
            fonts['detail'] = ImageFont.truetype("assets/fonts/PressStart2P-Regular.ttf", 6)
            fonts['rank'] = ImageFont.truetype("assets/fonts/PressStart2P-Regular.ttf", 9)
            self.logger.info("Successfully loaded fonts")
        except IOError as e:
            self.logger.warning(f"Fonts not found, using default PIL font: {e}")
            fonts['score'] = ImageFont.load_default()
            fonts['time'] = ImageFont.load_default()
            fonts['team'] = ImageFont.load_default()
            fonts['status'] = ImageFont.load_default()
            fonts['detail'] = ImageFont.load_default()
            fonts['rank'] = ImageFont.load_default()
        return fonts
    
    def _register_fonts(self):
        """Register fonts with the font manager."""
        try:
            if not hasattr(self.plugin_manager, 'font_manager'):
                return

            font_manager = self.plugin_manager.font_manager

            # Team name font
            font_manager.register_manager_font(
                manager_id=self.plugin_id,
                element_key=f"{self.plugin_id}.team_name",
                family="press_start",
                size_px=10,
                color=(255, 255, 255)
            )

            # Score font
            font_manager.register_manager_font(
                manager_id=self.plugin_id,
                element_key=f"{self.plugin_id}.score",
                family="press_start",
                size_px=12,
                color=(255, 200, 0)
            )

            # Status font (time, half)
            font_manager.register_manager_font(
                manager_id=self.plugin_id,
                element_key=f"{self.plugin_id}.status",
                family="four_by_six",
                size_px=6,
                color=(0, 255, 0)
            )

            # Detail font (records, rankings)
            font_manager.register_manager_font(
                manager_id=self.plugin_id,
                element_key=f"{self.plugin_id}.detail",
                family="press_start",
                size_px=10,
                color=(200, 200, 200)
            )

            self.logger.info("Cricket scoreboard fonts registered")
        except Exception as e:
            self.logger.warning(f"Error registering fonts: {e}")

    def update(self) -> None:
        """Update cricket game data for all enabled leagues."""
        if not self.initialized:
            return

        try:
            self.current_games = []

            # Fetch data for each enabled league
            for league_key, league_config in self.leagues.items():
                if league_config.get('enabled', False):
                    games = self._fetch_league_data(league_key, league_config)
                    if games:
                        # Add league info to each game
                        for game in games:
                            game['league_config'] = league_config
                        self.current_games.extend(games)

            # Sort games - prioritize live games and favorites
            self._sort_games()

            self.last_update = time.time()
            self.logger.debug(f"Updated cricket data: {len(self.current_games)} games")

        except Exception as e:
            self.logger.error(f"Error updating cricket data: {e}")

    def _sort_games(self):
        """Sort games by priority and favorites."""
        def sort_key(game):
            league_key = game.get('league')
            league_config = game.get('league_config', {})
            status = game.get('status', {})

            # Priority 1: Live games
            is_live = status.get('state') == 'in'
            live_score = 0 if is_live else 1

            # Priority 2: Favorite teams
            favorite_score = 0 if self._is_favorite_game(game) else 1

            # Priority 3: Start time (earlier games first for upcoming, later for recent)
            start_time = game.get('start_time', '')

            return (live_score, favorite_score, start_time)

        self.current_games.sort(key=sort_key)

    def _fetch_league_data(self, league_key: str, league_config: Dict) -> List[Dict]:
        """Fetch game data for a specific league."""
        cache_key = f"cricket_{league_key}_{datetime.now().strftime('%Y%m%d')}"
        update_interval = league_config.get('update_interval_seconds', 60)

        # Check cache first (use league-specific interval)
        cached_data = self.cache_manager.get(cache_key)
        if cached_data and (time.time() - self.last_update) < update_interval:
            self.logger.debug(f"Using cached data for {league_key}")
            return cached_data

        # Fetch from API
        try:
            url = self.ESPN_API_URLS.get(league_key)
            if not url:
                self.logger.error(f"Unknown league key: {league_key}")
                return []

            #yesterday_date = now - timedelta(days=1)
            #tomorrow_date = now + timedelta(days=1)
            #yesterday_str = yesterday_date.strftime("%Y%m%d")
            #tomorrow_str = tomorrow_date.strftime("%Y%m%d")
            #formatted_date_parm = f"?dates={yesterday_str}-{tomorrow_str}"
            #url = url + formatted_date_parm
            
            self.logger.info(f"Fetching {league_key} data from ESPN API...")
            response = requests.get(url, timeout=self.background_config.get('request_timeout', 30))
            response.raise_for_status()

            data = response.json()
            games = self._process_api_response(data, league_key, league_config)

            # Cache for league-specific interval
            self.cache_manager.set(cache_key, games, ttl=update_interval * 2)
            #self.cache_manager.set(cache_key, games, 120)

            return games

        except requests.RequestException as e:
            self.logger.error(f"Error fetching {league_key} data: {e}")
            return []
        except Exception as e:
            self.logger.error(f"Error processing {league_key} data: {e}")
            return []

    def _process_api_response(self, data: Dict, league_key: str, league_config: Dict) -> List[Dict]:
        """Process ESPN API response into standardized game format."""
        games = []

        try:
            events = data.get('events', [])
            league_name = data.get('leagues', [{}])[0].get('name','Unknown')
            league_abbreviation = data.get('leagues', [{}])[0].get('abbreviation','Unknown')

            for event in events:
                try:
                    game = self._extract_game_info(event, league_key, league_config, league_name, league_abbreviation)
                    if game:
                        games.append(game)
                except Exception as e:
                    self.logger.error(f"Error extracting game info: {e}")
                    continue

        except Exception as e:
            self.logger.error(f"Error processing API response: {e}")

        return games

    def _extract_game_info(self, event: Dict, league_key: str, league_config: Dict, league_name: str, league_abbreviation: str) -> Optional[Dict]:
        """Extract game information from ESPN event."""
        try:
            competition = event.get('competitions', [{}])[0]
            status = competition.get('status', {})
            competitors = competition.get('competitors', [])

            if len(competitors) < 2:
                return None

            # Find home and away teams
            home_team = next((c for c in competitors if c.get('homeAway') == 'home'), None)
            away_team = next((c for c in competitors if c.get('homeAway') == 'away'), None)
            
            home_team_linescores = home_team.get('linescores', [])
            home_team_batting_one = next((c for c in home_team_linescores if c.get('isBatting') == True and c.get('period') <= 2), None)
            home_team_batting_two = next((c for c in home_team_linescores if c.get('isBatting') == True and c.get('period') >= 3), None)
            away_team_linescores = away_team.get('linescores', [])
            away_team_batting_one = next((c for c in away_team_linescores if c.get('isBatting') == True and c.get('period') <= 2), None)
            away_team_batting_two = next((c for c in away_team_linescores if c.get('isBatting') == True and c.get('period') >= 3), None)
            
            if not home_team or not away_team:
                return None

            # Extract game details
            game = {
                'league': league_key,
                'league_config': league_config,
                'league_name': league_name,
                'league_abbreviation': league_abbreviation,
                'game_id': event.get('id'),
                'generalClassCard': competition.get('class', {}).get('generalClassCard', 'Unknown Class'),
                'home_team': {
                    'name': home_team.get('team', {}).get('displayName', 'Unknown'),
                    'abbrev': home_team.get('team', {}).get('abbreviation', 'UNK'),
                    'score': home_team.get('score', 'Unknown'),
                    'logo': home_team.get('team', {}).get('logo')
                },
                'away_team': {
                    'name': away_team.get('team', {}).get('displayName', 'Unknown'),
                    'abbrev': away_team.get('team', {}).get('abbreviation', 'UNK'),
                    #'score': int(away_team.get('score', 0)),
                    'score': away_team.get('score', 'Unknown'),
                    'logo': away_team.get('team', {}).get('logo')
                },
                'status': {
                    'state': status.get('type', {}).get('state', 'unknown'),
                    'detail': status.get('type', {}).get('detail', ''),
                    'short_detail': status.get('type', {}).get('shortDetail', ''),
                    'description': status.get('type', {}).get('description', ''),
                    'period': status.get('period', 0),
                    'display_clock': status.get('displayClock', ''),
                    'summary': status.get('summary',''),
                    'session': status.get('session',''),
                },
                'start_time': event.get('date', ''),
                'event_desc': event.get('description', ''),
                'event_name': event.get('name', ''),
                'venue': competition.get('venue', {}).get('fullName', 'Unknown Venue'),
                'comp_desc': competition.get('description', '')
            }
            if home_team_batting_one:
                game['home_team'].update({
                    'wickets': home_team_batting_one.get('wickets',0),
                    'runs': home_team_batting_one.get('runs',0),
                    'overs': home_team_batting_one.get('overs',0)
                })
            if away_team_batting_one:
                game['away_team'].update({
                    'wickets': away_team_batting_one.get('wickets',0),
                    'runs': away_team_batting_one.get('runs',0),
                    'overs': away_team_batting_one.get('overs',0)
                })
            
            return game

        except Exception as e:
            self.logger.error(f"Error extracting game info: {e}")
            return None

    def _is_favorite_game(self, game: Dict) -> bool:
        """Check if game involves a favorite team."""
        league = game.get('league')
        league_config = game.get('league_config', {})
        favorites = league_config.get('favorite_teams', [])

        if not favorites:
            return False

        home_name = game.get('home_team', {}).get('name', '')
        away_name = game.get('away_team', {}).get('name', '')

        return home_name in favorites or away_name in favorites

    def display(self, display_mode: str = None, force_clear: bool = False) -> None:
        """
        Display cricket games.

        Args:
            display_mode: Which mode to display (cricket_live, cricket_recent, cricket_upcoming)
            force_clear: If True, clear display before rendering
        """
        if not self.initialized:
            self._display_error("Cricket plugin not initialized")
            return

        # Determine which display mode to use - prioritize live games if enabled
        if not display_mode:
            # Auto-select mode based on available games and priorities
            if self._has_live_games():
                display_mode = 'cricket_live'
            else:
                # Fall back to recent or upcoming
                display_mode = 'cricket_recent' if self._has_recent_games() else 'cricket_upcoming'

        self.current_display_mode = display_mode

        # Filter games by display mode
        filtered_games = self._filter_games_by_mode(display_mode)

        if not filtered_games:
            self._display_no_games(display_mode)
            return

        # Display the first game (rotation handled by LEDMatrix)
        #game = filtered_games[0]
        #self._display_game(game, display_mode)
        for i in range(len(filtered_games)):
            game = filtered_games[i]
            self._display_game(game, display_mode)
            time.sleep(self.display_duration / 2)

    def _filter_games_by_mode(self, mode: str) -> List[Dict]:
        """Filter games based on display mode and per-league settings."""
        filtered = []

        for game in self.current_games:
            league_key = game.get('league')
            league_config = game.get('league_config', {})
            status = game.get('status', {})
            state = status.get('state')

            # Check if this mode is enabled for this league
            display_modes = league_config.get('display_modes', {})
            mode_enabled = display_modes.get(mode.replace('cricket_', ''), False)
            if not mode_enabled:
                continue

            # Filter by game state and per-league limits
            if mode == 'cricket_live' and state == 'in':
                filtered.append(game)

            elif mode == 'cricket_recent' and state == 'post':
                # Check recent games limit for this league
                recent_limit = league_config.get('recent_games_to_show', 5)
                recent_count = len([g for g in filtered if g.get('league') == league_key and g.get('status', {}).get('state') == 'post'])
                if recent_count >= recent_limit:
                    continue
                filtered.append(game)

            elif mode == 'cricket_upcoming' and state == 'pre':
                # Check upcoming games limit for this league
                upcoming_limit = league_config.get('upcoming_games_to_show', 10)
                upcoming_count = len([g for g in filtered if g.get('league') == league_key and g.get('status', {}).get('state') == 'pre'])
                if upcoming_count >= upcoming_limit:
                    continue
                filtered.append(game)

        return filtered

    def _has_live_games(self) -> bool:
        """Check if there are any live games available."""
        return any(game.get('status', {}).get('state') == 'in' for game in self.current_games)

    def _has_recent_games(self) -> bool:
        """Check if there are any recent games available."""
        return any(game.get('status', {}).get('state') == 'post' for game in self.current_games)

    def _load_team_logo(self, team: Dict, league: str) -> Optional[Image.Image]:
        """Load and resize team logo - matching football plugin logic."""
        try:
            # Get logo directory from league configuration
            league_config = self.leagues.get(league, {})
            #logo_dir = league_config.get('logo_dir', 'assets/sports/cricket_logos')
            logo_dir = league_config.get('logo_dir', 'plugin-repos/cricket-scoreboard/logos')
            
            # Convert relative path to absolute path by finding LEDMatrix project root
            if not os.path.isabs(logo_dir):
                current_dir = os.path.dirname(os.path.abspath(__file__))
                ledmatrix_root = None
                for parent in [current_dir, os.path.dirname(current_dir), os.path.dirname(os.path.dirname(current_dir))]:
                    if os.path.exists(os.path.join(parent, 'assets', 'sports')):
                        ledmatrix_root = parent
                        break
                
                if ledmatrix_root:
                    logo_dir = os.path.join(ledmatrix_root, logo_dir)
                else:
                    logo_dir = os.path.abspath(logo_dir)
            
            team_abbrev = team.get('abbrev', '')
            if not team_abbrev:
                return None
            
            # Try different case variations and extensions
            logo_extensions = ['.png', '.jpg', '.jpeg']
            logo_path = None
            abbrev_variations = [team_abbrev.upper(), team_abbrev.lower(), team_abbrev]
            
            for abbrev in abbrev_variations:
                for ext in logo_extensions:
                    potential_path = os.path.join(logo_dir, f"{abbrev}{ext}")
                    if os.path.exists(potential_path):
                        logo_path = potential_path
                        break
                if logo_path:
                    break
            
            if not logo_path:
                return None
            
            # Load and resize logo (matching original managers)
            logo = Image.open(logo_path).convert('RGBA')
            max_width = int(self.display_manager.matrix.width * 1.5)
            max_height = int(self.display_manager.matrix.height * 1.5)
            logo.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)
            
            return logo
            
        except Exception as e:
            self.logger.debug(f"Could not load logo for {team.get('abbrev', 'unknown')}: {e}")
            return None

    def _draw_text_with_outline(self, draw: ImageDraw.Draw, text: str, position: tuple, font, fill=(255, 255, 255), outline_color=(0, 0, 0)):
        """Draw text with a black outline for better readability."""
        try:
            x, y = position
            # Draw outline
            for dx, dy in [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]:
                draw.text((x + dx, y + dy), text, font=font, fill=outline_color)
            # Draw main text
            draw.text((x, y), text, font=font, fill=fill)
        except Exception as e:
            self.logger.error(f"Error drawing text with outline: {e}")
    
    def _display_game(self, game: Dict, mode: str):
        """Display a single game."""
        try:
            matrix_width = self.display_manager.matrix.width
            matrix_height = self.display_manager.matrix.height

            # Create image
            img = Image.new('RGB', (matrix_width, matrix_height), (0, 0, 0))
            draw = ImageDraw.Draw(img)

            # Create image with transparency support
            main_img = Image.new('RGBA', (matrix_width, matrix_height), (0, 0, 0, 255))
            overlay = Image.new('RGBA', (matrix_width, matrix_height), (0, 0, 0, 0))
            draw_overlay = ImageDraw.Draw(overlay)
            
            # Get team info
            home_team = game.get('home_team', {})
            away_team = game.get('away_team', {})
            status = game.get('status', {})
            event_desc = game.get('event_desc', {})
            event_name = game.get('event_name', {}) # Australia v England
            comp_desc = game.get('comp_desc', {}) # 2nd Test

            # Display team names/abbreviations
            home_name = home_team.get('name', 'HOME')
            away_name = away_team.get('name', 'AWAY')

            # TODO: Add team logos if available
            # Load team logos
            home_logo = self._load_team_logo(home_team, game.get('league', ''))
            self.logger.info(f"Working on {home_team} logo from ESPN API...")
            away_logo = self._load_team_logo(away_team, game.get('league', ''))
            self.logger.info(f"Working on {away_team} logo from ESPN API...")
            
            # TODO: Use font manager for text rendering
            # TODO: Add scores, time, half display

            if home_logo and away_logo:

                # Draw logos (matching original positioning)
                center_y = matrix_height // 2
                #home_x = matrix_width - home_logo.width + 10
                home_x = -10
                home_y = center_y - (home_logo.height // 2)
                main_img.paste(home_logo, (home_x, home_y), home_logo)
                
                #away_x = -10
                away_x = matrix_width - away_logo.width + 10
                away_y = center_y - (away_logo.height // 2)
                main_img.paste(away_logo, (away_x, away_y), away_logo)

                # Draw scores (centered)
                #home_score = str(home_team.get('score', 0))
                #away_score = str(away_team.get('score', 0))
                #score_text = f"{away_score}-{home_score}"
                #score_text = f"{home_score}-{away_score}"
                
                home_wickets = str(home_team.get('wickets', 0))
                home_runs = str(home_team.get('runs', 0))
                if home_wickets == "10":
                    home_score_text = f"{home_runs}"
                else:
                    home_score_text = f"{home_wickets}/{home_runs}"
                home_score_text_width = draw_overlay.textlength(home_score_text, font=self.fonts['rank'])
                home_score_text_x = 5
                home_score_text_y = (matrix_height // 2) - 7
                home_overs = str(home_team.get('overs', 0))
                home_overs_text = f"{home_overs} Overs"
                home_overs_text = home_overs_text.replace(".0 "," ")
                home_overs_text_width = draw_overlay.textlength(home_overs_text, font=self.fonts['detail'])
                home_overs_text_x = 5
                home_overs_text_y = (matrix_height // 2) + 5
                if home_overs_text != "0 Overs":
                    self._draw_text_with_outline(draw_overlay, home_score_text, (home_score_text_x, home_score_text_y), self.fonts['rank'], fill=(255, 255, 255))
                    self._draw_text_with_outline(draw_overlay, home_overs_text, (home_overs_text_x, home_overs_text_y), self.fonts['detail'], fill=(255, 255, 255))

                away_wickets = str(away_team.get('wickets', 0))
                away_runs = str(away_team.get('runs', 0))
                if away_wickets == "10":
                    away_score_text = f"{away_runs}"
                else:
                    away_score_text = f"{away_wickets}/{away_runs}"
                away_score_text_width = draw_overlay.textlength(away_score_text, font=self.fonts['rank'])
                away_score_text_x = (matrix_width - away_score_text_width - 5)
                away_score_text_y = (matrix_height // 2) - 7
                away_overs = str(away_team.get('overs', 0))
                away_overs_text = f"{away_overs} Overs"
                away_overs_text = away_overs_text.replace(".0 "," ")
                away_overs_text_width = draw_overlay.textlength(away_overs_text, font=self.fonts['detail'])
                away_overs_text_x = (matrix_width - away_overs_text_width - 5)
                away_overs_text_y = (matrix_height // 2) + 5
                if away_overs_text != "0 Overs":
                    self._draw_text_with_outline(draw_overlay, away_score_text, (away_score_text_x, away_score_text_y), self.fonts['rank'], fill=(255, 255, 255))
                    self._draw_text_with_outline(draw_overlay, away_overs_text, (away_overs_text_x, away_overs_text_y), self.fonts['detail'], fill=(255, 255, 255))
                
                # Inning/Status (top center)
                #status_text = game.get('event_name','')
                status_text = f"{game.get('league_name','')}"
                
                status_width = draw_overlay.textlength(status_text, font=self.fonts['time'])
                status_x = (matrix_width - status_width) // 2
                status_y = 1
                self._draw_text_with_outline(draw_overlay, status_text, (status_x, status_y), self.fonts['time'], fill=(0, 255, 0))
                
                session_text = status.get('session','')
                status_type_desc = status.get('description','')
                if session_text == "":
                    session_text = f"{game.get('comp_desc', {})} - {status_type_desc}"
                else:
                    session_text = f"{game.get('comp_desc', {})} - {session_text} - {status_type_desc}"
                session_width = draw_overlay.textlength(session_text, font=self.fonts['score'])
                session_x = (matrix_width - session_width) // 2
                session_y = 11
                self._draw_text_with_outline(draw_overlay, session_text, (session_x, session_y), self.fonts['score'], fill=(255, 200, 0))
                
                #score_width = draw_overlay.textlength(score_text, font=self.fonts['detail'])
                #score_x = (matrix_width - score_width) // 2
                #score_y = (matrix_height // 2) - 5
                #self._draw_text_with_outline(draw_overlay, score_text, (score_x, score_y), self.fonts['detail'], fill=(255, 255, 255))

                summary_text = status.get('summary','')
                summary_width = draw_overlay.textlength(summary_text, font=self.fonts['score'])
                summary_x = (matrix_width - summary_width) // 2
                summary_y = (matrix_height // 2) + 15
                self._draw_text_with_outline(draw_overlay, summary_text, (summary_x, summary_y), self.fonts['score'], fill=(255, 200, 0))
                
                venue_text = f"{game.get('generalClassCard','')} - {game.get('venue','')}"
                venue_width = draw_overlay.textlength(venue_text, font=self.fonts['detail'])
                venue_x = (matrix_width - venue_width) // 2
                venue_y = matrix_height - 6
                self._draw_text_with_outline(draw_overlay, venue_text, (venue_x, venue_y), self.fonts['detail'], fill=(255, 165, 0))

                
                # Composite and display
                final_img = Image.alpha_composite(main_img, overlay)
                self.display_manager.image = final_img.convert('RGB').copy()

            else:

                # For now, simple text display (placeholder)
                draw.text((5, 5), f"{away_name} @ {home_name}", fill=(255, 255, 255))
                draw.text((5, 15), f"{away_team.get('score', 0)} - {home_team.get('score', 0)}", fill=(255, 200, 0))
                draw.text((5, 25), status.get('short_detail', ''), fill=(0, 255, 0))
    
                self.display_manager.image = img.copy()

            
            self.display_manager.update_display()

        except Exception as e:
            self.logger.error(f"Error displaying game: {e}")
            self._display_error("Display error")

    def _display_no_games(self, mode: str):
        """Display message when no games are available."""
        img = Image.new('RGB', (self.display_manager.matrix.width,
                               self.display_manager.matrix.height),
                       (0, 0, 0))
        draw = ImageDraw.Draw(img)

        message = {
            'cricket_live': "No Live Games",
            'cricket_recent': "No Recent Games",
            'cricket_upcoming': "No Upcoming Games"
        }.get(mode, "No Games")

        draw.text((5, 12), message, fill=(150, 150, 150))

        self.display_manager.image = img.copy()
        self.display_manager.update_display()

    def _display_error(self, message: str):
        """Display error message."""
        img = Image.new('RGB', (self.display_manager.matrix.width,
                               self.display_manager.matrix.height),
                       (0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.text((5, 12), message, fill=(255, 0, 0))

        self.display_manager.image = img.copy()
        self.display_manager.update_display()

    def get_display_duration(self) -> float:
        """Get display duration from config."""
        return self.display_duration

    def get_info(self) -> Dict[str, Any]:
        """Return plugin info for web UI."""
        info = super().get_info()

        # Get league-specific configurations
        leagues_config = {}
        for league_key, league_config in self.leagues.items():
            leagues_config[league_key] = {
                'enabled': league_config.get('enabled', False),
                'favorite_teams': league_config.get('favorite_teams', []),
                'display_modes': league_config.get('display_modes', {}),
                'recent_games_to_show': league_config.get('recent_games_to_show', 5),
                'upcoming_games_to_show': league_config.get('upcoming_games_to_show', 10),
                'update_interval_seconds': league_config.get('update_interval_seconds', 60)
            }

        info.update({
            'total_games': len(self.current_games),
            'enabled_leagues': [k for k, v in self.leagues.items() if v.get('enabled', False)],
            'current_mode': self.current_display_mode,
            'last_update': self.last_update,
            'display_duration': self.display_duration,
            'show_records': self.show_records,
            'show_ranking': self.show_ranking,
            'live_games': len([g for g in self.current_games if g.get('status', {}).get('state') == 'in']),
            'recent_games': len([g for g in self.current_games if g.get('status', {}).get('state') == 'post']),
            'upcoming_games': len([g for g in self.current_games if g.get('status', {}).get('state') == 'pre']),
            'leagues_config': leagues_config,
            'global_config': self.global_config
        })
        return info

    def cleanup(self) -> None:
        """Cleanup resources."""
        self.current_games = []
        self.logger.info("Cricket scoreboard plugin cleaned up")
