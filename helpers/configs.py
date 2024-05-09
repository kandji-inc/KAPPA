#!/usr/local/autopkg/python
# Created 01/16/24; NRJA
# Updated 02/20/24; NRJA
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

#######################
####### IMPORTS #######
#######################

import json
import os

from autopkglib import Processor, ProcessorError


class Configurator(Processor):
    """Reads and sets variables based on configured settings"""

    #####################################
    ######### PRIVATE FUNCTIONS #########
    #####################################

    def _parse_enforcement(self, enforcement):
        """Translates provided enforcement val between config values and API-valid values"""
        match enforcement.lower():
            case "audit_enforce":
                parsed_enforcer = "continuously_enforce"
            case "self_service":
                parsed_enforcer = "no_enforcement"
            case "continuously_enforce":
                parsed_enforcer = "audit_enforce"
            case "no_enforcement":
                parsed_enforcer = "self_service"
            case "install_once":
                parsed_enforcer = "install_once"
            case _:
                return False
        return parsed_enforcer

    def _read_config(self, kandji_conf):
        """Read in configuration from defined conf path
        Building out full path to read and load as JSON data
        Return loaded JSON data once existence and validity are confirmed"""
        # Have to derive path this way in order to get the execution file origin
        kandji_conf_path = os.path.join(self.parent_dir, kandji_conf)
        if not os.path.exists(kandji_conf_path):
            self.output(f"ERROR: KAPPA config not found at {kandji_conf_path}! Validate its existence and try again")
            return False
        try:
            with open(kandji_conf_path) as f:
                custom_config = json.loads(f.read())
        except ValueError as ve:
            self.output(
                f"ERROR: Config at {kandji_conf_path} is not valid JSON!\n{ve} — validate file integrity for {kandji_conf} and try again"
            )
            return False
        return custom_config

    def _populate_from_recipe(self):
        """Checks for any optional values assigned in-recipe
        Assigns values if defined, else None"""
        ############################
        # Populate Vars from Recipe
        ############################

        self.recipe_custom_name, self.recipe_test_name, self.recipe_ss_category, self.recipe_test_category = (
            None,
            None,
            None,
            None,
        )

        # Query from recipe and assign values
        self.recipe_create_new = self.env.get("create_new", None)
        # Check if recipe was set to skip custom app creation
        self.recipe_dry_run = self.env.get("dry_run", None)
        # Assign dict with custom app info
        self.recipe_custom_app = self.env.get("custom_app", None)
        if self.recipe_custom_app:
            self.recipe_custom_name = self.recipe_custom_app.get("prod_name", None)
            self.recipe_test_name = self.recipe_custom_app.get("test_name", None)
            self.recipe_ss_category = self.recipe_custom_app.get("ss_category", None)
            self.recipe_test_category = self.recipe_custom_app.get("test_category", None)

        # Use recipe path to define recipe name
        recipe_path = self.env.get("RECIPE_PATH", None)
        if recipe_path is not None:
            self.recipe_name = os.path.basename(recipe_path)
        else:
            self.recipe_name = self.name_in_recipe

    def _populate_recipe_map(self):
        """Checks if recipe map is enabled and iters
        to match recipe with custom app name(s)/env(s)"""

        ############################
        # Populate Vars from Mapping
        ############################

        self.app_names = {}
        if self.kappa_config.get("use_recipe_map") is True:
            self.recipe_map = self._read_config(self.recipe_map_file)
            if self.recipe_map is False:
                self.output("ERROR: Recipe map is enabled, but config is invalid!")
                raise ProcessorError("ERROR: Recipe map is enabled, but config is invalid!")
            for recipe, apps in self.recipe_map.items():
                # Once matching recipe found, assign and exit loop
                if recipe in self.recipe_name:
                    self.app_names = apps
                    break
            if not self.app_names:
                self.output(f"WARNING: Recipe map enabled, but no match found for recipe '{self.recipe_name}'!")
                self.output("Will use defaults if no in-recipe values set")

        self.map_ss_category = self.app_names.get("ss_category")
        self.map_test_category = self.app_names.get("test_category")

        # Once assigned, remove from dict
        # This ensures we're only iterating over app names
        try:
            self.app_names.pop("ss_category")
        except KeyError:
            pass
        try:
            self.app_names.pop("test_category")
        except KeyError:
            pass

    def _set_defaults_enforcements(self):
        """Reads JSON config and sets enforcement based on
        defined value, otherwise defaults to install once"""
        if (default_vals := self.kappa_config.get("zz_defaults")) is not None:
            self.default_auto_create = default_vals.get("auto_create_app")
            self.default_custom_name = default_vals.get("new_app_naming")
            self.default_dry_run = default_vals.get("dry_run")
            self.default_dynamic_lookup = default_vals.get("dynamic_lookup")
            self.default_ss_category = default_vals.get("self_service_category")
            self.test_default_ss_category = default_vals.get("test_self_service_category")

        config_enforcement = self.kappa_config.get("li_enforcement")
        enforcement_type = self._parse_enforcement(config_enforcement.get("type"))
        # Check if enforcement type specified, else default to once
        # May be overridden later based on recipe-specific mappings
        self.custom_app_enforcement = (
            "no_enforcement"
            if (self.map_ss_category or self.recipe_ss_category or self.recipe_test_category) is not None
            else enforcement_type
            if enforcement_type
            else "install_once"
        )
        # Assign enforcement delays for audits
        if config_enforcement.get("delays"):
            self.test_delay = config_enforcement.get("delays").get("test")
            self.prod_delay = config_enforcement.get("delays").get("prod")

        self.dry_run = False
        if (self.recipe_dry_run or self.default_dry_run) is True:
            self.output(f"DRY RUN: {self.recipe_name} will not make any Custom App modifications!\n\n\n")
            self.dry_run = True

    def _set_custom_name(self):
        """Sets and populates self.app_names dict for later iter"""
        # If not in config, check if custom name(s) defined within recipe
        if self.recipe_custom_name is not None:
            self.app_names["prod_name"] = self.recipe_custom_name
        # If prod and test names defined, assign to dict (overwriting if necessary)
        if self.recipe_test_name is not None:
            self.app_names["test_name"] = self.recipe_test_name
        if not self.app_names:
            if self.default_custom_name is not None:
                self.custom_app_name = self.default_custom_name.replace("APPNAME", self.name_in_recipe)
            # All else fails, assign as recipe name (AutoPkg)
            else:
                self.custom_app_name = f"{self.name_in_recipe} (AutoPkg)"
            self.app_names["undefined"] = self.custom_app_name

    def _populate_self_service(self):
        def get_self_service():
            """Queries all Self Service categories from Kandji tenant; assigns GET URL to var for cURL execution
            Runs command and validates output when returning self._validate_curl_response()"""
            get_url = f"{self.kandji_api_prefix}/self-service/categories"
            status_code, response = self._curl_cmd_exec(url=get_url)
            return self._validate_curl_response(status_code, response, "get_selfservice")

        def name_to_id(ss_name, ss_type):
            """Iterates over self_service list and assigns category ID to var"""
            # Iter over and find matching id for name
            ss_default = (
                self.default_ss_category
                if ss_type == "prod"
                else self.test_default_ss_category
                if ss_type == "test"
                else None
            )
            try:
                ss_assignment = next(
                    category.get("id") for category in self.self_service if category.get("name") == ss_name
                )
            except StopIteration:
                self.output(f"WARNING: Provided category '{ss_name}' not found in Self Service!") if ss_name is not None else None
                try:
                    # Set category id to default (None check performed later)
                    ss_assignment = (
                        next(category.get("id") for category in self.self_service if category.get("name") == ss_default)
                        if ss_default
                        else None
                    )
                except StopIteration:
                    self.output(f"WARNING: Default category '{ss_default}' not found in Self Service!")
                    ss_assignment = None
            # Only reassign/override if not already set
            if ss_type == "prod":
                if ss_name is not None:
                    self.ss_category_id = ss_assignment
                else:
                    self.ss_category_id = self.ss_category_id if self.ss_category_id is not None else ss_assignment
            elif ss_type == "test":
                if ss_name is not None:
                    self.test_category_id = ss_assignment
                else:
                    self.test_category_id = (
                        self.test_category_id if self.test_category_id is not None else ss_assignment
                    )

        # Set category IDs to None
        self.ss_category_id, self.test_category_id = None, None

        get_self_service()  # assigns list of dicts to self.self_service

        # Create and iter over ad hoc lists with categories/envs
        # If both recipe and mapping values defined, override with values set in recipe
        for cat, env in zip(
            [self.map_ss_category, self.map_test_category, self.recipe_ss_category, self.recipe_test_category],
            ["prod", "test", "prod", "test"],
        ):
            name_to_id(cat, env)

    def _set_slack_config(self):
        """Checks if Slack token name is in config
        Looks up webhook and assigns for use in self.slack_notify()"""

        # Check Slack setting and get/assign webhook
        self.slack_token_name = (
            self.kandji_slack_opts.get("webhook_name") if self.kandji_slack_opts.get("enabled") is True else None
        )
        self.slack_channel = self._retrieve_token(self.slack_token_name) if self.slack_token_name is not None else None

    def _set_kandji_config(self):
        """Validates provided Kandji API URL is valid for use
        Assigns prefix used for API calls + bearer token"""

        # Overwrite Kandji API URL from ENV or keep as set in config
        self.kandji_api_url = os.environ.get("KANDJI_API_URL", self.kandji_api_url)

        # Confirm provided Kandji URL is valid
        status_code, response = self._curl_cmd_exec(url=self.kandji_api_url.replace("api", "web-api"))
        if "tenantNotFound" in response.values():
            self.output(f"ERROR: Provided Kandji URL {self.kandji_api_url} appears invalid! Cannot upload...")
            raise ProcessorError(f"ERROR: Provided Kandji URL {self.kandji_api_url} appears invalid! Cannot upload...")

        # Assign tenant URL
        self.tenant_url = self.kandji_api_url.replace(".api.", ".")
        # Assign API domain
        self.kandji_api_prefix = os.path.join(self.kandji_api_url, "api", "v1")
        # Define API endpoints
        self.api_custom_apps_url = os.path.join(self.kandji_api_prefix, "library", "custom-apps")
        self.api_upload_pkg_url = os.path.join(self.api_custom_apps_url, "upload")
        self.api_self_service_url = os.path.join(self.kandji_api_prefix, "self-service", "categories")

        # Grab auth token for Kandji API interactions
        self.kandji_token = self._retrieve_token(self.kandji_token_name)

    ####################################
    ######### PUBLIC FUNCTIONS #########
    ####################################

    def populate_from_config(self):
        """Read in configuration from defined conf path
        Building out full path to read and load as JSON data
        Return loaded JSON data once existence and validity are confirmed"""
        # Hardcoded filenames for configs
        self.config_file = "config.json"
        self.recipe_map_file = "recipe_map.json"
        self.audit_script = "audit_app_and_version.zsh"

        # If env-specific custom app name(s) are defined for this recipe, these'll be overwritten below
        self.test_app, self.prod_app, self.custom_app_name = False, False, None
        # Assign vars from AutoPkg ENV
        # App bundle metadata
        self.name_in_recipe = self.env.get("NAME")
        self.app_name = self.env.get("app_name", None)
        self.bundle_id = self.env.get("bundleid", None)
        self.app_vers = self.env.get("version", None)
        # PKG metadata
        self.pkg_path = self.env.get("pkg_path")
        self.pkg_name = os.path.basename(self.pkg_path)

        # Populate config
        self.kappa_config = self._read_config(self.config_file)
        if self.kappa_config is False:
            raise ProcessorError("ERROR: Config is invalid! Confirm file integrity and try again")
        try:
            kandji_conf = self.kappa_config["kandji"]
            self.kandji_api_url = kandji_conf["api_url"]
            self.kandji_token_name = kandji_conf["token_name"]
            self.token_keystores = self.kappa_config["token_keystore"]
            # Overwrite keystore conf from ENV if set
            if "ENV_KEYSTORE" in os.environ:
                self.token_keystores["environment"] = True
            # Sanity check values before continuing
            if "TENANT" in self.kandji_api_url:
                self.output("ERROR: Kandji API URL is invalid! Run 'setup.command' and try again")
                raise ProcessorError("ERROR: Kandji API URL is invalid! Run 'setup.command' and try again")
            if not any(self.token_keystores.values()):
                self.output("ERROR: Token keystore is undefined! Run 'setup.command' and try again")
                raise ProcessorError("ERROR: Token keystore is undefined! Run 'setup.command' and try again")
            self.kandji_slack_opts = self.kappa_config["slack"]
        except KeyError as err:
            self.output(f"ERROR: Required key(s) are undefined! {' '.join(err.args)}")
            raise ProcessorError(f"ERROR: Required key(s) are undefined! {' '.join(err.args)}")

        self._populate_from_recipe()
        self._populate_recipe_map()
        self._set_defaults_enforcements()
        self._set_custom_name()
        self._set_slack_config()
        self._set_kandji_config()
        self._populate_self_service()
