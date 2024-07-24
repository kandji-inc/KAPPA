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

import difflib
import json
import os
import plistlib
import re
import shlex
import shutil
import tempfile
import time
import xml.etree.ElementTree as ETree
from datetime import datetime
from fileinput import FileInput
from functools import reduce
from pathlib import Path, PosixPath
from subprocess import PIPE, STDOUT, run
from urllib.parse import urlsplit, urlunsplit

from autopkglib import Processor, ProcessorError
from pip._vendor.packaging import version as packaging_version


class Utilities(Processor):
    #####################################
    ######### PRIVATE FUNCTIONS #########
    #####################################

    def _run_command(self, shell_exec):
        """Runs a shell command and returns the response"""
        raw_out = run(shlex.split(shell_exec), stdout=PIPE, stderr=STDOUT, shell=False, check=False)
        exit_code = raw_out.returncode
        decoded_out = raw_out.stdout.decode().strip()
        if exit_code > 0:
            self.output(f"ERROR: '{shell_exec}' failed with exit code {exit_code} and output '{decoded_out}'")
            return False
        return decoded_out

    def _ensure_https(self, url):
        """Parses provided URL, formats, and returns to ensure proper scheme for cURL"""
        parsed_url = urlsplit(url)
        if not parsed_url.scheme or parsed_url.scheme == "http":
            netloc = parsed_url.netloc if parsed_url.netloc else parsed_url.path
            path = parsed_url.path if parsed_url.netloc else ""
            new_url = parsed_url._replace(scheme="https", netloc=netloc, path=path)
            return urlunsplit(new_url)
        return url

    ######################
    # cURL Wrapper Funcs
    ######################

    def _curl_cmd_exec(self, method="GET", url=None, files=None, data=None):
        """Wrapper for cURL which includes HTTP response code line broken after response
        Default method is GET, with support for POST and PATCH along with form and data submissions
        Assigns received output to json_body and http_code, where json_body is created from response
        if not received directly from server; returns http_code and json_body"""
        curl_prefix = f'curl -sw "\n%{{response_code}}" -L -X {method}'
        curl_headers = '-H "Content-Type application/json"'
        url = self._ensure_https(url)
        # For Kandji client API interactions
        if "kandji.io/api" in url.lower():
            curl_headers = curl_headers + f' -H "Authorization: Bearer {self.kandji_token}"'
            curl_prefix = curl_prefix + " --url-query source=KAPPA"
        curl_shell_exec = f"{curl_prefix} {curl_headers} {url} "
        curl_shell_exec = (
            curl_shell_exec + files
            if files
            else curl_shell_exec + f"--data-urlencode '{data}'"
            if data
            else curl_shell_exec
        )
        # Shell out to cURL and validate success
        raw_out = run(curl_shell_exec, stdout=PIPE, stderr=STDOUT, shell=True, check=False)
        exit_code = raw_out.returncode
        decoded_out = raw_out.stdout.decode().strip()
        if exit_code > 0:
            self.output(f"ERROR: cURL command failed with exit code {exit_code} and output {decoded_out}")
            return False, False
        # Split response code from output
        line_broken_out = decoded_out.splitlines()
        match len(line_broken_out):
            # No response, so assign json_body to received HTTP code
            case 1:
                http_code = int(decoded_out)  # HTTP Response
                json_body = {"HTTP Status Code", http_code}  # JSON body
            case _:
                try:
                    http_code = "".join(line_broken_out[-1])
                    response_body = "".join(line_broken_out[:-1])
                except IndexError as err:
                    self.output(f"Got {line_broken_out} and {decoded_out} with error {err}")
                try:
                    json_body = json.loads(response_body)  # JSON body
                except json.decoder.JSONDecodeError:
                    json_body = {"cURL Response": str(response_body)}

        http_code = int(http_code)  # HTTP Response
        return http_code, json_body

    def _validate_curl_response(self, http_code, response, action):
        """Check HTTP response from cURL command; if healthy, take action
        according to the provided method where "get" assigns list of custom apps to var;
        "get_selfservice" populates categories from Self Service; "presign" assigns S3 response for upload URL
        "upload" reports upload success; "create"/"update" reports success, posting Custom App details to Slack
        HTTP response of 503 means an upload is still processing and will retry after 5 seconds
        Anything else is treated as an error and notifies to Slack with HTTP code and response
        Identified HTTP code 401 adds language to validate permissions for the passed token"""
        if http_code <= 204:
            # Identify specified action and invoke func
            match action.lower():
                case "get":
                    self.custom_apps = response.get("results")
                case "get_selfservice":
                    self.self_service = response
                case "presign":
                    self.s3_generated_req = response
                case "upload":
                    self.output(f"Successfully uploaded {self.pkg_name}!")
                    # Initial sleep allowing S3 to process upload
                    time.sleep(5)
                case "create" | "update":
                    custom_app_id = response.get("id")
                    custom_name = response.get("name")
                    custom_app_enforcement = response.get("install_enforcement")
                    config_named_enforcement = self._parse_enforcement(custom_app_enforcement)
                    custom_app_url = os.path.join(self.tenant_url, "library", "custom-apps", custom_app_id)
                    self.output(f"SUCCESS: Custom App {action.capitalize()}")
                    self.output(f"Custom App '{custom_name}' available at '{custom_app_url}'")
                    self.slack_notify(
                        "SUCCESS",
                        f"Custom App {action.capitalize()}d",
                        f"*Name*: `{custom_name}`\n*ID*: `{custom_app_id}`\n*PKG*: `{self.pkg_name}`\n*Enforcement*: `{config_named_enforcement}`",
                        f"{custom_app_url}",
                    )
                case _:
                    self.output(
                        f"Assignment for 'action' must be one of [get|get_selfservice|presign|upload|create|update]; got '{action}'"
                    )
                    raise ProcessorError(f"Assignment for 'action' must be one of [get|get_selfservice|presign|upload|create|update]; got '{action}'")
            return True
        elif http_code == 503 and (action.lower() == "update" or "create"):
            self.output(f"WARNING: (HTTP {http_code}): {response.get('detail')}\nRetrying in five seconds...")
            time.sleep(5)
            return (
                self.create_custom_app()
                if action.lower() == "create"
                else self.update_custom_app()
                if action.lower() == "update"
                else None
            )
        else:
            error_body = f"`{self.custom_app_name}`/`{self.pkg_name}` failed to {action}: `{response}`"
            if http_code == 401:
                error_body += "\nValidate token is set and try again"
            elif http_code == 403:
                error_body += "\nValidate token permissions and try again"
            self.output(f"ERROR: Failed to {action.capitalize()} Custom App (HTTP {http_code})\n{error_body}")
            self.slack_notify(
                "ERROR",
                f"Failed to {action.capitalize()} Custom App (HTTP {http_code})",
                f"{error_body}",
            )
            raise ProcessorError(f"ERROR: Failed to {action.capitalize()} Custom App (HTTP {http_code})\n{error_body}")

    ######################
    # Audit Script Funcs
    ######################

    def _customize_audit_for_upload(self):
        """Finally a worthy Python replacement for sed
        Gets current TS and iters over audit script line by line
        Searches for our keys and updates them with assigned vals
        Creates a backup file before modification"""
        epoch_now = datetime.now().strftime("%s")
        with FileInput(files=self.audit_script_path, inplace=True, backup=".bak", encoding="utf-8") as f:
            for line in f:
                line = line.rstrip()  # noqa: PLW2901
                if "APP_NAME=" in line and hasattr(self, "app_name") and self.app_name is not None:
                    line = f'APP_NAME="{self.app_name}"'  # noqa: PLW2901
                elif "BUNDLE_ID=" in line and hasattr(self, "bundle_id") and self.bundle_id is not None:
                    line = f'BUNDLE_ID="{self.bundle_id}"'  # noqa: PLW2901
                elif "PKG_ID=" in line and hasattr(self, "pkg_id") and self.pkg_id is not None:
                    line = f'PKG_ID="{self.pkg_id}"'  # noqa: PLW2901
                elif "MINIMUM_ENFORCED_VERSION=" in line and hasattr(self, "app_vers") and self.app_vers is not None:
                    line = f'MINIMUM_ENFORCED_VERSION="{self.app_vers}"'  # noqa: PLW2901
                elif "CREATION_TIMESTAMP=" in line:
                    line = f'CREATION_TIMESTAMP="{epoch_now}"'  # noqa: PLW2901
                elif "DAYS_UNTIL_ENFORCEMENT=" in line:
                    line = (  # noqa: PLW2901
                        f"DAYS_UNTIL_ENFORCEMENT={self.test_delay}"
                        if self.test_app is True
                        else f"DAYS_UNTIL_ENFORCEMENT={self.prod_delay}"
                        if self.prod_app is True
                        else f"DAYS_UNTIL_ENFORCEMENT={self.prod_delay}"
                        if self.prod_delay
                        else line
                    )
                # Print here writes to file vs. stdout
                print(line)

    def _restore_audit(self):
        """Overwrite customized audit script with clean backup"""
        shutil.move(self.audit_script_path + ".bak", self.audit_script_path)

    ######################
    # Token Lookup Funcs
    ######################

    def _env_token_get(self, item_name):
        """Searches ENV for str `item_name`"""
        token = os.environ.get(item_name, None)
        # Also search for val from uppercase ENV name
        upper_token = os.environ.get(item_name.upper(), None)
        if token is None:
            token = upper_token if upper_token is not None else None
        return token

    def _keychain_token_get(self, item_name):
        """Retrieves and returns a secret stored at `item_name` from the keychain"""
        shell_cmd = f"/usr/bin/security find-generic-password -w -s {item_name} -a 'KAPPA'"
        decoded_out = self._run_command(shell_cmd)
        return decoded_out if decoded_out is not False else None

    def _retrieve_token(self, item_name):
        """Searches for by name and returns token for keystores toggled for use
        If multiple keystores are enabled, first searches ENV for token, then if not found, keychain"""
        token_val = None
        token_val = self._env_token_get(item_name) if self.token_keystores.get("environment") is True else None
        if not token_val:
            token_val = self._keychain_token_get(item_name) if self.token_keystores.get("keychain") is True else None
        return token_val

    ######################
    # Source info from PKG
    ######################
    def _expand_pkg_get_info(self):
        """Explodes a provided PKG at self.pkg_path into a temp dir Locates Info.plist for app within
        If multiple, selects Info.plist for largest app bundle within PKG
        Reads in BID, version, and .app name and assigns to self. If unable to locate, raises RuntimeError
        and proceeds with PackageInfo lookup to enforce install/version from PKG metadata; ends run with temp dir delete
        """

        def _get_largest_entry(file_list):
            """Locates largest directory housing file from a list of files"""

            def _get_dir_size(path="."):
                """Subfunc to iterate over a dir and return sum total bytesize
                Defaults to local directory with "." if no arg passed"""
                total = 0
                with os.scandir(path) as directory:
                    for entry in directory:
                        # Ignore symlinks that could lead to inf recursion
                        if entry.is_file(follow_symlinks=False):
                            total += entry.stat(follow_symlinks=False).st_size
                        elif entry.is_dir(follow_symlinks=False):
                            total += _get_dir_size(entry.path)
                return total

            # Create tmp dict
            dir_sizes = {}
            # Iter and assign plist as key and parent dir size as val
            for file in file_list:
                dir_sizes[file] = _get_dir_size(os.path.dirname(file))
            # Get file associated with largest size
            likely_file = max(dir_sizes, key=dir_sizes.get)
            return likely_file

        def _pkg_expand(src, dst):
            """Subprocess runs pkgutil --expand-full
            on source src, expanding to destination dst"""
            # Shell out to do PKG expansion and validate success
            shell_cmd = f"pkgutil --expand-full '{src}' '{dst}'"
            if self._run_command(shell_cmd) is not False:
                return True
            return False

        def _plist_find_return(exploded_pkg):
            """Locates all Info.plists within a provided expanded PKG path
            Identifies likely plist for core app (if multiple), populating
            dict with bundle ID, name, and version; returns dict and plist path"""
            # Make pathlib.Path obj from exploded PKG
            expanded_pkg_path = Path(exploded_pkg)
            # Find all Info.plists
            info_plist_paths = expanded_pkg_path.glob("**/Info.plist")
            # Rule out Info.plists in nonstandard dirs
            core_app_plists = [
                plist
                for plist in info_plist_paths
                if "Contents/Info.plist" in plist.as_posix()
                and all(
                    folder not in plist.as_posix()
                    for folder in (
                        "Extensions/",
                        "Frameworks/",
                        "Helpers/",
                        "Library/",
                        "MacOS/",
                        "PlugIns/",
                        "Resources/",
                        "SharedSupport/",
                        "opt/",
                        "bin/",
                    )
                )
            ]

            # If more than one found
            if len(core_app_plists) > 1:
                likely_plist = _get_largest_entry(core_app_plists)
            elif len(core_app_plists) == 1:
                likely_plist = core_app_plists[0]
            else:
                # If no plists found, raise RuntimeError to proceed with PackageInfo lookup
                raise RuntimeError

            # Quickly iter and assign all plist values we want
            def lookup_from_plist():
                return {
                    k: plistlib.load(open(likely_plist, "rb")).get(k)
                    for k in ("CFBundleIdentifier", "CFBundleShortVersionString", "CFBundleName")
                }

            # Run and return
            return lookup_from_plist(), likely_plist

        def _pkg_metadata_find_return(exploded_pkg):
            """Locates all identifying metadata files within an expanded PKG path
            If multiple PackageInfo, attempts query of pkg-ref from Distribution
            If PackageInfo Identifies likely PackageInfo (if multiple), populating values
            for PKG ID and PKG version if set and returning"""

            def _parse_pkg_xml_id_name(xml_file):
                """Parses PKG ID and version from either Distribution
                or PackageInfo XML file; returns tuple of ID and version"""
                # Convert to str if PosixPath
                if type(xml_file) == PosixPath:
                    xml_file = xml_file.as_posix()
                with open(xml_file) as f:
                    parsed_xml = ETree.parse(f)
                if "Distribution" in xml_file:
                    distro_pkg_info = parsed_xml.find("pkg-ref").attrib
                    pkg_id = distro_pkg_info.get("id")
                    pkg_vers = distro_pkg_info.get("version")
                elif "PackageInfo" in xml_file:
                    pkginfo_info = parsed_xml.getroot()
                    pkg_id = pkginfo_info.get("identifier")
                    pkg_vers = pkginfo_info.get("version")
                return pkg_id, pkg_vers

            # Make pathlib.Path obj from exploded PKG
            expanded_pkg_path = Path(exploded_pkg)
            # Find all Distribution/PackageInfo files
            distro_files = list(expanded_pkg_path.glob("**/Distribution"))
            package_infos = list(expanded_pkg_path.glob("**/PackageInfo"))

            # If more than one found
            if len(package_infos) > 1:
                # If Distro file found, use first pkg-ref from Distro file as truth
                if distro_files:
                    distro_id, distro_vers = _parse_pkg_xml_id_name(distro_files[0])
                    # Match Distro ID to PackageInfo, assign vers, and return
                    for info in package_infos:
                        pkg_id, pkg_vers = _parse_pkg_xml_id_name(info)
                        if pkg_id == distro_id and pkg_vers:
                            return pkg_id, pkg_vers
                # If no Distro file. get PackageInfo from largest dir by size
                likely_pkginfo = _get_largest_entry(package_infos)
            elif len(package_infos) == 1:
                likely_pkginfo = package_infos[0]
            else:
                # Nothing returned? Raise
                self.output("ERROR: No PackageInfo file found in PKG!")
                self.output(package_infos)
                raise ProcessorError(f"No PackageInfo file found in PKG!\n{package_infos}")

            # Read PackageInfo XML and parse PKG ID/version
            pkg_id, pkg_vers = _parse_pkg_xml_id_name(likely_pkginfo)
            if pkg_id and pkg_vers:
                return pkg_id, pkg_vers
            else:
                self.output("ERROR: One of PKG ID/PKG version missing from PackageInfo!")
                self.output(f"ERROR: See below for full PackageInfo output:\n{likely_pkginfo}")
                raise ProcessorError(
                    "One of PKG ID/PKG version missing from PackageInfo!\nSee below for full PackageInfo output:\n{likely_pkginfo}"
                )

        ##############
        #### MAIN ####
        ##############

        # Create temp dir and assign var for expanded PKG
        temp_dir = tempfile.TemporaryDirectory()
        tmp_pkg_path = os.path.join(temp_dir.name, self.pkg_name)

        if _pkg_expand(self.pkg_path, tmp_pkg_path) is False:
            self.output(f"ERROR: Unable to read plist as PKG {self.pkg_path} failed to expand")
            raise ProcessorError(f"Unable to read plist as PKG {self.pkg_path} failed to expand")
        try:
            plist_values, likely_plist = _plist_find_return(tmp_pkg_path)

            try:
                self.bundle_id = plist_values["CFBundleIdentifier"]
                self.app_vers = plist_values["CFBundleShortVersionString"]
            except KeyError as err:
                self.output(f"ERROR: Could not read one or more required key(s) from plist! {' '.join(err.args)}")
                raise ProcessorError(f"Could not read one or more required key(s) from plist! {' '.join(err.args)}")

            # CFBundleName isn't 100% match for actual app bundle name
            # Try getting .app name from abs path of Info.plist
            likely_app_name = Path(likely_plist).parents[1].name
            # Dir could be named Payload in PKG, so validate name ends in .app
            # Otherwise assign as CFBundleName + .app (using BID for primary validation)
            self.app_name = (
                likely_app_name if likely_app_name.endswith(".app") else plist_values["CFBundleName"] + ".app"
            )
            self.output(
                f"INFO:\nApplication Name: '{self.app_name}'\nBundle Identifier: '{self.bundle_id}'\nApplication Version: '{self.app_vers}'"
            )
        # If no valid plist found, proceed with PackageInfo lookup
        except RuntimeError:
            self.output("WARNING: No valid app plist found in PKG!")
            self.output("Attempting lookup from PackageInfo file...")
            self.pkg_id, self.app_vers = _pkg_metadata_find_return(tmp_pkg_path)
            self.output(f"Found PKG ID '{self.pkg_id}' with PKG Version '{self.app_vers}'")
            self.output("Will be used for audit enforcement if enabled")
        # rm dir + exploded PKG when done
        temp_dir.cleanup()
        return True

    ######################
    # Custom LI Find Funcs
    ######################

    def _find_lib_item_match(self):
        """Searches for custom app to update from existing items in Kandji library
        If none match, attempts to find custom app dynamically by PKG name similarity
        if more than one match found, collates metadata for matches and reports to Slack with error"""
        # Locate custom app by name
        self.output(f"Searching for {self.custom_app_name} from list of custom apps")
        app_picker = [app for app in self.custom_apps if self.custom_app_name == app.get("name")]
        # If not found, try to find dynamically
        if not app_picker:
            self.output(f"WARNING: No existing LI found for provided name '{self.custom_app_name}'!")
            if self.default_auto_create is True:
                self.output("Creating as new custom app...")
                return False
            if self.default_dynamic_lookup is True:
                self.output("Will try dynamic lookup from newly built PKG...")
                return self._find_lib_item_dynamic()
        elif len(app_picker) > 1:
            # More than one hit, attempt to find match by SS category
            if self.ss_category_id and self.custom_app_enforcement == "no_enforcement":
                app_picker_by_ss = [
                    app
                    for app in app_picker
                    if app.get("show_in_self_service") is True
                    and app.get("self_service_category_id") == self.ss_category_id
                ]
                if len(app_picker_by_ss) == 1:
                    return next(iter(app_picker_by_ss))
            if self.default_dynamic_lookup is True:
                self.output(f"WARNING: More than one match ({len(app_picker)}) returned for provided LI name!")
                self.output("Will try dynamic lookup from newly built PKG...")
                return self._find_lib_item_dynamic(app_picker)
            # If we get here, means we couldn't decide on a single match
            # Create Slack body str and notify of duplicates
            slack_body = ""
            # Iter over custom_apps
            for custom_app in app_picker:
                custom_app_id = custom_app.get("id")
                # Get PKG name without abs path
                custom_app_pkg = os.path.basename(custom_app.get("file_key"))
                custom_app_created = custom_app.get("created_at")
                custom_app_created_fmt = (
                    datetime.strptime(custom_app_created, "%Y-%m-%dT%H:%M:%S.%fZ")
                    .astimezone()
                    .strftime("%m/%d/%Y @ %I:%M %p")
                )
                custom_app_updated = custom_app.get("file_updated")
                custom_app_url = os.path.join(self.tenant_url, "library", "custom-apps", custom_app_id)
                custom_app_url = self._ensure_https(custom_app_url)
                # Append matching custom app names/MD to Slack body to post
                slack_body += f"*<{custom_app_url}|Custom App Created _{custom_app_created_fmt}_>*\n*PKG*: `{custom_app_pkg}` (*uploaded* _{custom_app_updated}_)\n\n"
            self.output(
                f"ERROR: More than one match ({len(app_picker)}) returned for provided LI name! Cannot upload...\n{slack_body}"
            )
            self.slack_notify(
                "ERROR",
                f"Found Duplicates of Custom App {self.custom_app_name}",
                f"{slack_body}",
            )
            # Return None to bypass remaining steps
            return None
        try:
            return next(iter(app_picker))
        except StopIteration:
            return False

    def _find_lib_item_dynamic(self, possible_apps={}):
        """Uses SequenceMatcher to find most similarly named PKG in Kandji to the newly built PKG
        Requires a minimum ratio of .8 suggesting high probability of match; takes matching PKGs
        and filters out any not matching the existing LI name (if provided); sorts by semantic version
        and if multiple matches found, iterates to find oldest Custom App entry and assigns as selection"""

        ####################
        # Dynamic population
        ####################
        # Define a function to parse the datetime strings
        def parse_dt(dt_str):
            """Parses datetime strings from Kandji API into datetime objects"""
            try:
                return datetime.strptime(dt_str, "%Y-%m-%dT%H:%M:%S.%fZ").astimezone()
            except ValueError:
                return datetime.strptime(dt_str, "%Y-%m-%dT%H:%M:%SZ").astimezone()

        # Get PKG names (no path) if .pkg is suffix
        all_pkg_names = [
            os.path.basename(app.get("file_key")) for app in self.custom_apps if app.get("file_key").endswith(".pkg")
        ]
        # Create dict to hold PKG names and their similarity scores
        similarity_scores = {}

        for pkg in all_pkg_names:
            # re.sub to remove the _ + random UUID chars prepended to .pkg
            similarity_scores[pkg] = difflib.SequenceMatcher(
                None, re.sub(r"_\w{8}(?=.pkg)", "", pkg), self.pkg_name
            ).ratio()

        # Sort dict by similarity scores
        sorted_similar_pkgs = dict(sorted(similarity_scores.items(), key=lambda k: k[1], reverse=True))

        # Gaudy gauntlet of regex formatting to sanitize the version
        re_replacements = {r"_\w{8}(?=.pkg)": "", r"[ ]": ".", "[^0-9\\.]": "", r"[.]{2,}": ".", r"^\.|\.$": ""}
        # Setting limit to .85 is the sweet spot to account for variations in versions
        # Still high enough to exclude both version and name changes (reducing false positives)
        ratio_limit = 0.85
        # Grab all PKG names that are above our sim threshold
        possible_pkgs = [pkg for pkg in sorted_similar_pkgs.keys() if sorted_similar_pkgs.get(pkg) >= ratio_limit]

        # If possible_apps defined, we were given a specific name to validate against
        provided_app_name = None
        if possible_apps:
            matching_pkgs = []
            for possible in possible_apps:
                # Any matches are added to matching_pkgs list
                matching_pkgs.extend(pkg for pkg in possible_pkgs if pkg in possible.get("file_key"))
            # One or more matches, reassign var
            if matching_pkgs:
                possible_pkgs = matching_pkgs
            # Assign provided_app_name as unique name from possible_apps (should only be one)
            provided_app_name = "".join({possible.get("name") for possible in possible_apps})

        # Dict to hold PKG names and their sanitized vers strs for semantic parsing
        pkgs_versions = {
            maybepkg: reduce(
                lambda parsed_vers, match_replace: re.sub(*match_replace, parsed_vers),
                re_replacements.items(),
                maybepkg,
            )
            for maybepkg in possible_pkgs
        }

        # Sort PKGs according to semantic versioning
        pkgs_versions_sorted = dict(
            sorted(pkgs_versions.items(), key=lambda k: packaging_version.parse(k[1]), reverse=True)
        )

        try:
            custom_app = None
            # Iter over it and grab first item with highest vers
            custom_pkg_name, custom_pkg_vers = next(iter(pkgs_versions_sorted.items()))

            # Get custom PKG name with highest version
            highest_vers = [
                pkg for pkg in pkgs_versions_sorted.keys() if custom_pkg_vers in pkgs_versions_sorted.get(pkg)
            ]
            # Check if more than one vers found matching highest
            if len(highest_vers) > 1:
                # Create dict to hold PKG names and their mod dates
                pkg_custom_app_updated = {}
                for pkg in highest_vers:
                    try:
                        # Find the matching app record
                        app_record = next(app for app in self.custom_apps if pkg in app.get("file_key"))
                        pkg_uploaded = app_record.get("file_updated")
                        custom_li_modified = app_record.get("updated_at")
                        # Append to dict
                        pkg_custom_app_updated[pkg] = {
                            "pkg_uploaded": pkg_uploaded,
                            "custom_li_modified": custom_li_modified,
                        }
                    # Not found if searching only names matching user input
                    except StopIteration:
                        pass
                # Find the oldest app by first pkg_uploaded, and if identical, custom_li_modified
                oldest_app = min(
                    pkg_custom_app_updated,
                    key=lambda key: (
                        parse_dt(pkg_custom_app_updated[key]["pkg_uploaded"]),
                        parse_dt(pkg_custom_app_updated[key]["custom_li_modified"]),
                    ),
                )
                custom_pkg_name = oldest_app

            # Assign this as our best guess PKG
            matching_entry = [app for app in self.custom_apps if custom_pkg_name in app.get("file_key")]
            if len(matching_entry) > 1:
                if provided_app_name is not None:
                    matching_entry = [app for app in matching_entry if provided_app_name in app.get("name")]
            custom_app = next(iter(matching_entry))
            custom_app_id = custom_app.get("id")
            custom_name = custom_app.get("name")
            self.output(f"Found match '{custom_name}' with ID '{custom_app_id}' for provided PKG")
            self.output("Proceeding to update...")
            return custom_app
        except StopIteration as si:
            self.output(f"Found no match for provided LI name! Error {si}; cannot upload...")
            return False

    ####################################
    ######### PUBLIC FUNCTIONS #########
    ####################################

    def slack_notify(self, status, text_header, text_payload, title_link=None):
        """Posts to an indicated Slack channel, accepting arguments for
        text_header (header), text_payload (body), and opt arg title_link (header link)"""
        # Return if no val found for Slack webhook
        if self.slack_channel is None:
            return False

        if status == "SUCCESS":
            # Set alert color to green
            color = "00FF00"
        elif status == "WARNING":
            # Set alert color to orange
            color = "E8793B"
        elif status == "ERROR":
            # Set alert color to red
            color = "FF0000"

        slack_payload = f'payload={{"attachments":[{{"color":"{color}", "title": "{status}: {text_header}", "text": "{text_payload}"'
        if title_link:
            title_link = self._ensure_https(title_link)
            slack_payload = slack_payload + f', "title_link":"{title_link}"'
        slack_payload = slack_payload + "}]}"
        status_code, response = self._curl_cmd_exec(method="POST", url=self.slack_channel, data=slack_payload)
        if status_code <= 204:
            self.output("Successfully posted message to Slack channel")
        else:
            self.output(f"ERROR: Failed to post {text_payload} to Slack channel! Got {response}")
