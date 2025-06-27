from datetime import datetime, timezone
from dateutil.tz import gettz  # for timezone conversion
from dateutil import parser  # use parse for robust ISO parsing
from zoneinfo import ZoneInfo
from typing import Optional, Union

def to_dt(val: Union[str, None, datetime]) -> Optional[datetime]:
    '''
    Convert an ISO-format string (or empty string / None) to a datetime,
    or pass through if it's already a datetime.
    '''
    if val is None or val == "":
        return None

    if isinstance(val, str):
        return datetime.fromisoformat(val)

    # assume it's already a datetime
    return val

def datetimes_match(dt1: datetime, dt2: datetime) -> bool:
    """
    Return True if dt1 and dt2 represent the same calendar date and time
    down to the second (ignores microseconds and timezone differences).
    """
    if dt1 is None or dt2 is None:
        return False

    if isinstance(dt1, str):
        # you may need to strip timezone Z or adjust format variants here
        dt1 = datetime.fromisoformat(dt1)

    if isinstance(dt2, str):
        # you may need to strip timezone Z or adjust format variants here
        dt2 = datetime.fromisoformat(dt2)

    # 1) Convert any "aware" datetime to UTC, then drop tzinfo
    if dt1.tzinfo is not None:
        dt1 = dt1.astimezone(timezone.utc).replace(tzinfo=None)
    if dt2.tzinfo is not None:
        dt2 = dt2.astimezone(timezone.utc).replace(tzinfo=None)

    # 2) Zero out microseconds
    dt1 = dt1.replace(microsecond=0)
    dt2 = dt2.replace(microsecond=0)

    # 3) Compare
    return dt1 == dt2

def to_pst(ts_input) -> str:
    # If input is a string, parse it to a datetime
    if isinstance(ts_input, str):
        if ts_input.endswith('Z'):
            ts_input = ts_input[:-1] + '+00:00'
        dt = parser.parse(ts_input)
    elif isinstance(ts_input, datetime):
        dt = ts_input
    else:
        raise ValueError("Unsupported type for timestamp input")

    # Convert to Pacific time zone
    tz = gettz('America/Los_Angeles') or gettz('US/Pacific')
    pst = dt.astimezone(tz)

    return pst.strftime('%b %d, %Y %I:%M:%S %p')
