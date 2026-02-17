#!/usr/local/autopkg/python
# Created 01/16/24; NRJA
# Updated 02/20/24; NRJA
# Updated 03/19/24; NRJA
################################################################################################
# License Information
################################################################################################
#
# Copyright 2026 Iru, Inc.
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

#################
##### ABOUT #####
#################

"""Kandji AutoPkg Processor Actions (KAPPA): post-processor for programmatic management of Kandji Custom Apps via AutoPkg"""

#######################
####### IMPORTS #######
#######################

import os
import sys
from pathlib import Path

sys.path.append(Path(__file__).parent.as_posix())
from autopkglib import ProcessorError  # noqa: E402
from helpers.configs import Configurator  # noqa: E402
from helpers.utils import Utilities  # noqa: E402

__all__ = ["KAPPA"]


class KAPPA(Configurator, Utilities):
    description = (
        "Kandji AutoPkg Processor Actions: post-processor for programmatic management of Kandji Custom Apps via AutoPkg"
    )
    input_variables = {
        "NAME": {"required": True, "description": "Name from AutoPkg recipe (used if no custom_name defined)"},
        "pkg_path": {"required": False, "description": "Path of the built PKG for upload"},
        "app_name": {"required": False, "description": "Name of .app in payload (for audit script)"},
        "bundleid": {
            "required": False,
            "description": "Bundle ID of .app in payload (for audit script; used if no val for app_name)",
        },
        "version": {"required": False, "description": "Version of .app in payload (for audit script)"},
        "custom_app": {
            "required": False,
            "description": (
                "A dictionary whose keys are 'prod_name', 'test_name', 'ss_category', 'test_category'"
                "Used to set specify custom app names and Self Service categories"
            ),
        },
        "create_new": {
            "required": False,
            "description": "Boolean to toggle creation of a new LI (default: False)",
        },
        "dry_run": {
            "required": False,
            "description": "Boolean setting KAPPA to execute a dry run, not making actual mods (default: False)",
        },
    }

    output_variables = {}

    __doc__ = description

    ####################################
    ######### PUBLIC FUNCTIONS #########
    ####################################

    def upload_custom_app(self):
        """Calls func to generate S3 presigned URL (response assigned to self.s3_generated_req)
        Formats presigned URL response to cURL syntax valid for form submission, also appending path to PKG
        Assigns upload form and POST URL to vars for cURL execution
        Runs command and validates output when returning self._validate_curl_response()"""

        def _generate_s3_req():
            """Generates an S3 presigned URL to upload a PKG"""
            post_url = self.api_upload_pkg_url
            form_data = f"-F 'name={self.pkg_name}'"
            status_code, response = self._curl_cmd_exec(method="POST", url=post_url, files=form_data)
            return self._validate_curl_response(status_code, response, "presign")

        if not _generate_s3_req():
            return False
        # Ugly way to shell-ify our JSON resp for curl form data
        s3_data = (
            str(self.s3_generated_req.get("post_data"))
            .replace("{", "-F ")
            .replace("': '", "=")
            .replace("', '", "' -F '")
            .replace("}", "")
        )
        # Append PKG path to form data
        s3_data = s3_data + f" -F 'file=@{self.pkg_path}'"
        upload_url = self.s3_generated_req.get("post_url")
        self.s3_key = self.s3_generated_req.get("file_key")
        if self.dry_run is True:
            self.output(f"DRY RUN: Would upload PKG '{self.pkg_path} cURL POST to '{upload_url}'")
            return True
        self.output(f"Beginning file upload of {self.pkg_name}...")
        status_code, response = self._curl_cmd_exec(method="POST", url=upload_url, files=s3_data)
        return self._validate_curl_response(status_code, response, "upload")

    def create_custom_app(self):
        """Assigns creation data and POST URL to vars for cURL execution
        Runs command and validates output when returning self._validate_curl_response()"""
        create_data = f"-F 'name={self.custom_app_name}' -F 'file_key={self.s3_key}' -F 'install_type=package' -F 'install_enforcement={self.custom_app_enforcement}'"
        if self.custom_app_enforcement == "continuously_enforce":
            create_data += f" -F 'audit_script=<{self.audit_script_path}'"
        elif self.custom_app_enforcement == "no_enforcement":
            if self.test_app is True:
                create_data += f" -F 'show_in_self_service=true' -F 'self_service_category_id={self.test_category_id}'"
            else:
                create_data += f" -F 'show_in_self_service=true' -F 'self_service_category_id={self.ss_category_id}'"
        post_url = self.api_custom_apps_url
        if self.dry_run is True:
            self.output(
                f"DRY RUN: Would create Custom App '{self.custom_app_name}' with cURL POST to '{post_url}' and fields '{create_data}'"
            )
            return True
        status_code, response = self._curl_cmd_exec(method="POST", url=post_url, files=create_data)
        return self._validate_curl_response(status_code, response, "create")

    def update_custom_app(self):
        """Assigns update data and PATCH URL to vars for cURL execution
        Runs command and validates output when returning self._validate_curl_response()"""

        # Assign self.custom_apps
        def get_custom_apps():
            """Queries all custom apps from Kandji tenant; assigns GET URL to var for cURL execution
            Runs command and validates output when returning self._validate_curl_response()"""
            get_url = self.api_custom_apps_url
            status_code, response = self._curl_cmd_exec(url=get_url)
            return self._validate_curl_response(status_code, response, "get")

        # Raise if our custom apps GET fails
        if not get_custom_apps():
            raise ProcessorError

        if self.custom_app_name is not None:
            lib_item_dict = self._find_lib_item_match()

        # Returns None if multiple matches, False if no matches
        if lib_item_dict is None:
            return False
        if lib_item_dict is False:
            if self.default_auto_create is True:
                self.output("WARNING: Could not find existing custom app to update — creating as new")
                return self.create_custom_app()
            else:
                self.output("ERROR: Could not locate existing custom app to update")
                self.output("ERROR: Auto-create is disabled — skipping remaining steps")
                return False

        update_data = f"-F 'file_key={self.s3_key}'"

        # Assign existing LI UUID and enforcement
        lib_item_uuid = lib_item_dict.get("id")
        lib_item_enforcement = lib_item_dict.get("install_enforcement")
        # Validate enforcement of existing LI
        if lib_item_enforcement == "continuously_enforce":
            # If existing LI enforcement differs from set value, override var to Kandji value
            if self.custom_app_enforcement != lib_item_enforcement:
                self.output(
                    "Existing app enforcement differs from local config... Deferring to Kandji enforcement type"
                )
                # This info is needed for auditing/enforcement, so split the PKG and find if req values unset
                try:
                    self.app_vers
                    self.output("Skipping PKG expansion as app version already known")
                except (AttributeError, NameError):
                    self.output("Proceeding with PKG expansion to populate ID/version...")
                    self._expand_pkg_get_info()
                # Call audit customization here since not invoked earlier
                self._customize_audit_for_upload()
                self.custom_app_enforcement = lib_item_enforcement
            update_data += f" -F 'audit_script=<{self.audit_script_path}'"
        patch_url = os.path.join(self.api_custom_apps_url, lib_item_uuid)
        if self.dry_run is True:
            self.output(
                f"DRY RUN: Would update Custom App '{self.custom_app_name}' with cURL PATCH to '{patch_url}' and fields '{update_data}'"
            )
            return True
        status_code, response = self._curl_cmd_exec(method="PATCH", url=patch_url, files=update_data)
        return self._validate_curl_response(status_code, response, "update")

    def kandji_customize_create_update(self):
        """Parent function to process any audit script updates and
        either create a net new or update an existing custom app"""
        # Properly escape any single quotes in app name
        self.custom_app_name = self.custom_app_name.replace(r"'", r"'\''")
        self._customize_audit_for_upload() if self.custom_app_enforcement == "continuously_enforce" else True
        if self.recipe_create_new is True:
            self.create_custom_app()
        else:
            self.update_custom_app()
        self._restore_audit() if self.custom_app_enforcement == "continuously_enforce" else True

    def main(self):
        """Main function to execute KAPPA"""
        # Define our variables from recipe input
        # Report var assignments to AutoPKG output
        script_path = Path(__file__).resolve()
        # Capture exec dir path
        self.parent_dir = script_path.parent

        # Ensure pkg_path is defined for post-processing
        if "pkg_path" not in self.env:
            raise ProcessorError("Missing required input variable: pkg_path")

        # Reads config and assigns needed vars for runtime
        # Also validates and populates values for Kandji/Slack (if defined)
        self.populate_from_config()
        self.audit_script_path = os.path.join(self.parent_dir, self.audit_script)
        if self.custom_app_enforcement == "continuously_enforce":
            if (self.app_name is None and self.bundle_id is None) or self.app_vers is None:
                # This info is needed for auditing/enforcement, so split the PKG and find it
                self._expand_pkg_get_info()

        ###################
        #### MAIN EXEC ####
        ###################
        if self.upload_custom_app() is True:
            # Iterate over dict specifying app type and name
            for key, value in self.app_names.items():
                if key == "test_name":
                    self.custom_app_name = value
                    self.test_app, self.prod_app = True, False
                elif key == "prod_name":
                    self.custom_app_name = value
                    self.test_app, self.prod_app = False, True
                else:
                    self.test_app, self.prod_app = False, False
                # Main func for processing Cr/Up ops
                self.kandji_customize_create_update()


##############
#### BODY ####
##############

if __name__ == "__main__":
    processor = KAPPA()
    processor.execute_shell()
