#!/bin/zsh
# Created 02/05/24; NRJA
################################################################################################
# License Information
################################################################################################
#
# Copyright 2024 Kandji, Inc.
#
# Permission is hereby granted, free of charge, to any person obtaining a copy of this
# software and associated documentation files (the "Software"), to deal in the Software
# without restriction, including without limitation the rights to use, copy, modify, merge,
# publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons
# to whom the Software is furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all copies or
# substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED,
# INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR
# PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE
# FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR
# OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
# DEALINGS IN THE SOFTWARE.
#
################################################################################################

#############################
######### ARGUMENTS #########
#############################

# Provide arg support to only set config file
zparseopts -D -E -a opts h -help c -config m -map r -reset
# Set args for help and show message
if (( ${opts[(I)(-h|--help)]} )); then
    /bin/cat <<EOF
Usage: ./setup.command [-h/--help|-c/--config|-m/--map|-r/--reset]

Conducts prechecks to ensure all required dependencies are available prior to runtime.
Once confirmed, reads and prompts to populate values in config.json if any are invalid.

Options:
-h, --help                       Show this help message and exit
-c, --config                     Configure config.json with required values for runtime (don't store secrets)
-m, --map                        Populate to CSV usable values for recipe_map.json
-r, --reset                      Prompts to overwrite any configurable variable
EOF
    exit 0
fi

##############################
########## VARIABLES #########
##############################

# Get username
user=$(/usr/bin/stat -f%Su /dev/console)

# Get local dir name
dir=$(dirname ${ZSH_ARGZERO})
# Assign full path
abs_dir=$(realpath ${dir})
# Hardcoded filename for configs
config_name="config.json"
# Hardcoded filename for configs
config_file="${abs_dir}/${config_name}"

# RE matching for Kandji API URL
kandji_api_re='^[A-Za-z0-9]+\.api(\.eu)?\.kandji\.io$'
# xdigit is an RE pattern match for valid hex chars
kandji_token_re='[[:xdigit:]]{8}(-[[:xdigit:]]{4}){3}-[[:xdigit:]]{12}'
slack_webhook_re='https://hooks.slack.com/services/[[:alnum:]]{9}/[[:alnum:]]{11}/[[:alnum:]]{24}'

# Get login keychain for user
user_keychain_path=$(security login-keychain | xargs)

# AutoPkg download/shasum variables
autopkg_latest_url="https://api.github.com/repos/autopkg/autopkg/releases/latest"
autopkg_pinned_pkg="https://github.com/autopkg/autopkg/releases/download/v2.7.2/autopkg-2.7.2.pkg"
autopkg_pinned_shasum="2ff34daf02256ad81e2c74c83a9f4c312fa2f9dd212aba59e0cef0e6ba1be5c9" # pragma: allowlist secret
autopkg_temp_dl="/tmp/autopkg.pkg"

##############################
########## FUNCTIONS #########
##############################

##############################################
# Formats provided text with ###s to create
# section bodies + headers/footers
##############################################
function format_stdout() {
    body=${1}
    # Formats provided str with #s to create a header
    hashed_body="####### ${body} #######"
    # shellcheck disable=SC2051
    hashed_header_footer=$(printf '#%.0s' {1..$#hashed_body})
    echo "\n\n${hashed_header_footer}\n${hashed_body}\n${hashed_header_footer}\n"
}

##############################################
# Reads in config.json and assigns values
# to global vars; if any are undefined,
# prompts user to populate interactively
# Calls prechecks to validate config
# Globals:
#  config_file
# Assigns:
#  kandji_api
#  kandji_token_name
#  env_store
#  keychain_store
#  slack_enabled
#  slack_token_name
##############################################
function read_config() {
    # Read in configs and assign to vars
    kandji_api=$(plutil -extract kandji.api_url raw -o - "${config_file}")
    kandji_token_name=$(plutil -extract kandji.token_name raw -o - "${config_file}")
    # Ensure at least one enabled keystore val
    env_store=$(plutil -extract token_keystore.environment raw -o - "${config_file}")
    keychain_store=$(plutil -extract token_keystore.keychain raw -o - "${config_file}")
    # Check if Slack enabled and read in webhook name
    slack_enabled=$(plutil -extract slack.enabled raw -o - "${config_file}")
    slack_token_name=$(plutil -extract slack.webhook_name raw -o - "${config_file}")
    use_recipe_map=$(plutil -extract use_recipe_map raw -o - "${config_file}")
}


##############################################
# Prompts interactively to reset existing
# values in config.json as well as stored
# secrets; once value is reset, marked True so
# as to not prompt indefinitely
##############################################
function reset_values() {
    echo "\n$(date +'%r') : Running setup to reset existing values"
    if ! ${reset_kandji_url}; then
        reset_kandji_url=true
        set_kandji_api_url
    fi
    if ! ${reset_keystore}; then
        reset_keystore=true
        set_keystore
    fi
    # Re-read config to update vars
    read_config
    if [[ -n ${kandji_token_name} ]]; then
        if ! ${reset_kandji_token}; then
            token_type="Kandji"
            prompt_store_secret
        fi
    else
        echo "$(date +'%r') : Kandji token name not defined in config!"
        exit 1
    fi

    if [[ ${slack_enabled} == true ]]; then
        if ! ${reset_slack_token}; then
            token_type="Slack"
            prompt_store_secret
        fi
    fi
}


##############################################
# Conducts prechecks to ensure all required
# dependencies are available prior to runtime
# and that existing configs are valid
# If any are found to be invalid, prompts
# user to populate interactively
# Globals:
#  kandji_api
#  kandji_token_name
#  env_store
#  keychain_store
#  slack_enabled
#  slack_token_name
#  config_file
# Assigns:
#  token_type
##############################################
function prechecks() {

    if [[ -z ${kandji_api} || $(grep "TENANT\.api" <<< ${kandji_api}) ]]; then
        echo "\n$(date +'%r') : WARNING: A valid Kandji API URL is not set in ${config_name}"
        set_kandji_api_url
        # Re-read config to update var
        read_config
        # Re-run prechecks to validate change
        prechecks
        # Return to avoid duplicate prompts
        return
    fi

    if [[ ${env_store} != true && ${keychain_store} != true ]]; then
        echo "\n$(date +'%r') : WARNING: No keystore defined in config"
        set_keystore
        # Re-read config to update var
        read_config
        # Re-run prechecks to validate change
        prechecks
        # Return to avoid duplicate prompts
        return
    fi

    if [[ -n ${kandji_token_name} ]]; then
        token_type="Kandji"
        prompt_store_secret
    else
        echo "$(date +'%r') : Kandji token name not defined in config!"
        exit 1
    fi

    if [[ ${slack_enabled} == true && -n ${slack_token_name} ]]; then
        token_type="Slack"
        prompt_store_secret
    fi

    if ! /usr/local/bin/autopkg version >/dev/null 2>&1 && [[ $(uname) == "Darwin" ]]; then
        echo
        if read -q "?No AutoPkg found! Download and install now? (recommended) (Y/N):"; then
            autopkg_dl_install
        fi
    fi

    if /usr/local/bin/autopkg version >/dev/null 2>&1 && [[ $(uname) == "Darwin" ]]; then
        if ! autopkg info io.kandji.kappa -q >/dev/null 2>&1; then
            echo "$(date +'%r') : KAPPA not found in AutoPkg scope; adding now..."
            defaults write com.github.autopkg RECIPE_SEARCH_DIRS -array-add "${abs_dir}"
        fi
    fi
}

##############################################
# Identifies and DLs latest release of AutoPkg
# Validates shasum from known good value
# If shasums differ, DLs pinned version
# Will notify stdout about newer version
# Outputs:
#   Installs AutoPkg to disk
# Returns:
#   Success, else exit 1 and notify on error
##############################################
function autopkg_dl_install() {
    # Grab latest release of AutoPkg
    autopkg_pkg_dl=$(/usr/bin/curl -s -L "${autopkg_latest_url}" | /usr/bin/sed -n -e 's/^.*"browser_download_url": //p' |  /usr/bin/tr -d \")

    # Download it - retry up to 3 more times if it fails
    /usr/bin/curl -s -L --retry 3 "${autopkg_pkg_dl}" -o "${autopkg_temp_dl}"

    # Check that shasum matches latest
    # Could hardcode our pinned version, but want to be alerted for new versions
    if [[ ! $(/usr/bin/shasum -a 256 "${autopkg_temp_dl}" 2>/dev/null  | /usr/bin/awk '{print $1}') == ${autopkg_pinned_shasum} ]]; then
        echo "$(date +'%r') : WARNING: Shasum mismatch for AutoPkg download\nAttempted download from ${autopkg_pkg_dl}; may be a newer version?"
        echo "$(date +'%r') : INFO: Downloading AutoPkg from pinned URL ${autopkg_pinned_pkg}"

        # If we have a shasum mismatch, try downloading the known good package of our pinned version
        autopkg_pkg_dl=${autopkg_pinned_pkg}
        /bin/rm "${autopkg_temp_dl}"
        /usr/bin/curl -L "${autopkg_pkg_dl}" -o "${autopkg_temp_dl}"

        # Confirm shasum of pinned value
        if [[ ! $(/usr/bin/shasum -a 256 "${autopkg_temp_dl}" 2>/dev/null  | /usr/bin/awk '{print $1}') == ${autopkg_pinned_shasum} ]]; then
            echo "$(date +'%r') : CRITICAL: Shasum mismatch for AutoPkg download\nAttempted download from ${autopkg_pinned_pkg}, but shasum check failed!"
            exit 1
        fi
    fi

    echo "$(date +'%r') : AutoPkg download complete — beginning install..."
    echo "$(date +'%r') : INFO: You may be sudo prompted to complete AutoPkg installation"

    # Install AutoPkg
    sudo /usr/sbin/installer -pkg "${autopkg_temp_dl}" -target / 2>/dev/null

    # Validate success
    exit_code=$?

    if [[ "${exit_code}" == 0 ]]; then
        echo "$(date +'%r') : Successfully installed AutoPkg"
    else
        echo "$(date +'%r') : ERROR: AutoPkg install failed with error code ${exit_code}"
        exit 1
    fi

    # Remove temp DL
    /bin/rm "${autopkg_temp_dl}"
}

##############################################
# Validates specified token type and assigns
# token_name to align with indicated type
# Globals:
#   token_type
# Assigns:
#   token_name
# Returns:
#   1 if assigned val token_type is invalid
##############################################
function assign_token_name() {
    case ${token_type} in
        "Kandji")
            token_name=${kandji_token_name}
            secret_regex_pattern=${kandji_token_re}
            reset_token="reset_kandji_token"
            ;;
        "Slack")
            token_name=${slack_token_name}
            secret_regex_pattern=${slack_webhook_re}
            reset_token="reset_slack_token"
            ;;
        *)
            echo "$(date +'%r') : CRITICAL: Token type must be one of either Kandji or Slack!"
            return 1
            ;;
    esac
}

##############################################
# Prompts interactively to set Kandji API URL
# Once API URL is validated, writes to config
# Globals:
#  kandji_api_re
#  config_file
#  CONFIG_VALUE
# Outputs:
#  Writes input string to config.json
##############################################
function set_kandji_api_url() {
    value_regex_pattern=${kandji_api_re}
    prompt_for_value "Kandji API URL" "INSTANCE.api(.eu).kandji.io"
    plutil -replace kandji.api_url -string ${CONFIG_VALUE} -r "${config_file}"
}

##############################################
# Prompts interactively to set keystore
# for token storage; func recursively calls
# self until at least one keystore is defined
# Outputs:
#  Writes input bool to config.json
##############################################
function set_keystore() {
    echo
    if read -q "?Use ENV for token storage? (Y/N):"; then
        plutil -replace token_keystore.environment -bool true -r "${config_file}"
    else
        plutil -replace token_keystore.environment -bool false -r "${config_file}"
    fi
    echo
    if read -q "?Use keychain for token storage? (Y/N):"; then
        plutil -replace token_keystore.keychain -bool true -r "${config_file}"
    else
        plutil -replace token_keystore.keychain -bool false -r "${config_file}"
    fi
}

##############################################
# Prompts interactively to assign value
# to entry; func recursively calls self until
# value is defined or user interrupts w/SIGINT
# Arguments:
#  key_name; ${1}
#  example_val; ${2}
# Assigns:
#   CONFIG_VALUE
# Returns:
#   Recursively calls func if no val provided
##############################################
function prompt_for_value() {
    key_name=${1}
    example_val=${2}
    echo
    read "CONFIG_VALUE?Enter value for ${key_name} (e.g. ${example_val}):
"
    if [[ -n ${CONFIG_VALUE} ]]; then
        if grep -q -w -E "${value_regex_pattern}" <<< "${CONFIG_VALUE}"; then
            return 0
        else
            echo "\n$(date +'%r') : Provided value did not match expected sequence!"
            echo "$(date +'%r') : Accepted format is ${example_val}"
            echo "$(date +'%r') : Validate your input and try again; press CTRL+C to exit"
            prompt_for_value ${key_name} ${example_val}
        fi
    else
        echo "\n$(date +'%r') : No value provided!"
        echo "$(date +'%r') : Validate your input and try again; press CTRL+C to exit"
        prompt_for_value ${key_name} ${example_val}
    fi
}

##############################################
# Prompts interactively to assign secret value
# to entry; func recursively calls self until
# token is defined or user interrupts w/SIGINT
# Globals:
#   token_type
# Assigns:
#   BEARER_TOKEN
# Returns:
#   Recursively calls func if no val provided
##############################################
function prompt_for_secret() {
    echo
    read -s "BEARER_TOKEN?Enter ${token_type} token value: "
    if [[ -n ${BEARER_TOKEN} ]]; then
        if grep -q -w -E "${secret_regex_pattern}" <<< "${BEARER_TOKEN}"; then
            return 0
        else
            echo "\n$(date +'%r') : Provided token did not match expected sequence!"
            echo "$(date +'%r') : Validate your input and try again; press CTRL+C to exit"
            prompt_for_secret
        fi
    else
        echo "\n$(date +'%r') : No value provided for token!"
        echo "$(date +'%r') : Validate your input and try again; press CTRL+C to exit"
        prompt_for_secret
    fi
}

##############################################
# Retrieves token from ENV or keychain
# based on config settings; assigns token to
# global for API calls elsewhere
# Arguments:
#  token_name; ${1}
# Assigns:
#  BEARER_TOKEN
##############################################
function retrieve_token() {
    token_name=${1}
    unset BEARER_TOKEN
    if [[ ${env_store} == true ]]; then
        BEARER_TOKEN=${(P)token_name}
    fi
    if [[ -z ${BEARER_TOKEN} && ${keychain_store} == true ]]; then
        BEARER_TOKEN=$(security find-generic-password -w -a "KAPPA" -s ${token_name})
    fi
}

##############################################
# Checks config; if ENV is set to true,
# searches for token by name. If not found,
# prompts user to store secret in ENV
# Func calls itself to validate successful
# lookup of secret from ENV once stored
# Globals:
#   config_file
#   token_name
#   token_type
# Outputs:
#   Writes secret to ENV if not found
##############################################
function check_store_env() {
    # Validate expected secrets are stored if using ENV
    if [[ ${env_store} == true ]]; then
        # Check if env is undefined
        if [[ ! -v ${token_name} ]] || (( ${opts[(I)(-r|--reset)]} )); then
            echo
            if (( ${opts[(I)(-r|--reset)]} )) && check_set_reset_var; then
                return 0
            fi
            if read -q "?Store ${token_type} token in ENV? (Y/N):"; then
                prompt_for_secret "${token_type}"
                user_shell=$(dscl . -read /Users/${user} UserShell | cut -d ":" -f2)
                if grep -q -i zsh <<< ${user_shell}; then
                    dotfile_name=".zshenv"
                elif grep -q -i bash <<< ${user_shell}; then
                    dotfile_name=".bash_profile"
                else
                    dotfile_name=".profile"
                fi
                # shellcheck disable=SC1090
                echo "export ${token_name}=${BEARER_TOKEN}" >> "/Users/${user}/${dotfile_name}" && source "/Users/${user}/${dotfile_name}"
                check_store_env
            fi
        else
            echo "\n$(date +'%r') : Valid ${token_type} token set in ENV"
        fi
    fi
}

##############################################
# Checks if reset flag is set; if true, checks
# if specified token is True; if so returns 0
# If not, sets token to true and returns 1
# Globals:
#  reset_token
# Assigns:
#  reset_token
##############################################
function check_set_reset_var() {
    if ${(P)reset_token}; then
        return 0
    fi
    # Have to eval here because reset_token could be Kandji or Slack
    eval ${reset_token}=true
    return 1
}

##############################################
# Checks config; if keychain is set to true,
# searches for token by name. If not found,
# prompts user to store secret in keychain
# (may prompt for PW to first unlock user KC)
# Func calls itself to validate successful
# lookup of secret from keychain once stored
# Globals:
#   token_type
# Outputs:
#   Writes secret to keychain if not found
##############################################
function check_store_keychain() {

    # Validate expected secrets are stored if using keychain
    if [[ ${keychain_store} == true ]]; then
        # Check if keychain value for name is undefined; also proceed is reset flag is set
        if ! security find-generic-password -a "KAPPA" -s ${token_name} >/dev/null 2>&1 || (( ${opts[(I)(-r|--reset)]} )); then
            echo
            if (( ${opts[(I)(-r|--reset)]} )) && check_set_reset_var; then
                return 0
            fi
            if read -q "?Store ${token_type} token in user keychain? (Y/N):"; then
                prompt_for_secret "${token_type}"
                echo "\n$(date +'%r') : Adding token to login keychain"
                echo "$(date +'%r') : Enter your password if prompted to unlock keychain"
                if ! security unlock-keychain -u; then
                    echo "$(date +'%r') : ERROR: Unable to unlock keychain; exiting"
                    exit 1
                fi
                security add-generic-password -U -a "KAPPA" -s "${token_name}" -w "${BEARER_TOKEN}" \
                -T "/usr/bin/security" -T "${ZSH_ARGZERO}" ${user_keychain_path}
                check_store_keychain
            fi
        else
            echo "\n$(date +'%r') : Valid ${token_type} token set in keychain"
        fi
    fi
}

##############################################
# Assigns token name from provided type
# Checks if ENV and/or keychain set for token
# storage; if true and token not set, prompts
# interactively to place token in store
# Globals:
#   token_type
##############################################
function prompt_store_secret() {
    if [[ ${config_only} == true ]]; then
        echo "\n$(date +'%r') : Running config-only; skipping secrets storage on host"
        return 0
    fi
    assign_token_name
    # Reset for each keystore method
    eval ${reset_token}=false
    check_store_env
    eval ${reset_token}=false
    check_store_keychain
}

##############################################
# Populates values for AutoPkg recipes,
# custom apps, and Self Service categories
# Calls Kandji API to get custom apps and
# Self Service categories; uses AutoPkg to
# list recipes
# Outputs:
#  Writes to recipe_map_values.csv
#  Opens recipe_map_values.csv in default CSV viewer
# Globals:
#  kandji_api
#  api_token
# Outputs:
#  Writes recipe_map_values.csv to disk
##############################################
function populate_values_for_map() {

    unset autopkg_recipes custom_apps ss_categories
    declare -a autopkg_recipes custom_apps ss_categories

    # Define API endpoints
    custom_apps_api="${kandji_api}/api/v1/library/custom-apps"
    self_service_api="${kandji_api}/api/v1/self-service/categories"
    retrieve_token "${kandji_token_name}"
    if [[ -z ${BEARER_TOKEN} ]]; then
        echo "$(date +'%r') : WARNING: Valid Kandji token not found!"
        if read -q "?Provide Kandji token now for mapping? (Y/N):"; then
            token_type="Kandji"
            assign_token_name
            prompt_for_secret
        else
            echo "\n$(date +'%r') : CRITICAL: Kandji token not found in ENV or keychain!"
            echo "$(date +'%r') : CRITICAL: Please provide a valid token when prompted\nAlternatively, run ./setup.command to populate your config"
            exit 1
        fi
    fi
    echo "$(date +'%r') : Populating available AutoPkg recipes, Custom Apps, and Self Service categories..."
    echo "$(date +'%r') : Once recipe_map_values.csv is written, it will open in your default CSV viewer"
    echo "$(date +'%r') : Fill out recipe_map.json using values from created CSV"
    kandji_token=${BEARER_TOKEN}

    if ! /usr/local/bin/autopkg version >/dev/null 2>&1 && [[ $(uname) == "Darwin" ]]; then
        echo "$(date +'%r') : WARNING: No AutoPkg install found!"
        echo "$(date +'%r') : WARNING: Skipping population of available recipes..."
        autopkg_recipes=()
    else
        # Create array of autopkg recipes
        # zsh splits entries by newline with (f)
        autopkg_recipes=("${(f)$(autopkg list-recipes)}") 2>/dev/null
    fi

    # Populate custom app and Self Service category arrays
    custom_apps_out=$(curl -s -L -X GET -H 'Content-Type application/json' -H "Authorization: Bearer ${kandji_token}" "${custom_apps_api}")
    ss_categories_out=$(curl -s -L -X GET -H 'Content-Type application/json' -H "Authorization: Bearer ${kandji_token}" "${self_service_api}")
    # Get counts of custom apps and Self Service categories for iteration
    custom_app_count=$(plutil -extract results raw -o - - <<< ${custom_apps_out})
    ss_category_count=$(plutil -convert raw -o - - <<< ${ss_categories_out})

    # Iterate through results, extract name, and append to array
    # shellcheck disable=SC2051
    for i in {0..$(( ${custom_app_count} - 1 ))}; do
        # shellcheck disable=SC2034
        custom_app_name=$(plutil -extract results.${i}.name raw -o - - <<< ${custom_apps_out})
        # Split on newline and append to array
        # shellcheck disable=SC2206
        custom_apps+=(${(f)custom_app_name})
    done

    # shellcheck disable=SC2051
    for i in {0..$(( ${ss_category_count} - 1 ))}; do
        # shellcheck disable=SC2034
        self_service_name=$(plutil -extract ${i}.name raw -o - - <<< ${ss_categories_out})
        # Split on newline and append to array
        # shellcheck disable=SC2206
        ss_categories+=("${(f)self_service_name}")
    done

    echo "\n$(date +'%r') : Found ${#autopkg_recipes} AutoPkg recipes, ${#custom_apps} custom apps, and ${#ss_categories} Self Service categories"

    echo "AutoPkg Recipes,Custom Apps,Self Service Categories" > "${abs_dir}/recipe_map_values.csv"
    # Get highest count of arrays to iterate through
    highest_count=$((${#autopkg_recipes} > ${#custom_apps} ? ${#autopkg_recipes} : ${#custom_apps}))
    # shellcheck disable=SC2051
    for i in {1..${highest_count}}; do
        echo "${autopkg_recipes[i]},${custom_apps[i]},${ss_categories[i]}" >> "${abs_dir}/recipe_map_values.csv"
    done

    if [[ ${use_recipe_map} != true ]]; then
        echo "$(date +'%r') : Recipe map currently inactive"
        if read -q "?Enable it now? (from recipe_map.json) (Y/N):"; then
            plutil -replace use_recipe_map -bool true -r "${config_file}"
            use_recipe_map=true
            echo "$(date +'%r') : Recipe map enabled"
        fi
    fi

    echo "\n$(date +'%r') : Populated recipe_map_values.csv with AutoPkg recipes, custom apps, and Self Service categories"
    echo "$(date +'%r') : Opening recipe_map_values.csv in default CSV viewer"
    open "${abs_dir}/recipe_map_values.csv"
}

##############################################
# Checks config; assigns name of Kandji token
# and optional Slack token; if Kandji token
# undefined in config, returns 1 for err
# Validates defined tokens are placed in
# designated keystore(s) and if not found,
# prompts interactively for user to populate
# Globals:
#   config_file
# Assigns:
#   token_type
#   kandji_token_name
#   slack_token_name
##############################################
# shellcheck disable=SC2120
function main() {

    if [[ "${EUID}" -eq 0 ]]; then
        echo "$(date +'%r') : setup.command should NOT be run as superuser! Exiting..."
        exit 1
    fi

    format_stdout "Kandji AutoPkg Processor Actions (KAPPA)"
    # Check opts array to ensure no arguments are passed in
    if [[ -z $(printf '%s\n' "${(@)opts}") ]]; then
        # No args is default program
        format_stdout "KAPPA Initial Setup"
    fi

    # Read in config and assign values to vars
    read_config
    if (( ${opts[(I)(-m|--map)]} )); then
        format_stdout "KAPPA Mapping Starting"
        populate_values_for_map
        format_stdout "KAPPA Mapping Complete"
        exit 0
    fi

    if (( ${opts[(I)(-r|--reset)]} )); then
        format_stdout "KAPPA Reset Starting"
        reset_kandji_url=false
        reset_keystore=false
        reset_kandji_token=false
        reset_slack_token=false
        reset_values
        format_stdout "KAPPA Reset Complete"
        exit 0
    fi

    # If flag is set for config-only, don't offer to store secrets
    if (( ${opts[(I)(-c|--config)]} )); then
        format_stdout "KAPPA Config Only"
        config_only=true
    else
        config_only=false
    fi

    # Run prechecks to validate config file and on-disk
    prechecks

    format_stdout "KAPPA Setup Complete"
}

###############
##### MAIN ####
###############

main
