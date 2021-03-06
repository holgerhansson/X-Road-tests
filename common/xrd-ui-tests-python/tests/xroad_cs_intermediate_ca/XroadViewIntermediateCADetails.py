import unittest

from main.maincontroller import MainController
from tests.xroad_cs_intermediate_ca import cs_intermediate_ca


class XroadViewIntermediateCADetails(unittest.TestCase):
    """
    TRUST_07 View the Details of an Intermediate CA
    RIA URL: https://jira.ria.ee/browse/XTKB-190
    Depends on finishing other test(s): Add intermediate CA
    Requires helper scenarios:
    X-Road version: 6.16.0
    """

    def test_xroad_intermediate_ca_deleting(self):
        main = MainController(self)

        cs_host = main.config.get('cs.host')
        cs_user = main.config.get('cs.user')
        cs_pass = main.config.get('cs.pass')

        ca_name = main.config.get('ca.ssh_host')

        test_view_intermediate_ca_details = cs_intermediate_ca.test_view_intermediate_ca_details(main, ca_name=ca_name)
        try:
            main.reload_webdriver(cs_host, cs_user, cs_pass)
            test_view_intermediate_ca_details()

        finally:
            main.tearDown()
