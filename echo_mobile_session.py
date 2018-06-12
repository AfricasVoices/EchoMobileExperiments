import time

import six
import requests


class EchoMobileError(Exception):
    """
    Raised when the Echo Mobile server responded to a request with an error.
    """
    pass


class EchoMobileSession(object):
    """
    A client-side API for interacting with Echo Mobile servers.
    
    For example, to download a survey report:
    >>> session = EchoMobileSession()
    >>> session.login(<USERNAME>, <PASSWORD>)
    >>> session.use_account_with_name(<ACCOUNT_NAME>)  # Optional for users with only one account
    >>> report = session.survey_report_for_name(<SURVEY_NAME>)
    >>> session.delete_session_background_tasks()  # Removes the report background task from the Echo Mobile website.
    """
    BASE_URL = "https://www.echomobile.org/api/"

    def __init__(self, verbose=False):
        """
        :param verbose: Whether to initialise with verbose mode enabled.
        :type verbose: bool
        """
        self.session = requests.Session()
        self.verbose = verbose
        self.background_tasks = set()

    def login(self, username, password):
        """
        Logs into Echo Mobile using the given user credentials.

        :param username: Echo Mobile user name to use. Probably an email address.
        :type username: str
        :param password: Echo Mobile password.
        :type password: str
        """
        if self.verbose:
            six.print_("Logging in as '{}'... ".format(username), end="", flush=True)

        request = self.session.post(self.BASE_URL + "authenticate/simple",
                                    params={"_login": username, "_pw": password,
                                            # auth is a magic API key extracted from
                                            # echomobile.org/dist/src/app.build.js
                                            "auth": "JXEIUOVNQLKJDDHA2J", "populate_session": 1})
        response = request.json()

        if not response["success"]:
            raise EchoMobileError(response["message"])
        if self.verbose:
            print("Done")

    def accounts(self):
        """
        Returns the list of accounts available to the user who is currently logged in.

        :return: List of available accounts.
        :rtype: list
        """
        if self.verbose:
            six.print_("Fetching user's accounts... ", end="", flush=True)

        request = self.session.get(self.BASE_URL + "cms/account/me", params={"with_linked": 1})
        response = request.json()

        if not response["success"]:
            raise EchoMobileError(response["message"])
        if self.verbose:
            print("Done")
            print("  Accounts found for this user:")
            for account in response["linked"]:
                print("    " + account["ent_name"])

        return response["linked"]

    def account_key_for_name(self, account_name):
        """
        Returns the key for the account with the name provided.

        :param account_name: Name of the account to retrieve the key for
        :type account_name: str
        :return: Key for account with account_name
        :rtype: str
        """
        matching_accounts = [account for account in self.accounts() if account["ent_name"] == account_name]

        if len(matching_accounts) == 0:
            raise KeyError("Account with account_name '{}' not found".format(account_name))

        account_key = matching_accounts[0]["key"]

        if self.verbose:
            print("Key for account '{}' is '{}'".format(account_name, account_key))

        return account_key

    def use_account_with_key(self, account_key):
        """
        Updates this session to use the account that has the given key.

        :param account_key: Key of account to switch to.
        :type account_key: str
        """
        if self.verbose:
            six.print_("Switching to account '{}'... ".format(account_key), end="", flush=True)

        request = self.session.post(self.BASE_URL + "authenticate/linked", params={"acckey": account_key})
        response = request.json()

        if not response["success"]:
            raise EchoMobileError(response["message"])
        if self.verbose:
            print("Done")

    def use_account_with_name(self, account_name):
        """
        Updates this session to use the account that has the given name.

        Equivalent to choosing an account from the User -> Switch Accounts page of Echo Mobile.

        :param account_name: Name of account to switch to.
        :type account_name: str
        """
        self.use_account_with_key(self.account_key_for_name(account_name))

    def surveys(self):
        """Returns the list of active surveys available to the logged in user/account."""
        if self.verbose:
            six.print_("Fetching available surveys... ", end="", flush=True)

        request = self.session.get(self.BASE_URL + "cms/survey")
        response = request.json()

        if not response["success"]:
            raise EchoMobileError(response["message"])
        if self.verbose:
            print("Done")
            print("  Surveys found for this user/account:")
            for survey in response["surveys"]:
                print("    " + survey["name"])

        return response["surveys"]

    def survey_key_for_name(self, survey_name):
        """
        Returns the key for the survey with the given name.

        :param survey_name: Name of survey to get the key of
        :type survey_name: str
        :return: Key of survey
        :rtype: str
        """
        surveys = self.surveys()
        matching_surveys = [survey for survey in surveys if survey["name"] == survey_name]

        if len(matching_surveys) == 0:
            raise KeyError("Requested survey not found on Echo Mobile (Available surveys: " +
                           ",".join(list(map(lambda s: s["name"], surveys))) + ")")

        assert len(matching_surveys) == 1, "Multiple surveys with name " + survey_name

        survey_key = matching_surveys[0]["key"]

        if self.verbose:
            print("Key for survey '{}' is '{}'".format(survey_name, survey_key))

        return survey_key

    def await_report_generated(self, report_key, poll_interval=2):
        """
        Polls Echo Mobile for the status of a report until it is marked as complete.

        :param report_key: Key of report to poll status of
        :type report_key: str
        :param poll_interval: Time to wait between polling attempts, in seconds.
        :type poll_interval: float
        """
        if self.verbose:
            six.print_("Waiting for report to generate... ", end="", flush=True)

        # Status is not documented, but from observation '1' means generating and '3' means successfully generated
        report_status = 1
        while report_status == 1:
            time.sleep(poll_interval)

            request = self.session.get(self.BASE_URL + "cms/backgroundtask")
            response = request.json()

            if not response["success"]:
                raise EchoMobileError(response["message"])

            task = response["tasks"]["report_" + report_key]

            if self.verbose and task["total"] != 0:
                progress = task["progress"] / task["total"] * 100
                six.print_("\rWaiting for report to generate... {0:.2f}%".format(progress), end="", flush=True)

            report_status = task["status"]

        if self.verbose:
            print("\rWaiting for report to generate... Done        ")

        assert report_status == 3, "Report stopped generating, but with an unknown status"

    def generate_survey_report(self, survey_key, response_formats=None, contact_fields=None, wait_until_generated=True):
        """
        Starts the generation of a report for the given survey on Echo Mobile.

        Note that this function only triggers the generation of a report. Completed reports must be downloaded with
        download_survey_report.

        :param survey_key: Key of survey to generate report for.
        :type survey_key: str
        :param response_formats: List of response formats to download. Defaults to ["raw", "label"] if None.
                                 The full list of options is : raw, label, value, score.
        :type response_formats: list of str
        :param contact_fields: List of contact fields to download. Defaults to ["name", "phone"] if None.
                               The full list of options is: name, phone, internal_id, group, referrer, referrer_phone,
                               upload_date, last_survey_complete_date, geo, locationTextRaw, labels, linked_entity,
                               opted_out.
        :type contact_fields: list of str
        :param wait_until_generated: Whether to wait for the report to finish generating on the Echo Mobile server
                                     before returning.
        :type wait_until_generated: bool
        """
        if response_formats is None:
            response_formats = ["raw", "label"]
        if contact_fields is None:
            contact_fields = ["name", "phone"]

        if self.verbose:
            six.print_("Requesting generation of report for survey '{}'... ".format(survey_key), end="", flush=True)

        request = self.session.post(self.BASE_URL + "cms/report/generate",
                                    # Type is undocumented, but from inspection of the calls the website is
                                    # making it turns out that '13' is the magic number we need here.
                                    params={"type": 13, "target": survey_key,
                                            "gen": ",".join(response_formats),
                                            "std_field": ",".join(contact_fields)
                                            }
                                    )
        response = request.json()

        if not response["success"]:
            raise EchoMobileError(response["message"])
        elif self.verbose:
            print("Done")

        report_key = response["rkey"]
        self.background_tasks.add("report_" + report_key)

        if wait_until_generated:
            self.await_report_generated(report_key)

        return report_key

    def generate_global_inbox_report(self, wait_until_generated=True):
        if self.verbose:
            six.print_("Requesting generation of report for global inbox... ", end="", flush=True)

        request = self.session.post(self.BASE_URL + "cms/report/generate",
                                    params={
                                        # type and ftype were determined by inspecting the calls the website
                                        # was making.
                                        "type": 11, "ftype": 1,
                                        "std_field": "internal_id,group,referrer,upload_date,"
                                                     "last_survey_complete_date,"
                                                     "geo,locationTextRaw,labels"
                                    })
        response = request.json()

        if not response["success"]:
            raise EchoMobileError(response["message"])
        elif self.verbose:
            print("Done")

        report_key = response["rkey"]
        self.background_tasks.add("report_" + report_key)

        if wait_until_generated:
            print("About to wait for a report to generate. "
                  "Note that progress will always report 0% until done, due to an Echo Mobile bug.")
            self.await_report_generated(report_key)

        return report_key

    def download_report(self, report_key):
        """
        Downloads the specified report from Echo Mobile.

        Note that reports must first be generated before they can be downloaded.

        :param report_key: Key of report to download
        :type report_key: str
        :return: CSV containing the survey report
        :rtype: str
        """
        if self.verbose:
            six.print_("Downloading report... ", end="", flush=True)

        request = self.session.get(self.BASE_URL + "cms/report/serve", params={"rkey": report_key})
        response = request.text

        if self.verbose:
            print("Done")

        return response

    def survey_report_for_key(self, survey_key, contact_fields=None, response_formats=None):
        """
        Generates and downloads a report for the survey with the given key.

        :param survey_key: Key of survey to generate and download report for
        :type survey_key: str
        :param response_formats: List of response formats to download. Defaults to ["raw", "label"] if None.
                                 The full list of options is : raw, label, value, score.
        :type response_formats: list of str
        :param contact_fields: List of contact fields to download. Defaults to ["name", "phone"] if None.
                               The full list of options is: name, phone, internal_id, group, referrer, referrer_phone,
                               upload_date, last_survey_complete_date, geo, locationTextRaw, labels, linked_entity,
                               opted_out.
        :type contact_fields: list of str
        :return: CSV containing the survey report
        :rtype: str
        """
        report_key = self.generate_survey_report(survey_key, contact_fields=contact_fields,
                                                 response_formats=response_formats, wait_until_generated=True)
        return self.download_report(report_key)

    def survey_report_for_name(self, survey_name, contact_fields=None, response_formats=None):
        """
        Generates and downloads a report for the survey with the given name.

        :param survey_name: Name of survey to generate and download report for
        :type survey_name: str
        :param response_formats: List of response formats to download. Defaults to ["raw", "label"] if None.
                                 The full list of options is : raw, label, value, score.
        :type response_formats: list of str
        :param contact_fields: List of contact fields to download. Defaults to ["name", "phone"] if None.
                               The full list of options is: name, phone, internal_id, group, referrer, referrer_phone,
                               upload_date, last_survey_complete_date, geo, locationTextRaw, labels, linked_entity,
                               opted_out.
        :type contact_fields: list of str
        :return: CSV containing the survey report
        :rtype: str
        """
        return self.survey_report_for_key(self.survey_key_for_name(survey_name), contact_fields=contact_fields,
                                          response_formats=response_formats)

    def global_inbox_report(self):
        return self.download_report(self.generate_global_inbox_report(wait_until_generated=True))

    def delete_background_task(self, task_key):
        """
        Deletes the background task on Echo Mobile that has the given key.

        :param task_key: Key of background task to delete
        :type task_key: str
        """
        if self.verbose:
            six.print_("Deleting background task '{}'... ".format(task_key), end="", flush=True)

        request = self.session.post(self.BASE_URL + "cms/backgroundtask/cancel", params={"key": task_key})
        response = request.json()

        if not response["success"]:
            raise EchoMobileError(response["message"])
        if self.verbose:
            print("Done")

    def delete_session_background_tasks(self):
        """
        Deletes all the background tasks on Echo Mobile which have been generated by this session so far.
        """
        for key in list(self.background_tasks):
            self.delete_background_task(key)
            self.background_tasks.remove(key)