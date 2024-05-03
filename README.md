# `K`andji `A`uto`P`kg `P`rocessor `A`ctions (`KAPPA`)

KAPPA is an AutoPkg Processor designed for programmatic management of Kandji Custom Apps

## Table of Contents
- [About](#about)
- [Prerequisites](#prerequisites)
- [Initial Setup](#initial-setup)
- [Usage](#usage)
- [Configuration Options](#configuration-options)
  - [KAPPA Config](#kappa-config)
  - [In-Recipe](#in-recipe)
  - [Recipe Map](#recipe-map)
- [Runtime Considerations](#runtime-considerations)
  - [Supported Custom Apps](#supported-custom-apps)
  - [Enforcements](#enforcements)
  - [Custom App Behavior](#custom-app-behavior)
- [Technical Details](#technical-details)
  - [Secrets Management](#secrets-management)
  - [Kandji Token Permissions](#kandji-token-permissions)
  - [Slack Token Setup](#slack-token-setup)
  - [config.json](#configjson)
  - [AutoPkg Recipe Config](#autopkg-recipe-config)
  - [recipe_map.json](#recipe_mapjson)
  - [setup.command Flags](#setupcommand-flags)
  - [Audit/Enforcement Examples](#audit-enforcement-examples)

## About
An AutoPkg Processor designed for programmatic management of Kandji Custom Apps

Configurable in a variety of ways, KAPPA can be used to create, update, and enforce Custom Apps in Kandji

Fully open source, we welcome contributions and feedback to improve the tool!

## Prerequisites
Before running KAPPA, ensure you have the following:

- An AutoPkg install (on-prem or CI/CD)
  - `setup.command` will prompt to download/install AutoPkg if not found
- Kandji API token ([required permissions](#kandji-token-permissions))
- Slack webhook token (optional; [setup instructions](#slack-token-setup))

## Initial Setup

1. Open Terminal and run `autopkg repo-add kandji-inc/KAPPA` to clone/add KAPPA to AutoPkg
  * Alternatively, [click here](https://github.com/kandji-inc/KAPPA/releases/latest) to download the latest `.zip` release
2. Within Terminal, run `autopkg repo-list` and open the local path for KAPPA in Finder (likely `~/Library/AutoPkg/RecipeRepos/com.github.kandji-inc.KAPPA`)
  * Alternatively, double-click on the `.zip` downloaded above
3. Double-click on `setup.command`, found in the folder opened above
   - Initial setup will interactively prompt for:
     - **Kandji API URL** (`TENANT.api.[eu.]kandji.io`)
     - **Secrets keystore selection** (ENV and/or user's login keychain)
       - _If running AutoPkg/AutoPkgr on a dedicated Mac, select keychain_
     - **Kandji bearer token**
     - **Slack webhook token** (optional)

> [!NOTE]
> If running KAPPA in CI/CD, exit initial setup, and instead run `setup.command -c` to set required parameters in `config.json`
>
> Capture modified `.json` files and deploy them during runtime to overwrite repo defaults


[See below](#setupcommand-flags) for available `setup.command` flags

## Usage

KAPPA runs after a PKG is built, either added in-line to an AutoPkg recipe/override:

```xml
            <dict>
                <key>Processor</key>
                <string>io.kandji.kappa/KAPPA</string>
            </dict>
```

Or by specifying `io.kandji.kappa/KAPPA` as a postprocessor in a GUI tool like AutoPkgr or via command line:

`autopkg run RECIPE.pkg.recipe --post io.kandji.kappa/KAPPA`

|<img src="https://github.com/kandji-inc/support/assets/27963671/71e53bbc-83c0-4c64-a05d-7a1be38721f9" width="600">|
|:-:|
|KAPPA configured in AutoPkgr|

---

## Configuration Options

KAPPA supports both in-recipe and centralized options for customizing your AutoPkg --> Kandji workflow

### KAPPA Config

- `config.json` includes defaults if no per-recipe settings are found
  - Config can be modified as desired to set preferred defaults
  - [See below](#configjson) for an overview of available options and a sample config

### In-Recipe

- Recipes/overrides may pass arguments to set/override the following:
  - Always create new Custom App
  - Dry run of KAPPA (do not modify Kandji)
  - Custom app name
  - Custom app name (test)
  - Self Service category
  - Self Service category (test)
  - [See below](#autopkg-recipe-config) for an overview of available options and a sample config

> [!NOTE]
> If multiple configuration types are set during runtime, those defined in-recipe supersede any mappings

### Recipe Map

- A recipe map (`recipe_map.json`) can be defined to link AutoPkg recipes/overrides to Kandji Custom Apps
  - Key is recipe name
    - e.g. `APPNAME.pkg`, as shown when running `autopkg list-recipes`
  - Below values can be defined in map:
    - Custom app name
    - Custom app name (test)
    - Self Service category
    - Self Service category (test)
  - [See below](#recipe_mapjson) for a sample config

> [!TIP]
> Running `./setup.command -m` exports a .csv containing all AutoPkg recipes, Custom App names, and Self Service categories to help populate `recipe_map.json`

## Runtime Considerations

### Supported Custom Apps
- Currently, only installer packages are supported by this project
  - Packages include flat, component, and distribution types (`.pkg`/`.mpkg`)
  - Ensure your AutoPkg recipes/overrides output a package (recipe name ends in `.pkg`)
- Based on interest, new features may be considered and added over time
  - We would also welcome contributions!
- `.pkg` uploads can be configured with any Kandji enforcement type (see below)
  - This includes installers whose payloads are app bundles (`.app`) or command line tools/binaries
    - Audit/enforcement criteria are determined from:
      - An app bundle's `Info.plist`
      - A binary's installer package metadata (must contain version)

### Enforcements
- KAPPA supports three enforcement types (configurable in `config.json`), which sets enforcement type for new Custom Apps:
  - `audit_enforce` (Default)
  - `install_once`
  - `self_service`
- When updating _existing_ Custom Apps, KAPPA will respect the enforcement type already set in Kandji
- If method can't be read from `config.json`, enforcement defaults to `install_once`

> [!NOTE]
> When a Self Service category is defined in-recipe/map, enforcement is automatically set to `self_service` (ignoring `config.json`) during new app creation

#### `audit_enforce`
- Setting `audit_enforce` bundles `audit_app_and_version.zsh` for the Custom App's Audit Script during creation
  - App name, identifier, and version details are automatically populated in the audit script prior to upload
  - Subsequent updates to apps with audit enforcement receive an updated audit script with latest app info, version, and enforcement dates
- Up to two Custom App names can be specified (in-recipe or map), one for production workflows (`prod_name`) and the other for testing (`test_name`)
  - Production defaults to **5 days** prior to enforcement, with testing set to **0 days** (immediate enforcement)
    - Days until enforcement values are configurable in `config.json`
  - If `audit_enforce` is set but no values provided for `prod_name` or `test_name`, KAPPA still uses the prod delay set in `config.json`
    - If delay values are removed from `config.json`, KAPPA will fall back to an enforcement delay of **3 days**
- [See below](#audit-enforcement-examples) for Kandji audit/enforcement output examples
- If enforcement is due, but the app in use by the user, the user will be prompted to close the app, else delay one hour
![Delay Available](https://github.com/kandji-inc/support/assets/27963671/c74148c5-5e8e-4673-a04e-e2ef480604f7)
- Once the delay has lapsed, the user will again be prompted to quit, but with no delay option
![Enforcement Due](https://github.com/kandji-inc/support/assets/27963671/8c4496ae-1c82-4297-a5c2-f0dc616c4f39)

> [!CAUTION]
> `audit_app_and_version.zsh` immediately installs the custom app if not found on-disk!
>
> Otherwise, waits until deadline to validate installed version matches or exceeds the enforced

#### `self_service`
- With `self_service` enforcement, it is recommended to define a category in-recipe/map for `ss_category` (accompanying `prod_name`)
  - If not, will fall back to defined `self_service_category` (Default: `Apps`)
- Test workflows can be used with Self Service, but also recommend defining `test_category` (accompanying `test_name`)
  - Otherwise, falls back to `test_self_service_category` (Default: `Utilities`)
    - Default Self Service categories are configurable in `config.json`

[See here](https://support.kandji.io/support/solutions/articles/72000558748-custom-apps-overview) for more information regarding Kandji Custom App enforcement

### Custom App Behavior

#### New Custom Apps
- If no value is provided for `custom_app.prod_name` in recipe/override XML, the naming convention will be taken from the `config.json` default

#### Dynamic Lookup
- KAPPA supports dynamic lookup, used as a fallback if a definitive Custom App cannot be found by name
  - Configurable in `config.json` under `zz_defaults.dynamic_lookup`
- Lack of definitive Custom App includes both matching duplicates (by name) as well as when no matches are found
  - For duplicates by name, if dynamic lookup is disabled, duplicates are posted to Slack with metadata (creation date, etc.)
  - For no matches by name, if dynamic lookup is disabled, KAPPA will create a new entry if so configured, otherwise exit
- During dynamic lookup, KAPPA detects all existing Custom App PKGs and identify any that are similar by name to the newly built PKG
  - Of those, the highest version(s) will be detected from the PKG name (given standard formatting NAME-VERSION.pkg)
  - If multiple highest versions are detected (compared via semantic version), the oldest Custom App by last modification is selected for update

> [!CAUTION]
> Dynamic lookup *will* replace a Custom App's previous package without confirmation!
>
> This may have unintended impact, so recommend first testing with dry run enabled (`-y`)

## Technical Details

### Secrets Management
- KAPPA supports two keystore options for storing tokens:
  - `environment` variables (`ENV`)
    - During `setup.command`, secret storage in the user's dotfile is determined from the default shell; `UserShell` from `dscl`
    - For `zsh`, `.zshenv` is used; for `bash`, `.bash_profile`; otherwise, `.profile`
    - If setting `ENV` programmatically for runtime, ensure `ENV_KEYSTORE` is set to `true` to enable ENV keystore
  - macOS login keychain (for console user)
    - During `setup.command`, keychain source is determined from `/usr/bin/security login-keychain`
    - Running either `setup.command` or `KAPPA` may prompt the user to unlock the keychain if locked before continuing

> [!CAUTION]
> Recommended use of this tool is on a Privileged Access Workstation/Hardened Device, accessible only to authorized users
>
> Storing secrets on-disk always poses some risk, so ensure proper security measures are in place


### Kandji Token Permissions

Configure your Kandji bearer token to include the following scope:

- <ins>**Library**</ins>
  - `Create Custom App`
  - `Upload Custom App`
  - `Update Custom App`
  - `List Custom Apps`
  - `Get Custom App`
- <ins>**Self Service**</ins>
  - `List Self Service Categories`

Instructions for creating a Kandji API token [can be found here](https://support.kandji.io/support/solutions/articles/72000560412-kandji-api)

### Slack Token Setup

- Instructions for per-channel webhook generation can be [found here](https://api.slack.com/messaging/webhooks)
  - Webhook should be in the form `https://hooks.slack.com/services/XXXXXXXXX/XXXXXXXXXXX/XXXXXXXXXXXXXXXXXXXXXXXX`

### config.json

#### Required Keys
| Required Key          | Accepted Values            | Description                                                         | Default |
|-----------------------|----------------------------|---------------------------------------------------------------------|-------|
| `kandji.api_url`      | `TENANT.api.[eu.]kandji.io`   | Valid Kandji URL for API requests                                      |  |
| `kandji.token_name`   | *Name of Kandji token in keystore* | Name of Kandji token stored in keystore                              |`KANDJI_TOKEN`|
| `li_enforcement.type`    | `audit_enforce`\|`install_once`\|`self_service`| Default enforcement type if no override specified | `audit_enforce` |
| `slack.enabled`        |`bool`<br />               | Toggle on/off Slack notifications for runtime | `true` |
| `slack.webhook_name`        | *Name of Slack token in keystore* | Token name with value `hooks.slack.com/services` | `SLACK_TOKEN` |
| `token_keystore`      | **`environment:`**`bool`<br />**`keychain:`**`bool` | Keystore source(s) to retrieve tokens | `false` <br /> `false` |
| `use_recipe_map`      | `bool`                      | Use recipe --> Kandji mapping from `recipe_map.json`       | `false` |

> [!TIP]
> Set `ENV` values for `KANDJI_API_URL` (`str`) and `ENV_KEYSTORE` (`bool`) to override their settings in `config.json`

#### Optional Keys
| Optional Key          | Accepted Values            | Description                                                         | Default |
|-----------------------|----------------------------|---------------------------------------------------------------------|---------|
| `li_enforcement.delays`  | **`prod:`**`int`<br />**`test:`**`int` | Number of days before app/version enforcement occurs | `5`<br /> `0`
| `zz_defaults.auto_create_app` | `bool`                      | If custom app cannot be found to update, create new         | `true`         |
| `zz_defaults.dry_run` | `bool`                      | Does not modify any Kandji Custom Apps; shows instead what would have run | `false`         |
| `zz_defaults.dynamic_lookup`| `bool`                   | If custom app cannot be found to update, dynamically search and select | `false` |
| `zz_defaults.new_app_naming`      | `str`                       | Custom app naming convention if the name isn't otherwise specified   | `APPNAME (AutoPkg)` |
| `zz_defaults.self_service_category`| `str`                      | Self Service Category for `prod_name` if not otherwise specified          | `Apps` |
| `zz_defaults.test_self_service_category` | `str`               | Self Service Category for `test_name` if not otherwise specified     | `Utilities` |

#### Example config.json
```json
{
  "kandji" : {
    "api_url" : "TENANT.api.kandji.io",
    "token_name" : "KANDJI_TOKEN"
  },
  "li_enforcement" : {
    "delays" : {
      "prod" : 5,
      "test" : 0
    },
    "type" : "install_once"
  },
  "slack" : {
    "enabled" : true,
    "webhook_name" : "SLACK_TOKEN"
  },
  "token_keystore" : {
    "environment" : false,
    "keychain" : false
  },
  "use_recipe_map" : false,
  "zz_defaults" : {
    "auto_create_new_app" : true,
    "dry_run" : false,
    "dynamic_lookup_fallback" : false,
    "new_app_naming" : "APPNAME (AutoPkg)",
    "self_service_category" : "Apps",
    "test_self_service_category" : "Utilities"
  }
}
```

### AutoPkg Recipe Config

#### In-Recipe Keys
| Key           | Type  | Description                                                          |
|---------------|-------|----------------------------------------------------------------------|
| `create_new`  | `bool`| Recipe always creates (vs. updates) a custom app                     |
| `dry_run`  | `bool`| Do not make Custom App modifications; show commands which would have run |
| `custom_app`| `dict`| Dictionary setting custom app behavior         |
| `custom_app.prod_name`   | `str` | Name of custom app to be created/updated                            |
| `custom_app.test_name`   | `str` | Name of test custom app to be created/updated                       |
| `custom_app.ss_category` | `str` | Toggles on Self Service enforcement for `prod_name` and sets category       |
| `custom_app.test_category`| `str`| Toggles on Self Service enforcement for `test_name` and sets category  |


#### Example Recipe/Override XML
```xml
            <dict>
                <key>Processor</key>
                <string>io.kandji.kappa/KAPPA</string>
                <key>Arguments</key>
                <dict>
                    <key>create_new</key>
                    <true/>
                    <key>dry_run</key>
                    <true/>
                    <key>custom_app</key>
                    <dict>
                        <key>prod_name</key>
                        <string>Custom App Name</string>
                        <key>test_name</key>
                        <string>Test Custom App Name</string>
                        <key>ss_category</key>
                        <string>Productivity</string>
                        <key>test_category</key>
                        <string>Utilities</string>
                    </dict>
                </dict>
            </dict>
```
### recipe_map.json

#### Example Recipe Map
```json
{
  "GoogleChrome.pkg": {
    "prod_name": "Google Chrome",
    "test_name": "Google Chrome (Testing)",
    "ss_category": "Productivity",
    "test_category": "Utilities"
  },
  "GoogleDrive.pkg": {
    "prod_name": "Google Drive",
    "test_name": "Google Drive (Testing)"
  },
  "Rectangle.pkg": {
    "prod_name": "Rectangle (Window Manager)",
    "test_name": "Rectangle (Window Manager — Testing)"
  },
  "Thunderbird.pkg": {
    "prod_name": "Thunderbird",
    "test_name": "Thunderbird (Testing)",
    "ss_category": "Productivity",
    "test_category": "Utilities"
  }
}
```

### setup.command Flags

`setup.command` will run through initial setup to populate required variables if invoked without flags.

See below for full usage guide:

```
Usage: ./setup.command [-h/--help|-c/--config|-m/--map|-r/--reset]

Conducts prechecks to ensure all required dependencies are available prior to runtime.
Once confirmed, reads and prompts to populate values in config.json if any are invalid.

Options:
-h, --help                       Show this help message and exit
-c, --config                     Configure config.json with required values for runtime (don't store secrets)
-m, --map                        Populate to CSV usable values for recipe_map.json
-r, --reset                      Prompts to overwrite any configurable variable
```

### Audit Enforcement Examples

> #### App not found
> #### ![#E01E5A](https://via.placeholder.com/15/E01E5A/000000?text=+) Fails audit/triggers install
```
Last Audit - 04/15/2024 at 1:51:31 PM
• Executing audit script...
• Script exited with non-zero status.
• Script results:
• Checking for 'Google Drive.app' install...
• 'Google Drive.app' not found. Triggering install...
```

> #### App found, version enforcement pending
> #### ![#2EB67D](https://via.placeholder.com/15/2EB67D/000000?text=+) Passes audit/skips install
```
Last Audit - 04/15/2024 at 2:02:34 PM
• Executing audit script...
• Script exited with success.
• Script results:
• Checking for 'Google Drive.app' install...
• 'Google Drive.app' installed at '/Applications/Google Drive.app'
• Checking version enforcement...
• Update is due at 2024-04-20 11:49:30 PDT
• Will verify 'Google Drive.app' running at least version '90.0' in 4 days, 23 hours, 46 minutes, 57 seconds
```

> #### App found, version enforcement due
> #### Installed version newer/equal to enforced
> #### ![#2EB67D](https://via.placeholder.com/15/2EB67D/000000?text=+) Passes audit/skips install
```
Last Audit - 04/15/2024 at 2:03:21 PM
• Executing audit script...
• Script exited with success.
• Script results:
• Checking for 'Google Drive.app' install...
• 'Google Drive.app' installed at '/Applications/Google Drive.app'
• Checking version enforcement...
• Enforcement was due at 2024-04-15 11:49:30 PDT
• Confirming 'Google Drive.app' version...
• Installed version '90.0' greater than or equal to enforced version '90.0'
```

> #### App found, version enforcement due
> #### Installed version older than required
> #### User requests one hour delay
> #### ![#2EB67D](https://via.placeholder.com/15/2EB67D/000000?text=+) Passes audit/skips install
```
Last Audit - 04/15/2024 at 2:04:41 PM
• Executing audit script...
• Script exited with success.
• Script results:
• Checking for 'Google Drive.app' install...
• 'Google Drive.app' installed at '/Applications/Google Drive.app'
• Checking version enforcement...
• Enforcement was due at 2024-04-15 11:49:30 PDT
• Confirming 'Google Drive.app' version...
• Installed version '89.0' less than required version '90.0'
• Detected blocking process: 'Google Drive'
• No enforcement delay found for Google Drive.app
• User clicked Delay
• Writing enforcement delay for Google Drive.app to /Library/Preferences/io.kandji.enforcement.delay.plist
```

> #### App found, version enforcement due
> #### Installed version older than required
> #### User delay still active
> #### ![#2EB67D](https://via.placeholder.com/15/2EB67D/000000?text=+) Passes audit/skips install
```
Last Audit - 04/15/2024 at 2:05:20 PM
• Executing audit script...
• Script exited with success.
• Script results:
• Checking for 'Google Drive.app' install...
• 'Google Drive.app' installed at '/Applications/Google Drive.app'
• Checking version enforcement...
• Enforcement was due at 2024-04-15 11:49:30 PDT
• Confirming 'Google Drive.app' version...
• Installed version '89.0' less than required version '90.0'
• Detected blocking process: 'Google Drive'
• Enforcement delay present for Google Drive.app
• User delay still pending; enforcing version 90.0 for Google Drive.app in 0 hours, 58 minutes, 59 seconds
```
> #### App found, version enforcement due
> #### Installed version older than required
> #### App is closed (regardless of user delay)
> #### ![#E01E5A](https://via.placeholder.com/15/E01E5A/000000?text=+) Fails audit/triggers install
```
Last Audit - 04/15/2024 at 2:11:31 PM
• Executing audit script...
• Script exited with non-zero status.
• Script results:
• Checking for 'Google Drive.app' install...
• 'Google Drive.app' installed at '/Applications/Google Drive.app'
• Checking version enforcement...
• Enforcement was due at 2024-04-15 11:49:30 PDT
• Confirming 'Google Drive.app' version...
• Installed version '89.0' less than required version '90.0'
• No running process found for 'Google Drive.app'
• Upgrading 'Google Drive.app' to version '90.0'...
```
> #### App found, version enforcement due
> #### Installed version older than required
> #### User delay has expired
> #### ![#E01E5A](https://via.placeholder.com/15/E01E5A/000000?text=+) Fails audit/triggers install
```
Last Audit - 04/15/2024 at 2:18:05 PM
• Executing audit script...
• Script exited with non-zero status.
• Script results:
• Checking for 'Google Drive.app' install...
• 'Google Drive.app' installed at '/Applications/Google Drive.app'
• Checking version enforcement...
• Enforcement was due at 2024-04-15 11:49:30 PDT
• Confirming 'Google Drive.app' version...
• Installed version '89.0' less than required version '90.0'
• Detected blocking process: 'Google Drive'
• Enforcement delay present for Google Drive.app
• Enforcement delay has expired for Google Drive.app 90.0
• User clicked Quit
• Upgrading 'Google Drive.app' to version '90.0'...
```

