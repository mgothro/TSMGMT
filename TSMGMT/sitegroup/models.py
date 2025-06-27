import os
from datetime import datetime
from dataclasses import dataclass, field
from typing import List, Dict, Optional
from ..db.connection import execute_query
from lxml import etree
import logging
from datetime import datetime
from logging.handlers import RotatingFileHandler

# -----------------------------------------------------------------------------
# Module-level logger configuration
# -----------------------------------------------------------------------------

# Create a logger for this module
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)  # capture everything > DEBUG

# Formatter for both console and file
formatter = logging.Formatter(
    fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

# Console handler (stdout)
ch = logging.StreamHandler()
ch.setLevel(logging.DEBUG)
ch.setFormatter(formatter)
logger.addHandler(ch)

# File handler (rotates when it gets too big)
log_dir = os.path.expanduser(r"C:\inetpub\logs\sitegroup")
os.makedirs(log_dir, exist_ok=True)
fh = RotatingFileHandler(
    filename=os.path.join(log_dir, "sitegroup.log"),
    maxBytes=5*1024*1024,   # 5 MB
    backupCount=3,          # keep last 3 files
    encoding="utf-8"
)
fh.setLevel(logging.INFO)  # only INFO goes to disk
fh.setFormatter(formatter)
logger.addHandler(fh)

class Sitegroup:
    """
    Represents a sitegroup and provides access to its configuration and data.

    Attributes:
        CONF_PATHS (dict):  Predefined configuration paths for different sitegroups.
        SPECIAL_DIRECTORIES (list):  List of directories with special handling.
    """
    CONF_PATHS = {
        'default': r'C:\inetpub\wwwroot\web\sms\Conf',
        'dcyf': r'C:\inetpub\wwwroot\web\sms2\Conf',
        'others': r'C:\inetpub\wwwroot\web\sms3\Conf',
    }

    SPECIAL_DIRECTORIES = [
        'sfsummertogether', 'daa', 'chicagoprivate2223', 'urbanimpact',
        'nextuprfp', 'learn24', 'myspark', 'aeis', 'tips', 'dfss'
    ]

    def __init__(
        self,
        directory: str,
        *,
        sitegroupid:    Optional[str]           = None,
        conf_path:    Optional[str]             = None,
        systemname:    Optional[str]            = None,
        xml_files:   Optional[List[str]]        = None,
        person_types:   Optional[List[str]]     = None,
        service_formats: Optional[List[str]]    = None,
        shared_entities: Optional[List[str]]    = None,
        global_settings: Optional[Dict[str, str]] = None,
        site_list:      Optional[List['Site']]  = None,
        domain_list:      Optional[List['Domain']]  = None,
        user_list:      Optional[List['User']]  = None,
        contractcycle_list : Optional[List['ContractCycle']] = None,
        automated_jobs: Optional[List['AutomatedJob']] = None,
    ):
        self._directory       = directory.lower()
        self._starting_path   = self.get_starting_path()

        # pre-loaded caches (if provided, properties won't re-query)
        self._sitegroupid     = sitegroupid
        self._conf_path       = conf_path
        self._systemname      = systemname
        self._person_types    = person_types
        self._xml_files       = xml_files
        self._service_formats = service_formats
        self._shared_entities = shared_entities
        self._global_settings = global_settings
        self._site_list       = site_list
        self._domain_list     = domain_list
        self._user_list       = user_list
        self._contractcycle_list = contractcycle_list
        self._automated_jobs  = automated_jobs

        logger.debug(f"Initialized Sitegroup with directory='{self._directory}', starting_path='{self._starting_path}'")

    @property
    def directory(self) -> str:
        """str: The directory name of the sitegroup (lowercase)."""
        return self._directory

    @property
    def systemname(self) -> Optional[str]:
        """str: The system name"""

        if self._systemname is None:
            sql = f"SELECT IsNull(SystemName, 'N/A') as systemname FROM SiteGroupDetail WHERE Directory = '{self._directory}'"
            logger.debug(f"Querying systemname with SQL: {sql}")
            results = execute_query(sql)
            if not results:
                error_msg = f"Directory '{self._directory}' does not exist (Sitegroup.py)."
                logger.error(error_msg)
                raise ValueError(error_msg)
            # Convert results into a single string
            self._systemname = str(results[0]["SystemName"])
            logger.debug(f"Found systemname='{self._systemname}'")
        return self._systemname

    def get_starting_path(self) -> str:
        """
        Determines the starting path for configuration based on the directory.

        Returns:
            str: The starting path for configuration.
        """
        # Decide which path to use
        if self._directory in self.SPECIAL_DIRECTORIES:
            logger.debug(f"Directory '{self._directory}' is in SPECIAL_DIRECTORIES; using 'others' path.")
            return self.CONF_PATHS['others']

        path = self.CONF_PATHS.get(self._directory, self.CONF_PATHS['default'])
        logger.debug(f"Using path='{path}' for directory='{self._directory}'")
        return path

    @property
    def sitegroupid(self) -> str:
        """str: The SiteGroupID from the database.  Raises ValueError if not found."""
        if self._sitegroupid is None:
            sql = f"SELECT SiteGroupID FROM SiteGroupDetail WHERE Directory = '{self._directory}'"
            logger.debug(f"Querying sitegroupid with SQL: {sql}")
            results = execute_query(sql)

            if not results:
                error_msg = f"Directory '{self._directory}' does not exist (Sitegroup.py)."
                logger.error(error_msg)
                raise ValueError(error_msg)

            # Convert results into a single string
            self._sitegroupid = ''.join(str(x["sitegroupid"]) for x in results)
            logger.debug(f"Found sitegroupid='{self._sitegroupid}'")

        return self._sitegroupid

    @property
    def conf_path(self) -> Optional[str]:
        """Optional[str]: The path to the sitegroup's configuration directory, or None if not found."""
        if self._conf_path is None:
            try:
                logger.debug(f"Searching conf_path starting from '{self._starting_path}'")
                for subdir, _, _ in os.walk(self._starting_path):
                    if os.path.basename(subdir).lower() == self._directory:
                        self._conf_path = subdir
                        logger.debug(f"Found conf_path='{self._conf_path}'")
                        break
                if not self._conf_path:
                    logger.warning(f"Could not find conf_path for directory='{self._directory}' within '{self._starting_path}'")
            except Exception as e:
                logger.exception(f"Error finding conf_path: {e}")  # Use exception to log the stack trace

        return self._conf_path

    @property
    def person_types(self) -> List[str]:
        """List[str]: A list of PersonTypeName values from the database."""
        if self._person_types is None:
            sql = f"SELECT PersonTypeName FROM SiteGroupPersonTypeMap WHERE Directory = '{self._directory}'"
            logger.debug(f"Fetching person_types with SQL: {sql}")
            results = execute_query(sql)
            self._person_types = [x["PersonTypeName"] for x in results] if results else []  # Handle empty results
            logger.debug(f"Loaded person_types={self._person_types}")
        return self._person_types

    @property
    def service_formats(self) -> List[str]:
        """List[str]: A list of ServiceFormatName values from the database."""
        if self._service_formats is None:
            sql = f"SELECT ServiceFormatName FROM SiteGroupServiceFormatMap WHERE Directory = '{self._directory}'"
            logger.debug(f"Fetching service_formats with SQL: {sql}")
            results = execute_query(sql)
            self._service_formats = [x["ServiceFormatName"] for x in results] if results else []  # Handle empty results
            logger.debug(f"Loaded service_formats={self._service_formats}")
        return self._service_formats

    @property
    def shared_entities(self) -> List[str]:
        """List[str]: A list of shared entity 'Type' attributes from PropertySettings.xml (lowercase)."""
        if self._shared_entities is None:
            conf_path = self.conf_path
            if conf_path and os.path.isfile(os.path.join(conf_path, 'PropertySettings.xml')):
                prop_settings_file = os.path.join(conf_path, 'PropertySettings.xml')
                logger.debug(f"Parsing PropertySettings.xml at '{prop_settings_file}'")
                try:
                    tree = etree.parse(prop_settings_file)
                    # Extract 'Type' attribute from <Entity> elements, default to empty string, and convert to lowercase
                    self._shared_entities = [x.get('Type', '').lower() for x in tree.xpath('.//Entity')]
                    logger.debug(f"shared_entities={self._shared_entities}")
                except etree.XMLSyntaxError as e:
                    logger.error(f"Error parsing PropertySettings.xml: {e}")
                    self._shared_entities = []  # Initialize to empty list on error
            else:
                self._shared_entities = []  # Initialize to empty list if file not found
                logger.debug("No PropertySettings.xml found or conf_path is None.")
        return self._shared_entities

    @property
    def global_settings(self) -> Dict[str, str]:
        """Dict[str, str]: A dictionary of global settings from GlobalSettings.xml files."""
        if self._global_settings is None:
            self._global_settings = {}
            orig_conf_path = self.conf_path
            current_path = self.conf_path
            logger.debug(f"Loading global_settings starting from '{current_path}'")

            try:
                while current_path and 'conf' in current_path.lower():
                    global_settings_file = os.path.join(current_path, 'GlobalSettings.xml')
                    if os.path.isfile(global_settings_file):
                        # Is this the sitegroup's own GlobalSettings.xml?
                        is_sitegroup_file = (current_path == orig_conf_path)
                        logger.debug(f"Parsing GlobalSettings.xml at '{global_settings_file}' "
                                     f"{'(sitegroup)' if is_sitegroup_file else '(inherited)'}")
                        try:
                            tree = etree.parse(global_settings_file)
                            for setting in tree.xpath('.//GlobalSetting[@Name]'):
                                name = setting.get('Name')
                                if name in self._global_settings:
                                    continue  # first-one-wins

                                # base value
                                value = setting.get('Value', '')

                                # annotate if restricted
                                if setting.xpath('ancestor::Restriction | ancestor::MultiRestriction'):
                                    value = f"{value} (Restricted)"

                                # annotate if inherited (i.e. not from the sitegroup's own file)
                                if not is_sitegroup_file:
                                    value = f"{value} (Inherited)"

                                self._global_settings[name] = value
                                logger.debug(f"Set global_settings[{name}] = '{value}'")
                        except etree.XMLSyntaxError as e:
                            logger.error(f"Error parsing GlobalSettings.xml: {e}")
                    # move up one directory
                    current_path = os.path.dirname(current_path)
            except Exception as e:
                logger.exception(f"Error loading global settings: {e}")

        return self._global_settings

    @property
    def automated_jobs(self) -> List[str]:
        """List[str]: A list of automated jobs from the database."""
        if self._automated_jobs is None:
            sql = f"select job_type, name, sitegroupid, directory, last_run From sitegroup_automated_job_view WHERE Directory = '{self._directory}'"
            logger.debug(f"Fetching automated_jobs with SQL: {sql}")
            results = execute_query(sql)
            self._automated_jobs = [AutomatedJob(x) for x in results] if results else []
        return self._automated_jobs

    @property
    def site_list(self) -> List['Site']:
        """List[Site]: A list of Site objects representing the site list."""
        if self._site_list is None:
            sql = f"EXEC sitegroup_sitelist '{self._directory}'"
            logger.debug(f"Fetching site_list with SQL: {sql}")
            results = execute_query(sql)
            self._site_list = [Site(x) for x in results] if results else []  # Handle empty results
            logger.debug(f"Loaded site_list with {len(self._site_list)} sites")
        return self._site_list

    #todo: add # of users logged in during the past 7 days, or today

    @property
    def user_list(self) -> List['User']:
        """List[User]: A list of User objects representing the user list."""
        if self._user_list is None:
            sql = f'''SELECT DISTINCT ui.UserId, ui.UserName, ui.Email, ActiveStatus
                      FROM users..UserPermissionSetMap upsm WITH (NOLOCK)
                      INNER JOIN sms..SiteGroupDetailSites si
                          ON si.SiteID = upsm.mapID
                          AND si.Directory = '{self._directory}'
                      INNER JOIN users..userinfo ui WITH (NOLOCK)
                          ON ui.userid = upsm.userid
                      WHERE upsm.projectID = 1'''
            logger.debug(f"Fetching user_list with SQL: {sql}")
            results = execute_query(sql)
            self._user_list = [User(x) for x in results] if results else []  # Handle empty results
            logger.debug(f"Loaded user_list with {len(self._user_list)} users")
        return self._user_list

    @property
    def xml_files(self) -> List[str]:
        """List[str]: A list of XML file names in the conf_path."""
        if self._xml_files is None:
            conf_path = self.conf_path
            try:
                if not conf_path or not os.path.exists(conf_path):
                    # More specific error message and logging
                    msg = f"conf_path is invalid or does not exist: '{conf_path}'"
                    logger.warning(msg)
                    self._xml_files = []  # Set to empty list if conf_path is invalid
                    return self._xml_files

                # Gather .xml files in conf_path
                self._xml_files = [file for file in os.listdir(conf_path) if file.endswith(".xml")]
                logger.debug(f"Found {len(self._xml_files)} XML files in '{conf_path}'")
            except Exception as e:
                logger.exception(f"An error occurred while listing XML files: {e}")  # Log the full exception
                self._xml_files = []  # Set to empty list on error

        return self._xml_files

    @property
    def domain_list(self) -> List['Domain']:
        """List[Domain]: A list of Domain objects representing the domain list."""
        if self._domain_list is None:
            sql = f"select * from Domain d with (nolock) where SiteGroupId =  '{self.sitegroupid}'"
            logger.debug(f"Fetching domain_list with SQL: {sql}")
            results = execute_query(sql)
            self._domain_list = [Domain(x) for x in results] if results else []

        return self._domain_list

    @property
    def contractcycle_list(self) -> List['ContractCycle']:
        """List[ContractCycle]: A list of ContractCycle objects representing the contract cycle list."""
        if self._contractcycle_list is None:
            sql = f"select * from ContractCycleSiteGroupMap c where sitegroupid =  '{self.sitegroupid}' order by contractcycleid desc"
            logger.debug(f"Fetching contractcycle_list with SQL: {sql}")
            results = execute_query(sql)
            self._contractcycle_list = [ContractCycle(x) for x in results] if results else []
        return self._contractcycle_list

@dataclass(frozen=True)
class ContractCycle:
    """
    Represents a Contract Cycle entity.
    Attributes:
        contractcycleid (int): The cycle ID.
        description (str): The cycle name.
        sitegroupid (str): The site group ID.
        isarchived (int): whether cycle is active
    """
    contractcycleid: int
    description: str
    sitegroupid: str
    isarchived: int
    _contract_sites: Optional[List['ContractSite']] = field(default=None, init=False, repr=False)

    def __init__(self, row):
        try:
            contractcycleid = row["contractcycleid"]
            description = row["description"]
            sitegroupid = row["sitegroupid"]
            isarchived = row["isarchived"] if 'isarchived' in row else None  # Optional attribute
        except AttributeError as e:
            raise KeyError(f"Missing expected column in row: {e}") from e

        # Use object.__setattr__ to bypass frozen=True for initialization
        object.__setattr__(self, 'contractcycleid', contractcycleid)
        object.__setattr__(self, 'description', description)
        object.__setattr__(self, 'sitegroupid', sitegroupid)
        object.__setattr__(self, 'isarchived', isarchived)

        logger.debug(f"Initialized ContractCycle with contractcycleid='{contractcycleid}', description='{description}'")

    @property
    def contract_sites(self) -> List['Site']:
        """List[Site]: A list of Site objects associated with this contract cycle."""
        if self._contract_sites is None:
            sql = f"select contractid, contractcycleid, agencyname, programname, agencyid, programid, ucontractid, siteid From gms.dbo.ContractsView3 where ContractCycleID = '{self.contractcycleid}' order by agencyname, programname"
            logger.debug(f"Fetching contract_sites with SQL: {sql}")
            results = execute_query(sql)
            sites = [ContractSite(x) for x in results] if results else []
            object.__setattr__(self, '_contract_sites', sites)
            logger.debug(f"Loaded contract_sites with {len(self._contract_sites)} sites")


        return self._contract_sites

@dataclass(frozen=True)
class ContractSite:
    """
    Represents a Contract Site entity.
    Attributes:
        contractid (int): The contract ID.
        contractcycleid (int): The cycle ID.
        agency_name (str): The agency name.
        program_name (str): The program name.
        agency_id (str): The agency ID.
        program_id (str): The program ID.
        ucontractid (str): The unique contract ID.
        siteid (int): The site ID.
    """
    contractid: int
    contractcycleid: int
    agency_name: str
    program_name: str
    agency_id: str
    program_id: str
    ucontractid: str
    siteid: int

    def __init__(self, row):
        try:
            # Access attributes directly, assuming they are named as in the class definition
            contractid = row["contractid"]
            contractcycleid = row["contractcycleid"]
            agency_name = row["agencyname"]
            program_name = row["programname"]
            agency_id = row["agencyid"]
            program_id = row["programid"]
            ucontractid = row["ucontractid"]
            siteid = row["siteid"]
        except AttributeError as e:
            raise KeyError(f"Missing expected column in row: {e}") from e

        # Use object.__setattr__ to bypass frozen=True for initialization
        object.__setattr__(self, 'contractid', contractid)
        object.__setattr__(self, 'contractcycleid', contractcycleid)
        object.__setattr__(self, 'agency_name', agency_name)
        object.__setattr__(self, 'program_name', program_name)
        object.__setattr__(self, 'agency_id', agency_id)
        object.__setattr__(self, 'program_id', program_id)
        object.__setattr__(self, 'ucontractid', ucontractid)
        object.__setattr__(self, 'siteid', siteid)

@dataclass(frozen=True)
class Domain:
    """
    Represents a Domain entity.
    Attributes:
        domainid (int): The domain ID.
        name (str): The domain name.
        sitegroupid (str): The site group ID.
    """
    domainid: int
    sitegroupid: str
    domainname: str
    domaintype: str
    domain_description: str
    creationdate : datetime
    
    def __init__(self, row):
        try:
            # Access attributes directly, assuming they are named as in the class definition
            domainid = row["domainid"]
            name = row["name"]
            sitegroupid = row["sitegroupid"]
            domaintype = row["domaintype"]
            domain_description = row["domain_description"]
            creationdate = row["creationdate"] if 'creationdate' in row else None  # Optional attribute
        except AttributeError as e:
            raise KeyError(f"Missing expected column in row: {e}") from e

        # Use object.__setattr__ to bypass frozen=True for initialization
        object.__setattr__(self, 'domainid', domainid)
        object.__setattr__(self, 'name', name)
        object.__setattr__(self, 'sitegroupid', sitegroupid)
        object.__setattr__(self, 'domaintype', domaintype)
        object.__setattr__(self, 'domain_description', domain_description)
        object.__setattr__(self, 'creationdate', creationdate)
                    
@dataclass(frozen=True)
class AutomatedJob:
    """
    Represents an Automated Job entity.
    Attributes:
        job_type (str): The job type.
        name (str): The job name.
        sitegroupid (str): The site group ID.
        directory (str): The directory name.
        last_run (datetime): The last run time of the job.
    """
    job_type: str
    name: str
    sitegroupid: str
    directory: str
    last_run: datetime  # Optional attribute for last run time

    def __init__(self, row):
        try:
            # Access attributes directly, assuming they are named as in the class definition
            job_type = row["job_type"]
            name = row["name"]
            sitegroupid = row["sitegroupid"]
            directory = row["directory"]
            last_run = row['last_run'] if 'last_run' in row else None  # Optional attribute']

        except AttributeError as e:  # Corrected exception type to AttributeError
            raise KeyError(f"Missing expected column in row: {e}") from e

        # Use object.__setattr__ to bypass frozen=True for initialization
        object.__setattr__(self, 'job_type', job_type)
        object.__setattr__(self, 'name', name)
        object.__setattr__(self, 'sitegroupid', sitegroupid)
        object.__setattr__(self, 'directory', directory)
        object.__setattr__(self, 'last_run', last_run)

@dataclass(frozen=True)
class Site:
    """
    Represents a Site entity.

    Attributes:
        siteid (int): The site ID.
        agency_name (str): The agency name.
        site_name (str): The site name.
    """
    siteid: int
    agency_name: str
    site_name: str

    def __init__(self, row):
        """
        Initializes a Site object.  Raises KeyError if expected columns are missing.
        """
        try:
            # Access attributes directly, assuming they are named as in the class definition
            siteid = row["siteid"]
            agency_name = row["agencyname"]
            site_name = row["sitename"]
        except AttributeError as e:  # Corrected exception type to AttributeError
            raise KeyError(f"Missing expected column in row: {e}") from e

        # Use object.__setattr__ to bypass frozen=True for initialization
        object.__setattr__(self, 'siteid', siteid)
        object.__setattr__(self, 'agency_name', agency_name)
        object.__setattr__(self, 'site_name', site_name)

@dataclass(frozen=True)
class User:
    """
    Represents a User entity.

    Attributes:
        userid (int): The user ID.
        username (str): The username.
        email (str): The email address.
        active_status (int): The active status.
    """
    userid: int
    username: str
    email: str
    active_status: int

    def __init__(self, row):
        """
        Initializes a User object. Raises KeyError if expected columns are missing.
        """
        try:
            # Access attributes directly, assuming they are named as in the class definition
            userid = row["userid"]
            username = row["username"]
            email = row["email"]
            active_status = row["activestatus"]
        except AttributeError as e:  # Corrected exception type to AttributeError
            raise KeyError(f"Missing expected column in row: {e}") from e

        # Use object.__setattr__ to bypass frozen=True for initialization
        object.__setattr__(self, 'userid', userid)
        object.__setattr__(self, 'username', username)
        object.__setattr__(self, 'email', email)
        object.__setattr__(self, 'active_status', active_status)