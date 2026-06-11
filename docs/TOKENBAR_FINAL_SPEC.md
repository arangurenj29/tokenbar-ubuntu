# TokenBar Final Product Specification

## Purpose

TokenBar SHALL be a Linux tray utility for this Ubuntu GNOME/Wayland machine that monitors Codex/OpenAI and Claude Code quota/usage without attempting macOS CodexBar parity or broad provider support.

## Supported Environment

### Requirement: Narrow Linux Support

The system MUST officially support Ubuntu GNOME on Wayland with GTK 3 and Ayatana AppIndicator available.

#### Scenario: Supported desktop

- GIVEN the user is running Ubuntu GNOME on Wayland
- WHEN TokenBar starts
- THEN it SHALL choose an AppIndicator-compatible tray backend
- AND it SHALL show a tray icon and menu

#### Scenario: Unsupported desktop

- GIVEN the session cannot host a tray
- WHEN `--check` or `--doctor` runs
- THEN TokenBar SHALL report the missing display/tray condition clearly

## Providers

### Requirement: Codex and Claude First

The system MUST read Codex usage from local Codex auth and Claude usage from local Claude credentials. OpenAI API costs MAY be enabled explicitly.

#### Scenario: Default providers

- GIVEN no config file exists
- WHEN TokenBar collects snapshots
- THEN Codex and Claude SHALL be enabled
- AND OpenAI API costs SHALL be disabled

#### Scenario: Provider auth failure

- GIVEN a provider token is missing or expired
- WHEN TokenBar refreshes data
- THEN the menu SHALL show a readable failure state
- AND it SHALL show the relevant login guidance

## Tray Experience

### Requirement: Remaining Quota Display

The tray menu MUST display provider availability as remaining quota, not used quota.

#### Scenario: Successful usage refresh

- GIVEN Codex or Claude returns a utilization percentage
- WHEN the menu renders the provider
- THEN it SHALL show a usage bar
- AND it SHALL show `% left`
- AND reset countdown/details SHALL appear below the bar

#### Scenario: Low quota

- GIVEN a provider has remaining quota at or below the configured threshold
- WHEN the menu renders
- THEN TokenBar SHALL mark that provider as low quota
- AND the tray icon SHALL enter warning state

## Refresh, Cache, and Stale State

### Requirement: Resilient Refresh

The system MUST refresh automatically, support manual refresh, prevent overlapping refreshes, and cache the latest successful snapshot.

#### Scenario: Startup with cache

- GIVEN a cached snapshot exists
- WHEN TokenBar starts
- THEN it SHALL render cached data immediately
- AND it SHALL run a live refresh in the background

#### Scenario: Stale data

- GIVEN the last successful refresh is older than the configured stale threshold
- WHEN TokenBar renders status
- THEN it SHALL mark the data as stale

## Configuration

### Requirement: Minimal JSON Settings

The system MUST read optional settings from `~/.config/tokenbar/config.json` and safely fall back to defaults.

#### Scenario: Missing or invalid config

- GIVEN the config file is missing or invalid
- WHEN TokenBar starts
- THEN it SHALL continue with defaults
- AND diagnostics SHALL expose the config status

#### Scenario: User configures behavior

- GIVEN config values for providers, refresh interval, stale threshold, low quota, or notifications
- WHEN TokenBar starts
- THEN it SHALL apply supported values
- AND ignore unknown keys

## Notifications

### Requirement: Useful Non-Spam Alerts

The system MUST support configurable desktop notifications for low quota, provider errors, and stale data, while avoiding repeated alerts for unchanged conditions.

#### Scenario: New alert condition

- GIVEN a provider enters a low-quota or error state
- WHEN TokenBar processes a live refresh
- THEN it SHALL send one desktop notification
- AND persist active alert state

#### Scenario: Repeated unchanged condition

- GIVEN the same alert condition remains active
- WHEN subsequent refreshes run
- THEN TokenBar SHALL NOT repeat the notification

#### Scenario: Snoozed alerts

- GIVEN alerts are snoozed
- WHEN an alert condition occurs before snooze expiry
- THEN TokenBar SHALL suppress notifications until the snooze expires

## Diagnostics and Controls

### Requirement: Operator Visibility

The system MUST provide CLI and tray controls for diagnostics, config, auth guidance, notifications, and autostart.

#### Scenario: Doctor output

- GIVEN the user runs `--doctor`
- WHEN diagnostics execute
- THEN TokenBar SHALL report tray/session state, auth presence, config/cache paths, notification tools, and autostart status

#### Scenario: Autostart

- GIVEN the user enables autostart
- WHEN TokenBar writes the autostart entry
- THEN it SHALL create a user-level `.desktop` entry under `~/.config/autostart`

## Packaging Readiness

### Requirement: Installable Ubuntu App

Before release, TokenBar SHOULD provide an installer or package that installs the launcher, desktop entry, icon assets, and required runtime metadata without changing the narrow support scope.

#### Scenario: Fresh install

- GIVEN a supported Ubuntu GNOME machine with dependencies installed
- WHEN the user installs TokenBar
- THEN `tokenbar` SHALL be runnable from the desktop/session
- AND the tray icon SHALL use the TokenBar coin icon

#### Scenario: Uninstall

- GIVEN TokenBar was installed
- WHEN the user uninstalls it
- THEN installed launchers, icons, and autostart entries SHOULD be removable without deleting user config/cache unless requested
