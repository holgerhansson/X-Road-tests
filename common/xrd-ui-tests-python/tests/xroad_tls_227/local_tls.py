import os
import tarfile
import time
import re

from requests.exceptions import SSLError
from selenium.webdriver.common.by import By

from helpers import xroad, soaptestclient, auditchecker, ssh_server_actions
from tests.xroad_configure_service_222 import configure_service
from view_models import popups, clients_table_vm, sidebar, ss_system_parameters, messages, log_constants
# These faults are checked when we need the result to be unsuccessful. Otherwise the checking function returns True.
from view_models.log_constants import ADD_INTERNAL_TLS_CERT_FAILED, GENERATE_TLS_KEY_AND_CERT
from view_models.messages import TSL_CERTIFICATE_ALREADY_EXISTS, CERTIFICATE_IMPORT_SUCCESSFUL, \
    GENERATE_CERTIFICATE_NOT_FOUND_ERROR

faults_unsuccessful = ['Server.ClientProxy.SslAuthenticationFailed']
# These faults are checked when we need the result to be successful. Otherwise the checking function returns False.
faults_successful = ['Server.ServerProxy.AccessDenied', 'Server.ServerProxy.UnknownService',
                     'Server.ServerProxy.ServiceDisabled', 'Server.ClientProxy.*', 'Client.*']


def test_delete_tls(case, client, provider):
    self = case

    ss1_host = self.config.get('ss1.host')
    ss1_user = self.config.get('ss1.user')
    ss1_pass = self.config.get('ss1.pass')

    ss2_host = self.config.get('ss2.host')
    ss2_user = self.config.get('ss2.user')
    ss2_pass = self.config.get('ss2.pass')

    ss1_ssh_host = self.config.get('ss1.ssh_host')
    ss1_ssh_user = self.config.get('ss1.ssh_user')
    ss1_ssh_pass = self.config.get('ss1.ssh_pass')

    ss2_ssh_host = self.config.get('ss2.ssh_host')
    ss2_ssh_user = self.config.get('ss2.ssh_user')
    ss2_ssh_pass = self.config.get('ss2.ssh_pass')

    client_id = xroad.get_xroad_subsystem(client)
    provider_id = xroad.get_xroad_subsystem(provider)

    testservice_name = self.config.get('services.test_service')
    wsdl_url = self.config.get('wsdl.remote_path').format(self.config.get('wsdl.service_wsdl'))
    new_service_url = self.config.get('services.test_service_url')

    def delete_tls():
        '''Getting auditchecker instance for ss1'''
        log_checker = auditchecker.AuditChecker(host=ss1_ssh_host, username=ss1_ssh_user, password=ss1_ssh_pass)
        '''Get current log lines count'''
        current_log_lines = log_checker.get_line_count()
        self.reload_webdriver(url=ss1_host, username=ss1_user, password=ss1_pass)

        self.log('*** MEMBER_51 Delete internal TLS certificate')
        self.log('MEMBER_49 Delete setting {0} connection type to HTTP'.format(client_id))

        # Open "Security Server Clients" page
        self.by_css(sidebar.CLIENTS_BTN_CSS).click()

        # Wait until list is loaded
        self.wait_jquery()

        # Open client popup using shortcut button to open it directly at Services tab.
        clients_table_vm.open_client_popup_internal_servers(self, client_id=client_id)

        # Set connection type to HTTPS_NO_AUTH (SSLNOAUTH)
        self.is_true(clients_table_vm.client_servers_popup_set_connection(self, 'NOSSL'),
                     msg='MEMBER_49 Failed to set connection type to HTTP')

        # Delete all internal certificates
        deleted_certs = clients_table_vm.client_servers_popup_delete_tls_certs(self, cancel_deletion=True)

        expected_log_msg = log_constants.DELETE_INTERNAL_TSL_CERT
        '''If cert(s) were deleted check audit.log'''
        if deleted_certs > 0:
            self.log('MEMBER_51 5. System logs the event "{0}"'.format(expected_log_msg))
            logs_found = log_checker.check_log(expected_log_msg, from_line=current_log_lines + 1)
            self.is_true(logs_found)

        log_checker = auditchecker.AuditChecker(host=ss2_ssh_host, username=ss2_ssh_user, password=ss2_ssh_pass)
        # Switch to Security server 2
        self.reload_webdriver(url=ss2_host, username=ss2_user, password=ss2_pass)

        self.log('SERVICE_20 Disable certificate verification and set HTTP URL for the service')

        # Open "Security Server Clients" page
        self.by_css(sidebar.CLIENTS_BTN_CSS).click()

        # Wait until list is loaded
        self.wait_jquery()

        # Open client popup using shortcut button to open it directly at Services tab.
        clients_table_vm.open_client_popup_services(self, client_id=provider_id)

        # Find the service under the specified WSDL in service list (and expand the WSDL services list if not open yet)
        service_row = clients_table_vm.client_services_popup_find_service(self, wsdl_url=wsdl_url,
                                                                          service_name=testservice_name)

        # Click on the service row to select it
        service_row.click()

        # Open service parameters by finding the "Edit" button and clicking it.
        edit_service_button = self.by_id(popups.CLIENT_DETAILS_POPUP_EDIT_WSDL_BTN_ID)

        # Click the "Edit" button to open "Edit Service Parameters" popup
        edit_service_button.click()

        warning, error = configure_service.edit_service(self, service_url=new_service_url)
        case.is_none(error, msg='SERVICE_20 Got error when trying to update service URL')

        # Click tab "Internal Servers"
        self.by_css(clients_table_vm.INTERNAL_CERTS_TAB_TITLE_CSS).click()

        # Wait until everything is loaded.
        self.wait_jquery()

        '''Get current log lines count'''
        current_log_lines = log_checker.get_line_count()
        # Delete all internal certificates
        deleted_certs = clients_table_vm.client_servers_popup_delete_tls_certs(self)
        '''If certs were deleted, check log'''
        if deleted_certs > 0:
            '''Checks if expected message present in log'''
            logs_found = log_checker.check_log(expected_log_msg,
                                               from_line=current_log_lines + 1)
            self.is_true(logs_found,
                         msg='Some log entries were missing. Expected: "{0}", found: "{1}"'.format(
                             expected_log_msg,
                             log_checker.found_lines))

    return delete_tls


def test_tls(case, client, provider):
    self = case

    certs_download_filename = self.config.get('certs.downloaded_ss_certs_filename')
    certs_ss1_filename = self.config.get('certs.ss1_certs')
    certs_ss2_filename = self.config.get('certs.ss2_certs')
    verify_cert_filename = self.config.get('certs.server_cert_filename')
    client_cert_filename = self.config.get('certs.client_cert_filename')
    client_key_filename = self.config.get('certs.client_key_filename')
    mock_cert_filename = self.config.get('certs.service_cert_filename')

    download_check_interval = 1  # Seconds
    download_time_limit = self.config.get('certs.cert_download_time_limit')
    delete_created_files = False

    sync_retry = self.config.get('services.request_sync_delay')
    sync_max_seconds = self.config.get('services.request_sync_timeout')

    client_id = xroad.get_xroad_subsystem(client)
    provider_id = xroad.get_xroad_subsystem(provider)

    ss1_ssh_host = self.config.get('ss1.ssh_host')
    ss1_ssh_user = self.config.get('ss1.ssh_user')
    ss1_ssh_pass = self.config.get('ss1.ssh_pass')

    ss1_host = self.config.get('ss1.host')
    ss1_user = self.config.get('ss1.user')
    ss1_pass = self.config.get('ss1.pass')

    ss2_host = self.config.get('ss2.host')
    ss2_user = self.config.get('ss2.user')
    ss2_pass = self.config.get('ss2.pass')

    wsdl_url = self.config.get('wsdl.remote_path').format(self.config.get('wsdl.service_wsdl'))
    testservice_name = self.config.get('services.test_service')
    new_service_url = self.config.get('services.test_service_url_ssl')

    query_url = self.config.get('ss1.service_path')
    query_url_ssl = self.config.get('ss1.service_path_ssl')
    query_filename = self.config.get('services.request_template_filename')
    query = self.get_xml_query(query_filename)
    client_cert_path = self.get_cert_path(client_cert_filename)
    client_key_path = self.get_cert_path(client_key_filename)
    mock_cert_path = self.get_cert_path(mock_cert_filename)

    ss2_certs_directory = self.config.get('certs.ss2_certificate_directory')

    testclient_params = {
        'xroadProtocolVersion': self.config.get('services.xroad_protocol'),
        'xroadIssue': self.config.get('services.xroad_issue'),
        'xroadUserId': self.config.get('services.xroad_userid'),
        'serviceMemberInstance': provider['instance'],
        'serviceMemberClass': provider['class'],
        'serviceMemberCode': provider['code'],
        'serviceSubsystemCode': provider['subsystem'],
        'serviceCode': xroad.get_service_name(testservice_name),
        'serviceVersion': xroad.get_service_version(testservice_name),
        'memberInstance': client['instance'],
        'memberClass': client['class'],
        'memberCode': client['code'],
        'subsystemCode': client['subsystem'],
        'requestBody': self.config.get('services.testservice_request_body')
    }

    testclient_http = soaptestclient.SoapTestClient(url=query_url, body=query,
                                                    retry_interval=sync_retry, fail_timeout=sync_max_seconds,
                                                    faults_successful=faults_successful,
                                                    faults_unsuccessful=faults_unsuccessful, params=testclient_params)
    testclient_https = soaptestclient.SoapTestClient(url=query_url_ssl, body=query,
                                                     retry_interval=sync_retry, fail_timeout=sync_max_seconds,
                                                     server_certificate=self.get_download_path(verify_cert_filename),
                                                     faults_successful=faults_successful,
                                                     faults_unsuccessful=faults_unsuccessful, params=testclient_params)
    testclient_https_ss2 = soaptestclient.SoapTestClient(url=query_url_ssl, body=query,
                                                         retry_interval=sync_retry, fail_timeout=sync_max_seconds,
                                                         server_certificate=self.get_download_path(
                                                             os.path.join(ss2_certs_directory, verify_cert_filename)),
                                                         client_certificate=(client_cert_path, client_key_path),
                                                         faults_successful=faults_successful,
                                                         faults_unsuccessful=faults_unsuccessful,
                                                         params=testclient_params)
    log_checker = auditchecker.AuditChecker(host=ss1_ssh_host, username=ss1_ssh_user, password=ss1_ssh_pass)
    ssh_client = ssh_server_actions.get_client(ss1_ssh_host, ss1_ssh_user, ss1_ssh_pass)

    def local_tls():
        """
        :param self: MainController class object
        :return: None
        ''"""

        # UC MEMBER_49 (Change a Security Server Client's Internal Server Connection Type)
        # UC MEMBER_50 (Add a Security Server Client's Internal TLS Certificate)
        self.log('*** UC MEMBER_49 / MEMBER_50')

        self.reload_webdriver(url=ss1_host, username=ss1_user, password=ss1_pass)

        certs_filename = self.get_download_path(certs_download_filename)

        ss1_filename = self.get_download_path(certs_ss1_filename)
        ss2_filename = self.get_download_path(certs_ss2_filename)

        ss2_certs_directory_abs = self.get_download_path(ss2_certs_directory)

        # Create directory if not exists
        if not os.path.isdir(ss2_certs_directory_abs):
            os.mkdir(ss2_certs_directory_abs)

        self.remove_files([certs_filename, ss1_filename, ss2_filename, ss2_certs_directory_abs])

        created_files = [certs_filename]

        self.start_mock_service()

        # UC MEMBER_49 1. Select to change the internal server connection type.
        self.log('MEMBER_49 1. Select to change the internal server connection type.')
        self.log('UC SS_10 1. SS administrator selects to view the internal TLS certificate of the security server.')

        # Click "System Parameters" in sidebar
        self.by_css(sidebar.SYSTEM_PARAMETERS_BTN_CSS).click()

        current_log_lines = log_checker.get_line_count()
        self.log('UC SS_10 2. The SS administrator has a possibility to choose amongst the following actions: generate a new TLS key , view the details, export')

        '''Get TLS hash before generating process'''
        tls_hash_before_generating = self.wait_until_visible(type=By.ID,
                                                             element=ss_system_parameters.INTERNAL_TLS_CERT_HASH_ID).text
        '''Verify SHA-1'''
        sha1_match = re.match(ss_system_parameters.SHA1_REGEX, tls_hash_before_generating)
        self.is_true(sha1_match,
                     msg='SHA-1 wrong format')
        '''Verify "Certificate Details" button'''

        certificate_details_btn = self.wait_until_visible(self.by_id(ss_system_parameters.CERTIFICATE_DETAILS_BUTTON_ID)).is_enabled()
        self.is_true(certificate_details_btn,
                     msg='Certificate Details not enabled')

        self.log('SS_11 1. Click "Generate New TLS Key" button')
        '''Verify "Export" button'''
        export_btn = self.wait_until_visible(self.by_id(ss_system_parameters.EXPORT_INTERNAL_TLS_CERT_BUTTON_ID)).is_enabled()
        self.is_true(export_btn,
                     msg='Export not enabled')

        '''Verify "Generate New TLS Key" button'''
        generate_internal_tls_btn = self.wait_until_visible(
            self.by_id(ss_system_parameters.GENERATE_INTERNAL_TLS_KEY_BUTTON_ID)).is_enabled()
        self.is_true(generate_internal_tls_btn,
                     msg='"Generate New TLS Key" not enabled')

        '''Click "Generate New TLS Key" button'''
        self.wait_until_visible(ss_system_parameters.GENERATE_INTERNAL_TLS_KEY_BUTTON_ID, type=By.ID).click()
        self.log('SS_11 3a Generating TLS key is canceled')
        self.wait_until_visible(type=By.XPATH, element=popups.CONFIRM_POPUP_CANCEL_BTN_XPATH).click()
        self.log('Check if tls hash is same as before canceling')
        tls_hash_after_canceling = self.wait_until_visible(type=By.ID,
                                                           element=ss_system_parameters.INTERNAL_TLS_CERT_HASH_ID).text
        self.is_equal(tls_hash_before_generating, tls_hash_after_canceling)
        self.log('Click "Generate New TLS Key" button again')
        self.wait_until_visible(ss_system_parameters.GENERATE_INTERNAL_TLS_KEY_BUTTON_ID, type=By.ID).click()

        '''Script which generates TLS key'''
        cert_gen_script_path = '/usr/share/xroad/scripts/generate_certificate.sh'
        '''Script new name'''
        cert_gen_scipt_new_path = cert_gen_script_path + '.backup'
        '''Rename script'''
        ssh_server_actions.mv(ssh_client, src=cert_gen_script_path,
                              destination=cert_gen_scipt_new_path, sudo=True)

        self.log('SS_11 2, 3. Check for confirmation dialog and confirm the generation')
        popups.confirm_dialog_click(self)

        self.log('Wait until the TLS certificate has been generated.')
        self.wait_jquery()

        self.log('SS_11 4a system failed to generate key')
        try:
            expected_error_msg = GENERATE_CERTIFICATE_NOT_FOUND_ERROR.format(cert_gen_script_path)
            self.log('SS_11 4a.1 System displays an error message "{0}"'.format(expected_error_msg))
            error_message = self.wait_until_visible(type=By.CSS_SELECTOR, element=messages.ERROR_MESSAGE_CSS).text
            self.is_equal(expected_error_msg, error_message)
        finally:
            self.log('Rename generation script back to original')
            ssh_server_actions.mv(ssh_client, src=cert_gen_scipt_new_path,
                                  destination=cert_gen_script_path, sudo=True)

        self.log('SS_11 1. Generate TLS button is pressed')
        self.wait_until_visible(ss_system_parameters.GENERATE_INTERNAL_TLS_KEY_BUTTON_ID, type=By.ID).click()
        self.log('SS_11 3. Generation confirmation popup is confirmed')
        popups.confirm_dialog_click(self)

        self.log('Wait until the TLS certificate has been generated.')
        self.wait_jquery()

        self.log('Get TLS hash after confirming generation')
        tls_hash_after_confirming = self.wait_until_visible(type=By.ID,
                                                            element=ss_system_parameters.INTERNAL_TLS_CERT_HASH_ID).text
        self.log('Check if TLS hash is not same as before')
        self.not_equal(tls_hash_before_generating, tls_hash_after_confirming)

        expected_log_msg = GENERATE_TLS_KEY_AND_CERT
        self.log('SS_11 6. System logs the event "{0}"'.format(expected_log_msg))
        logs_found = log_checker.check_log(expected_log_msg, from_line=current_log_lines + 1)
        self.is_true(logs_found)

        self.log('MEMBER_49/MEMBER_50 - new key has been generated, downloading certificate')

        # If file already exists, delete it first
        if os.path.isfile(certs_filename):
            os.remove(certs_filename)

        # Find and click the "Export" button. Download should start automatically.
        self.by_id(ss_system_parameters.EXPORT_INTERNAL_TLS_CERT_BUTTON_ID).click()

        # Check if file exists every 0.5 seconds or until limit has passed.
        start_time = time.time()
        while True:
            if time.time() - start_time > download_time_limit:
                # Raise AssertionError
                raise AssertionError('Download time limit of {0} seconds passed for file {1}'.format(
                    download_time_limit, certs_download_filename))
            if os.path.isfile(certs_filename):
                try:
                    os.rename(certs_filename, ss1_filename)
                    break
                except OSError:
                    pass
            time.sleep(download_check_interval)

        created_files.append(ss1_filename)
        self.log('MEMBER_49/MEMBER_50 - certificate archive has been downloaded, extracting')

        # We're here, so download succeeded.
        # Extract the archive (tgz format) to downloads directory.
        with tarfile.open(ss1_filename, 'r:gz') as tar:
            # tarfile.extractall does not overwrite files so we need to extract them one by one.
            for fileobj in tar:
                filename = os.path.join(os.path.dirname(fileobj.name), os.path.basename(fileobj.name))
                file_target = self.get_download_path(filename)
                if os.path.isfile(file_target):
                    os.remove(file_target)
                created_files.append(file_target)
                tar.extract(fileobj, self.get_download_path())

        self.log('MEMBER_49/MEMBER_50 - certificate archive has been extracted')

        # UC MEMBER_49. Set connection type to HTTPS_NO_AUTH
        self.log('MEMBER_49. Set {0} connection type to HTTPS_NO_AUTH'.format(client_id))

        # Open "Security Server Clients" page
        self.by_css(sidebar.CLIENTS_BTN_CSS).click()

        # Wait until list is loaded
        self.wait_jquery()

        self.log('Opening client services tab')
        clients_table_vm.open_client_popup_internal_servers(self, client_id=client_id)

        self.log('MEMBER_49 1. Changing internal server connection type to HTTPS_NO_AUTH(SSLNOAUTH)')
        current_log_lines = log_checker.get_line_count()
        case.is_true(clients_table_vm.client_servers_popup_set_connection(self, 'SSLNOAUTH'))

        expected_log_msg = log_constants.SET_SERVICE_CONSUMER_CONNECTION_TYPE
        self.log('MEMBER_49 4. System logs the event "{0}"'.format(expected_log_msg))
        logs_found = log_checker.check_log(expected_log_msg, from_line=current_log_lines + 1)
        self.is_true(logs_found)

        # UC MEMBER_49 test query (1) from TS1:CLIENT1:sub to test service. Query should fail.
        self.log('MEMBER_49 test query (1) {0} to test service. Query should fail.'.format(query_filename))

        case.is_true(testclient_http.check_fail(), msg='MEMBER_49 test query (1) succeeded')

        # UC MEMBER_49 test query (2) to test service using SSL and client certificate. Query should succeed.
        self.log('MEMBER_49 test query (2) to test service using SSL and client certificate. Query should succeed.')
        case.is_true(testclient_https.check_success(), msg='MEMBER_49 test query (2) failed')

        # UC MEMBER_49. Set connection type to HTTPS
        self.log('MEMBER_49. Set {0} connection type to HTTPS'.format(client_id))

        # Set connection type to HTTPS (SSLAUTH)
        case.is_true(clients_table_vm.client_servers_popup_set_connection(self, 'SSLAUTH'),
                     msg='MEMBER_49. Failed to set connection type to SSLAUTH')

        # UC MEMBER_49 test query (3) to test service using SSL and client certificate. Query should fail.
        self.log('MEMBER_49 test query (3) to test service using SSL and client certificate. Query should fail.')
        case.is_true(testclient_https.check_fail(), msg='MEMBER_49 test query (3) succeeded')

        # UC MEMBER_50 1. Select to add internal TLS certificate for a security server client
        self.log('MEMBER_50 1. Select to add internal TLS certificate for a security server client {0}'.format(client_id))

        current_log_lines = log_checker.get_line_count()
        self.log('Click add certificate button')
        self.by_id(popups.CLIENT_DETAILS_POPUP_INTERNAL_SERVERS_ADD_CERTIFICATE_BTN_ID).click()

        upload_button = self.by_id(popups.FILE_UPLOAD_BROWSE_BUTTON_ID)
        '''File with wrong extension'''
        not_existing_file_with_wrong_extension = 'C:\\file.asd'
        self.log('MEMBER_50 3a The uploaded file is not in PEM or DER format')
        xroad.fill_upload_input(self, upload_button, not_existing_file_with_wrong_extension)

        self.log('Clicking submit')
        submit_button = self.by_id(popups.FILE_UPLOAD_SUBMIT_BUTTON_ID)
        submit_button.click()
        self.log('Waiting for error message')
        time.sleep(0.5)
        self.wait_jquery()
        expected_error_msg = messages.TSL_CERTIFICATE_INCORRECT_FILE_FORMAT
        self.log('MEMBER_50 3a.1 System displays the error message "{0}"'.format(expected_error_msg))
        error_message = self.wait_until_visible(type=By.CSS_SELECTOR, element=messages.ERROR_MESSAGE_CSS).text
        self.is_equal(expected_error_msg, error_message)
        expected_log_msg = log_constants.ADD_INTERNAL_TLS_CERT_FAILED
        self.log('MEMBER_50 3a.2 System logs the event "{0}"'.format(expected_log_msg))
        logs_found = log_checker.check_log(expected_log_msg,
                                           from_line=current_log_lines + 1)
        self.is_true(logs_found)
        self.log('MEMBER_50 3a.3a. Canceling uploading popup')
        self.by_xpath(popups.FILE_UPLOAD_CANCEL_BTN_XPATH).click()

        self.log('MEMBER_50 1. Add certificate button is pressed again')
        self.by_id(popups.CLIENT_DETAILS_POPUP_INTERNAL_SERVERS_ADD_CERTIFICATE_BTN_ID).click()

        self.log('MEMBER_50 2. Uploading certificate from local system')
        xroad.fill_upload_input(self, upload_button, client_cert_path)

        self.log('MEMBER_50 3. Verify valid file format')
        self.log('MEMBER_50 4. Verify unique certificate')

        self.log('MEMBER_50 5. System saves the certificate')
        submit_button = self.by_id(popups.FILE_UPLOAD_SUBMIT_BUTTON_ID)
        submit_button.click()
        time.sleep(0.5)
        self.wait_jquery()
        message = self.wait_until_visible(type=By.CSS_SELECTOR, element=messages.NOTICE_MESSAGE_CSS).text
        success_message = CERTIFICATE_IMPORT_SUCCESSFUL
        self.log('MEMBER_50 5. System displays the message {0}'.format(success_message))
        self.is_equal(success_message, message)

        expected_log_msg = log_constants.ADD_INTERNAL_TLS_CERT
        self.log('MEMBER_50 6. System logs the event "{0}"'.format(expected_log_msg))
        logs_found = log_checker.check_log(expected_log_msg, from_line=current_log_lines + 1)
        self.is_true(logs_found)

        # UC MEMBER_50 4a. Try to upload duplicate certificate.
        self.log('MEMBER_50 4a. Try to upload duplicate certificate.')

        current_log_lines = log_checker.get_line_count()
        self.log('Click add button')
        self.by_id(popups.CLIENT_DETAILS_POPUP_INTERNAL_SERVERS_ADD_CERTIFICATE_BTN_ID).click()

        self.log('Fill the upload popup')
        upload_button = self.by_id(popups.FILE_UPLOAD_BROWSE_BUTTON_ID)
        xroad.fill_upload_input(self, upload_button, client_cert_path)

        self.log('Confirm TLS adding')
        submit_button = self.by_id(popups.FILE_UPLOAD_SUBMIT_BUTTON_ID)
        submit_button.click()
        self.log('Wait until error message visible')
        time.sleep(0.5)
        self.wait_jquery()
        expected_error_msg = TSL_CERTIFICATE_ALREADY_EXISTS
        self.log('MEMBER_50 4a.1 System displays the error message "{0}"'.format(expected_error_msg))
        error_message = self.wait_until_visible(type=By.CSS_SELECTOR, element=messages.ERROR_MESSAGE_CSS).text
        self.is_equal(error_message, expected_error_msg)
        expected_log_msg = ADD_INTERNAL_TLS_CERT_FAILED
        self.log('MEMBER_50 4a.2 System logs the event "{0}"'.format(expected_log_msg))
        logs_found = log_checker.check_log(expected_log_msg, from_line=current_log_lines + 1)
        self.is_true(logs_found)
        self.log('MEMBER_50 4a.3a Canceling uploading popup')
        self.by_xpath(popups.FILE_UPLOAD_CANCEL_BTN_XPATH).click()

        # UC MEMBER_50 test query (4) to test service using SSL and client certificate. Query should succeed.
        self.log('MEMBER_50 test query (4) to test service using SSL and client certificate. Query should succeed.')

        # Set client certificate and key
        testclient_https.client_certificate = (client_cert_path, client_key_path)

        case.is_true(testclient_https.check_success(), msg='MEMBER_50 test query (4) failed')

        # UC MEMBER_50 set test client to use TS2 TLS certificate
        self.log('MEMBER_50 set test client to use TS2 TLS certificate')

        # First, get the certificate. For this, we need to get webdriver to go to TS2
        self.reload_webdriver(url=ss2_host, username=ss2_user, password=ss2_pass)

        # Click "System Parameters" in sidebar
        self.by_css(sidebar.SYSTEM_PARAMETERS_BTN_CSS).click()

        self.wait_jquery()

        # UC SS_12 1. Select to export internal TLS certificate of the security server
        self.log('SS_12 1. Select to export internal TLS certificate of the security server')

        if os.path.isfile(certs_filename):
            os.remove(certs_filename)

        # Find and click the "Export" button. Download should start automatically.
        self.by_id(ss_system_parameters.EXPORT_INTERNAL_TLS_CERT_BUTTON_ID).click()

        # Check if file exists every 0.5 seconds or until limit has passed.
        start_time = time.time()
        while True:
            if os.path.isfile(certs_filename):
                break
            if time.time() - start_time > download_time_limit:
                # Raise AssertionError
                raise AssertionError('Download time limit of {0} seconds passed for file {1}'.format(
                    download_time_limit, certs_download_filename))
            time.sleep(download_check_interval)

        os.rename(certs_filename, ss2_filename)

        created_files.append(ss2_filename)
        self.log('SS_12 2, 3. Certificate archive has been downloaded and saved, extracting')

        # We're here, so download succeeded.

        # Extract the archive (tgz format) to downloads directory.
        with tarfile.open(ss2_filename, 'r:gz') as tar:
            # tarfile.extractall does not overwrite files so we need to extract them one by one.
            for fileobj in tar:
                filename = self.get_download_path(os.path.join(ss2_certs_directory, os.path.dirname(fileobj.name),
                                                               os.path.basename(fileobj.name)))
                file_target = self.get_download_path(filename)
                if os.path.isfile(file_target):
                    os.remove(file_target)
                created_files.append(file_target)
                tar.extract(fileobj, self.get_download_path(ss2_certs_directory))

        self.log('SS_12. Certificate archive has been extracted')

        # UC SS_12 test query (5) to test service using SSL and TS2 certificate. Query should fail.
        self.log('SS_12 test query (5) to test service using SSL and client certificate, verify TS2. Query should fail.')

        try:
            testclient_https_ss2.check_fail()
            case.is_true(False, msg='SS_12 test query (5) failed but not with an SSLError.')
        except SSLError:
            # We're actually hoping to get an SSLError so we're good.
            pass

        # UC SS_12 test query (6) to test service using SSL and TS1 certificate. Query should succeed.
        self.log(
            'SS_12 test query (6) to test service using SSL and client certificate, verify TS1. Query should succeed.')

        case.is_true(testclient_https.check_success(), msg='SS_12 test query (6) failed')

        # UC SERVICE_20 1. Test service is configured from http to https. TLS check disabled.
        self.log(
            'SERVICE_20 1. Test service is configured from http to https. TLS check disabled.'.format(new_service_url))

        # Open "Security Server Clients" page
        self.by_css(sidebar.CLIENTS_BTN_CSS).click()

        # Wait until list is loaded
        self.wait_jquery()

        # Open client popup using shortcut button to open it directly at Services tab.
        clients_table_vm.open_client_popup_services(self, client_id=provider_id)

        # Find the service under the specified WSDL in service list (and expand the WSDL services list if not open yet)
        service_row = clients_table_vm.client_services_popup_find_service(self, wsdl_url=wsdl_url,
                                                                          service_name=testservice_name)

        # Click on the service row to select it
        service_row.click()

        # Open service parameters by finding the "Edit" button and clicking it.
        edit_service_button = self.by_id(popups.CLIENT_DETAILS_POPUP_EDIT_WSDL_BTN_ID)

        # Click the "Edit" button to open "Edit Service Parameters" popup
        edit_service_button.click()

        # UC SERVICE_20 2. Save service settings.
        self.log('SERVICE_20 2. Save service settings.')
        warning, error = configure_service.edit_service(self, service_url=new_service_url, verify_tls=False)
        case.is_none(error, msg='SERVICE_20 2. Got error when trying to update service URL')

        # UC SERVICE_20 test query (7) to test service using SSL and TS1 certificate. Query should succeed.
        self.log('SERVICE_20 test query (7) to test service using SSL and client certificate. Query should succeed.')
        case.is_true(testclient_https.check_success(), msg='SERVICE_20 test query (7) failed')

        # UC SERVICE_20 1. Test service is set to https with TLS certificate check enabled.
        self.log('SERVICE_20 1. Test service is https. TLS check enabled.'.format(new_service_url))

        # Click the "Edit" button to open "Edit Service Parameters" popup
        edit_service_button.click()

        # UC SERVICE_20 2. Save service settings.
        self.log('SERVICE_20 2. Save service settings.')
        configure_service.edit_service(self, service_url=new_service_url, verify_tls=True)

        # UC SERVICE_20 test query (8) to test service using SSL and TS1 certificate. Query should succeed.
        self.log('SERVICE_20 test query (8) to test service using SSL and client certificate. Query should fail.')

        case.is_true(testclient_https.check_fail(faults=['Server.ServerProxy.ServiceFailed.SslAuthenticationFailed']),
                     msg='SERVICE_20 test query (8) succeeded')

        # UC MEMBER_50 1. Import test service TLS certificate to security server TS2
        self.log('MEMBER_50 1. Import test service TLS certificate to security server TS2')

        # Click tab "Internal Servers"
        self.by_css(clients_table_vm.INTERNAL_CERTS_TAB_TITLE_CSS).click()

        # Wait until everything is loaded.
        self.wait_jquery()

        # Find the "Add" button and click it.
        self.by_id(popups.CLIENT_DETAILS_POPUP_INTERNAL_SERVERS_ADD_CERTIFICATE_BTN_ID).click()

        self.log('MEMBER_50 2. Uploading certificate from local system')

        # Get the upload button
        upload_button = self.by_id(popups.FILE_UPLOAD_BROWSE_BUTTON_ID)
        xroad.fill_upload_input(self, upload_button, mock_cert_path)

        submit_button = self.by_id(popups.FILE_UPLOAD_SUBMIT_BUTTON_ID)
        submit_button.click()

        self.log('MEMBER_50 3. Verify valid file format')
        self.log('MEMBER_50 4. Verify unique certificate')

        self.log('MEMBER_50 5. System saves the certificate')

        # UC SERVICE_20 test query (9) to test service using SSL and client certificate. Should succeed.
        self.log('SERVICE_20 test query (9) to test service using SSL and client certificate. Query should succeed.')

        case.is_true(testclient_https.check_success(), msg='SERVICE_20 test query (9) failed')

        # Remove all created files
        if delete_created_files:
            self.log('MEMBER_49/MEMBER_50 removing downloaded files')
            self.remove_files(created_files)

    return local_tls
