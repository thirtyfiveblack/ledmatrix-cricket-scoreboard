# Cricket Scoreboard Plugin

A plugin for LEDMatrix that displays live, recent, and upcoming cricket games.

## Features

- **Multiple League Support**: Premier League, La Liga, Bundesliga, Serie A, Ligue 1, MLS, Champions League, Europa League, and more
- **Live Game Tracking**: Real-time scores, match time, and half information
- **Recent Games**: Recently completed games with final scores
- **Upcoming Games**: Scheduled games with start times
- **Favorite Teams**: Prioritize games involving your favorite teams
- **Background Data Fetching**: Efficient API calls without blocking display

## Configuration

### Global Settings

- `display_duration`: How long to show each game (5-60 seconds, default: 15)
- `show_records`: Display team win-loss records (default: false)
- `show_ranking`: Display team rankings when available (default: false)
- `background_service`: Configure API request settings

### Per-League Settings

#### Premier League Configuration

```json
{
  "leagues": {
    "eng.1": {
      "enabled": true,
      "favorite_teams": ["Manchester United", "Liverpool", "Arsenal"],
      "display_modes": {
        "live": true,
        "recent": true,
        "upcoming": true
      },
      "recent_games_to_show": 5,
      "upcoming_games_to_show": 10
    }
  }
}
```

## Display Modes

The plugin supports three display modes:

1. **soccer_live**: Shows currently active games
2. **soccer_recent**: Shows recently completed games
3. **soccer_upcoming**: Shows scheduled upcoming games

## Supported Leagues

The plugin supports the following soccer leagues:

- **eng.1**: Premier League (England)

## Team Names

You can use either full team names or common abbreviations:

## Background Service

The plugin uses background data fetching for efficient API calls:

- Requests timeout after 30 seconds (configurable)
- Up to 3 retries for failed requests
- Priority level 2 (medium priority)

## Data Source

Game data is fetched from ESPN's public API endpoints for all supported soccer leagues.

## Dependencies

This plugin requires the main LEDMatrix installation and uses the plugin system base classes.

## Installation

1. Copy this plugin directory to your `ledmatrix-plugins/plugins/` folder
2. Ensure the plugin is enabled in your LEDMatrix configuration
3. Configure your favorite teams and display preferences
4. Restart LEDMatrix to load the new plugin

## Troubleshooting

- **No games showing**: Check if leagues are enabled and API endpoints are accessible
- **Missing team logos**: Ensure team logo files exist in your assets/sports/soccer_logos/ directory
- **Slow updates**: Adjust the update interval in league configuration
- **API errors**: Check your internet connection and ESPN API availability

## Advanced Configuration

For more advanced users, you can add additional leagues by modifying the `ESPN_API_URLS` dictionary in the plugin code and updating the configuration schema accordingly.
